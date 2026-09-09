from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.deps import get_db_session
from backend.database.models import (
    Alert,
    FacebookReplyAudit,
    Mention,
    MentionAnalysis,
    MentionOrganization,
    Organization,
    PipelineRun,
    Source,
)
from backend.ai.comment_triage.service import triage_social_comments
from backend.scoring.formulas import get_period_datetime_bounds
from backend.alerts.service import generate_alerts_for_negative_mentions
from backend.processing.mention_governance import analyse_comment
from backend.services.facebook_comment_collection_service import (
    collect_facebook_comments,
    comments_collection_status,
)
from backend.services.meta_facebook_comments_service import integration_status as meta_integration_status, send_reply

router = APIRouter(prefix="/api/facebook", tags=["facebook"])


def _comment_period_bounds(
    *,
    period_start: date | None,
    period_end: date | None,
    days: int,
) -> tuple[datetime, datetime, dict]:
    """Retourne une fenêtre [début, fin) basée sur la date de publication.

    La période métier est la semaine de publication réelle du commentaire
    (manual_published_at/published_at), et non sa date de collecte par ARMA.
    """
    if (period_start is None) != (period_end is None):
        raise HTTPException(422, "period_start et period_end doivent être fournis ensemble.")
    if period_start is not None and period_end is not None:
        if period_end < period_start:
            raise HTTPException(422, "period_end doit être >= period_start.")
        start_dt, end_dt = get_period_datetime_bounds(period_start, period_end)
        return start_dt, end_dt, {
            "period_start": period_start,
            "period_end": period_end,
            "period_days": (period_end - period_start).days + 1,
            "date_basis": "published_at",
        }

    safe_days = max(1, min(days, 3650))
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=safe_days)
    return start_dt, end_dt, {
        "period_start": start_dt.date(),
        "period_end": end_dt.date(),
        "period_days": safe_days,
        "date_basis": "published_at",
    }


class ReplyRequest(BaseModel):
    response_text: str = Field(min_length=1, max_length=4000)
    language: str = Field(pattern="^(fr|ar)$")
    human_approved: bool


class ApproveDraftRequest(BaseModel):
    response_text: str = Field(min_length=1, max_length=4000)
    language: str = Field(pattern="^(fr|ar)$")


def _is_demo(mention: Mention) -> bool:
    payload = mention.raw_payload or {}
    return bool(payload.get("is_demo") or payload.get("demo") or payload.get("data_type") == "demo")


def _platform_comment_id(mention: Mention) -> str:
    payload = mention.raw_payload or {}
    collection = payload.get("_collection") if isinstance(payload, dict) else {}
    candidates = [
        (collection or {}).get("platform_comment_id") if isinstance(collection, dict) else None,
        payload.get("commentId") if isinstance(payload, dict) else None,
        payload.get("id") if isinstance(payload, dict) else None,
        mention.external_id,
    ]
    for candidate in candidates:
        value = str(candidate or "").strip()
        if not value:
            continue
        if value.startswith("facebook_comment:"):
            value = value.split(":", 1)[1]
        if value:
            return value
    raise HTTPException(409, "Identifiant Facebook du commentaire indisponible.")


@router.get("/integration/status")
def read_integration_status() -> dict:
    collection = comments_collection_status()
    meta = meta_integration_status()
    return {
        **collection,
        "send_provider": "meta",
        "send_available": bool(meta.get("available")),
        "send_status": meta.get("status"),
        "send_message": meta.get("message"),
        "demo_enabled": bool(meta.get("demo_enabled")),
    }




@router.get("/comments/diagnostic")
def comments_diagnostic(session: Session = Depends(get_db_session)) -> dict:
    """Diagnostic sans secret de la chaîne Facebook commentaires."""

    from backend.services.apify_facebook_comments_service import load_retained_facebook_urls

    urls = load_retained_facebook_urls()
    total_comments = session.scalar(
        select(func.count(Mention.id)).where(Mention.content_type == "social_comment")
    ) or 0
    facebook_comments = session.scalar(
        select(func.count(Mention.id))
        .join(Source, Source.id == Mention.source_id)
        .where(Mention.content_type == "social_comment", Source.name == "Facebook")
    ) or 0
    latest_run = session.scalar(
        select(PipelineRun)
        .where(PipelineRun.run_type == "apify_facebook_comment_collection")
        .order_by(PipelineRun.started_at.desc(), PipelineRun.id.desc())
        .limit(1)
    )

    # Un commentaire collecté n'est visible dans /api/alerts que s'il a été
    # trié (raw_payload._comment_triage présent) ET qu'une alerte a été créée
    # pour lui. Ces compteurs permettent de diagnostiquer en un coup d'œil un
    # blocage à n'importe quelle étape de la chaîne.
    all_facebook_comments = list(
        session.scalars(
            select(Mention)
            .join(Source, Source.id == Mention.source_id)
            .where(Mention.content_type == "social_comment", Source.name == "Facebook")
        )
    )
    untriaged = 0
    actionable_relevant = 0
    actionable_with_open_alert = 0
    for comment in all_facebook_comments:
        payload = comment.raw_payload or {}
        triage = payload.get("_comment_triage") if isinstance(payload, dict) else None
        if not isinstance(triage, dict):
            untriaged += 1
            continue
        is_actionable = bool(
            triage.get("relevant")
            and (triage.get("sentiment") == "negative" or triage.get("reply_recommended"))
        )
        if not is_actionable:
            continue
        actionable_relevant += 1
        has_open_alert = session.scalar(
            select(func.count(Alert.id))
            .join(MentionOrganization, MentionOrganization.id == Alert.mention_organization_id)
            .where(
                MentionOrganization.mention_id == comment.id,
                Alert.status.in_(["open", "acknowledged", "resolved"]),
            )
        ) or 0
        if has_open_alert:
            actionable_with_open_alert += 1

    return {
        "integration": comments_collection_status(),
        "retained_facebook_urls_count": len(urls),
        "retained_facebook_urls": urls[:20],
        "social_comments_in_database": int(total_comments),
        "facebook_comments_in_database": int(facebook_comments),
        "facebook_comments_not_yet_triaged": untriaged,
        "facebook_comments_actionable": actionable_relevant,
        "facebook_comments_actionable_with_alert": actionable_with_open_alert,
        "facebook_comments_actionable_missing_alert": actionable_relevant - actionable_with_open_alert,
        "pipeline_health": (
            "ok"
            if untriaged == 0 and actionable_relevant == actionable_with_open_alert
            else "attention_requise : lancez scripts/sync_apify_facebook_comments.py "
            "ou POST /api/facebook/comments/sync pour trier les commentaires en attente "
            "et générer leurs alertes."
        ),
        "latest_apify_run": None if latest_run is None else {
            "id": latest_run.id,
            "status": latest_run.status,
            "started_at": latest_run.started_at,
            "finished_at": latest_run.finished_at,
            "items_received": latest_run.items_received,
            "items_created": latest_run.items_created,
            "items_updated": latest_run.items_duplicated,
            "error": latest_run.error_message,
            "statistics": latest_run.statistics,
        },
    }

@router.get("/comments/summary")
def comments_summary(
    organization: str = "ARMA",
    days: int = 90,
    period_start: date | None = None,
    period_end: date | None = None,
    session: Session = Depends(get_db_session),
) -> dict:
    """Résume les commentaires publiés pendant la période métier."""

    start_dt, end_dt, period_meta = _comment_period_bounds(
        period_start=period_start, period_end=period_end, days=days
    )

    rows = session.execute(
        select(MentionAnalysis.sentiment_label, func.count(MentionAnalysis.id))
        .join(MentionOrganization, MentionOrganization.id == MentionAnalysis.mention_organization_id)
        .join(Mention, Mention.id == MentionOrganization.mention_id)
        .join(Organization, Organization.id == MentionOrganization.organization_id)
        .join(Source, Source.id == Mention.source_id)
        .where(
            Mention.content_type == "social_comment",
            Organization.name == organization,
            MentionOrganization.include_in_reputation.is_(True),
            MentionAnalysis.is_current.is_(True),
            func.coalesce(Mention.manual_published_at, Mention.published_at) >= start_dt,
            func.coalesce(Mention.manual_published_at, Mention.published_at) < end_dt,
        )
        .group_by(MentionAnalysis.sentiment_label)
    ).all()
    counts = {str(label): int(count) for label, count in rows}

    linked_total = session.scalar(
        select(func.count(Mention.id))
        .join(MentionOrganization, MentionOrganization.mention_id == Mention.id)
        .join(Organization, Organization.id == MentionOrganization.organization_id)
        .where(
            Mention.content_type == "social_comment",
            Organization.name == organization,
            func.coalesce(Mention.manual_published_at, Mention.published_at) >= start_dt,
            func.coalesce(Mention.manual_published_at, Mention.published_at) < end_dt,
        )
    ) or 0
    noise_excluded = session.scalar(
        select(func.count(Mention.id))
        .join(MentionOrganization, MentionOrganization.mention_id == Mention.id)
        .join(Organization, Organization.id == MentionOrganization.organization_id)
        .where(
            Mention.content_type == "social_comment",
            Organization.name == organization,
            Mention.processing_status == "ignored",
            func.coalesce(Mention.manual_published_at, Mention.published_at) >= start_dt,
            func.coalesce(Mention.manual_published_at, Mention.published_at) < end_dt,
        )
    ) or 0
    open_negative_alerts = session.scalar(
        select(func.count(Alert.id))
        .join(MentionOrganization, MentionOrganization.id == Alert.mention_organization_id)
        .join(Mention, Mention.id == MentionOrganization.mention_id)
        .join(Organization, Organization.id == MentionOrganization.organization_id)
        .where(
            Mention.content_type == "social_comment",
            Organization.name == organization,
            Alert.status.in_(["open", "acknowledged"]),
            func.coalesce(Mention.manual_published_at, Mention.published_at) >= start_dt,
            func.coalesce(Mention.manual_published_at, Mention.published_at) < end_dt,
        )
    ) or 0

    linked_mentions = list(
        session.scalars(
            select(Mention)
            .join(MentionOrganization, MentionOrganization.mention_id == Mention.id)
            .join(Organization, Organization.id == MentionOrganization.organization_id)
            .where(
                Mention.content_type == "social_comment",
                Organization.name == organization,
                func.coalesce(Mention.manual_published_at, Mention.published_at) >= start_dt,
                func.coalesce(Mention.manual_published_at, Mention.published_at) < end_dt,
            )
        )
    )
    actionable = 0
    posts_with_comments: set[int] = set()
    for mention in linked_mentions:
        payload = mention.raw_payload or {}
        triage = payload.get("_comment_triage") if isinstance(payload, dict) else None
        if isinstance(triage, dict) and triage.get("relevant") and triage.get("reply_recommended"):
            actionable += 1
        if mention.parent_mention_id:
            posts_with_comments.add(mention.parent_mention_id)

    classified_total = sum(counts.values())
    return {
        "organization": organization,
        "period_days": period_meta["period_days"],
        "period_start": period_meta["period_start"],
        "period_end": period_meta["period_end"],
        "date_basis": period_meta["date_basis"],
        "linked_comments": int(linked_total),
        "classified_comments": classified_total,
        "positive": counts.get("positive", 0),
        "neutral": counts.get("neutral", 0),
        "negative": counts.get("negative", 0),
        "actionable": actionable,
        "posts_with_comments": len(posts_with_comments),
        "noise_excluded": int(noise_excluded),
        "open_negative_alerts": int(open_negative_alerts),
        "open_comment_alerts": int(open_negative_alerts),
        "comment_score_weight": 0.25,
        "note": "Seuls les commentaires dont la date de publication Facebook tombe dans la période sont comptés. La date de collecte ARMA reste disponible pour la traçabilité mais ne décide pas de la semaine. Chaque commentaire utile pèse 0,25 dans le score.",
    }


@router.get("/comments/by-post")
def comments_by_post(
    organization: str = "ARMA",
    days: int = 90,
    period_start: date | None = None,
    period_end: date | None = None,
    session: Session = Depends(get_db_session),
) -> list[dict]:
    """Détail des commentaires dont la date de publication appartient à la période."""

    start_dt, end_dt, _period_meta = _comment_period_bounds(
        period_start=period_start, period_end=period_end, days=days
    )
    comments = list(
        session.scalars(
            select(Mention)
            .join(MentionOrganization, MentionOrganization.mention_id == Mention.id)
            .join(Organization, Organization.id == MentionOrganization.organization_id)
            .where(
                Mention.content_type == "social_comment",
                Organization.name == organization,
                func.coalesce(Mention.manual_published_at, Mention.published_at) >= start_dt,
                func.coalesce(Mention.manual_published_at, Mention.published_at) < end_dt,
            )
            .order_by(func.coalesce(Mention.manual_published_at, Mention.published_at).desc(), Mention.id.desc())
        )
    )
    grouped: dict[int, dict] = {}
    for comment in comments:
        parent = session.get(Mention, comment.parent_mention_id) if comment.parent_mention_id else None
        key = parent.id if parent is not None else -comment.id
        row = grouped.setdefault(
            key,
            {
                "post_id": parent.id if parent is not None else None,
                "post_title": (parent.display_title or parent.title) if parent is not None else "Post parent introuvable",
                "post_url": parent.url if parent is not None else None,
                "collected": 0,
                "classified": 0,
                "positive": 0,
                "neutral": 0,
                "negative": 0,
                "actionable": 0,
                "open_alerts": 0,
                "comments": [],
            },
        )
        row["collected"] += 1
        payload = comment.raw_payload or {}
        triage = payload.get("_comment_triage") if isinstance(payload, dict) else None
        if isinstance(triage, dict) and triage.get("relevant"):
            sentiment = str(triage.get("sentiment") or "neutral")
            row["classified"] += 1
            if sentiment in {"positive", "neutral", "negative"}:
                row[sentiment] += 1
            if triage.get("reply_recommended"):
                row["actionable"] += 1
        alert_id = session.scalar(
            select(Alert.id)
            .join(MentionOrganization, MentionOrganization.id == Alert.mention_organization_id)
            .where(
                MentionOrganization.mention_id == comment.id,
                Alert.status.in_(["open", "acknowledged"]),
            )
            .limit(1)
        )
        if alert_id is not None:
            row["open_alerts"] += 1
        if len(row["comments"]) < 20:
            row["comments"].append(
                {
                    "id": comment.id,
                    "text": comment.clean_text or comment.raw_text,
                    "author_name": comment.author_name,
                    "collected_at": comment.collected_at,
                    "published_at": comment.published_at,
                    "sentiment": triage.get("sentiment") if isinstance(triage, dict) else None,
                    "reply_recommended": bool(triage.get("reply_recommended")) if isinstance(triage, dict) else False,
                    "alert_id": alert_id,
                }
            )
    return sorted(
        grouped.values(),
        key=lambda row: (row["actionable"], row["negative"], row["collected"]),
        reverse=True,
    )


@router.post("/comments/sync")
def sync_comments() -> dict:
    """Collecte les commentaires Facebook ET les rend visibles dans les alertes.

    La seule collecte (``collect_facebook_comments``) enregistre les
    commentaires en base mais ne les classe pas et ne crée aucune alerte : un
    commentaire qui appelle une réponse restait alors invisible dans la
    section "Alertes" du portail tant que le pipeline quotidien complet
    n'avait pas tourné. Ce endpoint manuel enchaîne donc systématiquement
    collecte -> tri -> génération d'alertes, comme le fait le pipeline n8n.
    """

    state = comments_collection_status()
    if not state["collection_available"]:
        return {**state, "synced": 0}
    try:
        collection_result = collect_facebook_comments() or {}
    except RuntimeError as error:
        return {**state, "status": "unavailable", "message": str(error), "synced": 0}

    triage_result: dict = {}
    alerts_result: dict = {}
    try:
        triage_result = triage_social_comments() or {}
    except Exception as error:  # noqa: BLE001 - on ne bloque pas la collecte déjà réussie
        triage_result = {"error": str(error)}
    try:
        alerts_result = generate_alerts_for_negative_mentions() or {}
    except Exception as error:  # noqa: BLE001
        alerts_result = {"error": str(error)}

    return {
        **state,
        **collection_result,
        "status": collection_result.get("status", "completed"),
        "synced": collection_result.get("synced", 0),
        "triage": triage_result,
        "alerts": alerts_result,
        "comments_created": collection_result.get("comments_created", 0),
        "comments_updated": collection_result.get("comments_updated", 0),
        "alerts_created": alerts_result.get("created", 0),
    }




def _collection_provider(mention: Mention) -> str:
    payload = mention.raw_payload or {}
    collection = payload.get("_collection") if isinstance(payload, dict) else {}
    if isinstance(collection, dict):
        return str(collection.get("source_provider") or collection.get("aggregator") or "unknown").lower()
    return "unknown"


@router.get("/comments")
def list_comments(
    limit: int = 100,
    session: Session = Depends(get_db_session),
) -> list[dict]:
    """Liste les commentaires collectés, y compris ceux sans alerte."""

    statement = (
        select(Mention, Source)
        .join(Source, Source.id == Mention.source_id)
        .where(Mention.content_type == "social_comment")
        .order_by(func.coalesce(Mention.manual_published_at, Mention.published_at).desc(), Mention.id.desc())
        .limit(max(1, min(limit, 500)))
    )
    rows: list[dict] = []
    for mention, source in session.execute(statement).all():
        parent = session.get(Mention, mention.parent_mention_id) if mention.parent_mention_id else None
        alert_id = session.scalar(
            select(Alert.id)
            .join(MentionOrganization, MentionOrganization.id == Alert.mention_organization_id)
            .where(MentionOrganization.mention_id == mention.id, Alert.status.in_(["open", "acknowledged"]))
            .order_by(Alert.created_at.desc())
            .limit(1)
        )
        payload = mention.raw_payload or {}
        triage = payload.get("_comment_triage") if isinstance(payload, dict) else None
        arma_relation = session.scalar(
            select(MentionOrganization)
            .join(Organization, Organization.id == MentionOrganization.organization_id)
            .where(MentionOrganization.mention_id == mention.id, Organization.name == "ARMA")
            .limit(1)
        )
        analysis = None
        if arma_relation is not None:
            analysis = session.scalar(
                select(MentionAnalysis)
                .where(
                    MentionAnalysis.mention_organization_id == arma_relation.id,
                    MentionAnalysis.is_current.is_(True),
                )
                .order_by(MentionAnalysis.id.desc())
                .limit(1)
            )
        rows.append({
            "id": mention.id,
            "platform_comment_id": _platform_comment_id(mention),
            "provider": _collection_provider(mention),
            "data_type": "demo" if _is_demo(mention) else "real",
            "source_name": source.name,
            "text": mention.clean_text or mention.raw_text,
            "author_name": mention.author_name,
            "author_handle": mention.author_handle,
            "published_at": mention.published_at,
            "collected_at": mention.collected_at,
            "comment_url": mention.url,
            "post_title": (parent.display_title or parent.title) if parent else None,
            "post_url": parent.url if parent else None,
            "engagement": mention.engagement or {},
            "threading_depth": int(((payload.get("_collection") or {}).get("threading_depth") or payload.get("threadingDepth") or 0)) if isinstance(payload, dict) else 0,
            "triage": triage if isinstance(triage, dict) else None,
            "processing_status": mention.processing_status,
            "included_in_score": bool(arma_relation and arma_relation.include_in_reputation),
            "sentiment": analysis.sentiment_label if analysis is not None else (triage or {}).get("sentiment"),
            "sentiment_confidence": analysis.confidence if analysis is not None else (triage or {}).get("confidence"),
            "alert_id": alert_id,
        })
    return rows


@router.post("/comments/{comment_id}/approve-draft")
def approve_draft(
    comment_id: int,
    payload: ApproveDraftRequest,
    session: Session = Depends(get_db_session),
    x_arma_user: str | None = Header(default=None),
) -> dict:
    mention = session.get(Mention, comment_id)
    if mention is None or mention.content_type != "social_comment":
        raise HTTPException(404, "Commentaire introuvable.")
    audit = FacebookReplyAudit(
        mention_id=mention.id, response_text=payload.response_text.strip(), language=payload.language,
        status="approved", human_approved=True, approved_at=datetime.now(timezone.utc),
        approved_by=(x_arma_user or "human_user")[:200], extra_data={"demo": _is_demo(mention)},
    )
    session.add(audit)
    session.commit()
    session.refresh(audit)
    return {"id": audit.id, "status": audit.status, "message": "Brouillon validé; aucun envoi effectué."}


@router.post("/comments/{comment_id}/reply")
def reply_to_comment(
    comment_id: int,
    payload: ReplyRequest,
    session: Session = Depends(get_db_session),
    x_arma_user: str | None = Header(default=None),
) -> dict:
    mention = session.get(Mention, comment_id)
    if mention is None or mention.content_type != "social_comment":
        raise HTTPException(404, "Commentaire réel introuvable.")
    if _is_demo(mention):
        raise HTTPException(409, "Donnée de démonstration — aucun envoi externe autorisé.")
    if not payload.human_approved:
        raise HTTPException(422, "La validation humaine est obligatoire.")
    raw_payload = mention.raw_payload or {}
    triage = raw_payload.get("_comment_triage") if isinstance(raw_payload, dict) else None
    if isinstance(triage, dict):
        eligible = bool(triage.get("relevant")) and bool(triage.get("reply_recommended"))
    else:
        eligible = analyse_comment(mention.raw_text).get("decision") == "public_reply"
    if not eligible:
        raise HTTPException(409, "Ce commentaire n'est pas éligible à une réponse publique selon le tri validé.")
    sent = session.scalar(select(FacebookReplyAudit).where(FacebookReplyAudit.mention_id == mention.id, FacebookReplyAudit.status == "sent"))
    if sent is not None:
        raise HTTPException(409, "Une réponse a déjà été envoyée à ce commentaire.")
    audit = FacebookReplyAudit(
        mention_id=mention.id, response_text=payload.response_text.strip(), language=payload.language,
        status="sending", human_approved=True, approved_at=datetime.now(timezone.utc),
        approved_by=(x_arma_user or "human_user")[:200],
    )
    session.add(audit)
    session.commit()
    try:
        result = send_reply(_platform_comment_id(mention), payload.response_text.strip())
        audit.status = "sent"
        audit.sent_at = datetime.now(timezone.utc)
        audit.platform_response_id = str(result["id"])
        session.commit()
        return {"id": audit.id, "status": "sent", "platform_response_id": audit.platform_response_id}
    except RuntimeError as error:
        audit.status = "unavailable" if not meta_integration_status()["available"] else "failed"
        audit.api_error = str(error)[:2000]
        session.commit()
        raise HTTPException(503, str(error)) from error
