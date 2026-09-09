from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from backend.alerts.service import alert_is_displayable
from backend.processing.city_detection import detect_city
from backend.api.deps import get_db_session
from backend.api.schemas import AlertResponse, AlertStatusUpdate, ResponseDraftResponse
from backend.database.models import (
    Alert,
    Mention,
    MentionAnalysis,
    MentionOrganization,
    Organization,
    ResponseDraft,
    Source,
)
from backend.processing.content_deduplication import event_similarity
from backend.scoring.formulas import get_period_datetime_bounds
from backend.scoring.periods import HANDLED_ALERT_STATUSES
from backend.processing.mention_governance import clean_display_text, clean_source_name
from backend.services.facebook_screenshot_service import find_latest_capture_for_url

router = APIRouter(prefix="/api/alerts", tags=["alerts"])
MENTION_EXCERPT_LENGTH = 280
ALERT_STATUSES = ("open", "acknowledged", "resolved", "ignored")


def get_content_label(content_type: str, source_type: str) -> str:
    if content_type == "social_comment":
        return "COMMENTAIRE À TRAITER"
    if content_type == "social_post":
        return "PUBLICATION"
    if content_type == "news_article" or source_type == "online_press":
        return "ARTICLE"
    if source_type == "search_api":
        return "ARTICLE / WEB"
    return "MENTION"




def get_collection_provider(mention: Mention) -> str | None:
    payload = mention.raw_payload or {}
    if not isinstance(payload, dict):
        return None
    collection = payload.get("_collection")
    if not isinstance(collection, dict):
        return None
    return str(collection.get("source_provider") or collection.get("aggregator") or "").strip().lower() or None


def get_comment_triage(mention: Mention) -> dict | None:
    payload = mention.raw_payload or {}
    if not isinstance(payload, dict):
        return None
    triage = payload.get("_comment_triage")
    return triage if isinstance(triage, dict) else None


def resolve_sentiment(
    mention: Mention,
    analysis_sentiment: str | None,
) -> tuple[str | None, str]:
    """Sentiment affiché sur la carte d'alerte, et sa provenance.

    Pour un commentaire social, le tri dédié (`_comment_triage`) fait foi car
    il est calculé sur le texte du commentaire lui-même. Pour tout autre
    contenu, on utilise l'analyse NLP courante de la mention. Sans l'un ni
    l'autre, la carte reste neutre visuellement plutôt que d'afficher une
    couleur trompeuse.
    """

    triage = get_comment_triage(mention)
    triage_sentiment = (triage or {}).get("sentiment")
    if mention.content_type == "social_comment" and triage_sentiment:
        return str(triage_sentiment), "comment_triage"
    if analysis_sentiment:
        return str(analysis_sentiment), "mention_analysis"
    if triage_sentiment:
        return str(triage_sentiment), "comment_triage"
    return None, "unknown"


def get_validation_details(alert: Alert) -> dict:
    """Trace de la validation humaine, stockée dans `metadata` de l'alerte."""

    details = alert.extra_data or {}
    if not isinstance(details, dict):
        details = {}
    return {
        "is_handled": alert.status in HANDLED_ALERT_STATUSES,
        "validated_by": details.get("validated_by"),
        "validation_note": details.get("validation_note"),
        "validated_at": alert.resolved_at or alert.acknowledged_at,
    }


def resolve_status_filter(status: str | None) -> list[str] | None:
    """Traduit le paramètre `status` en liste de statuts SQL.

    Accepte `open`, une liste `resolved,acknowledged`, `handled` (toutes les
    alertes validées) et `all` (aucun filtre). Sans ce paramètre étendu, une
    alerte validée disparaissait définitivement du portail.
    """

    if status is None:
        return None
    raw = status.strip().lower()
    if raw in {"", "all", "toutes"}:
        return None
    if raw == "handled":
        return sorted(HANDLED_ALERT_STATUSES)
    requested = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = [item for item in requested if item not in ALERT_STATUSES]
    if unknown:
        raise HTTPException(
            422,
            f"Statut inconnu : {', '.join(unknown)}. "
            f"Valeurs acceptées : {', '.join(ALERT_STATUSES)}, handled, all.",
        )
    return requested


@router.get("", response_model=list[AlertResponse])
def read_alerts(
    status: str | None = "open",
    organization: str | None = None,
    limit: int = 50,
    days: int | None = 90,
    period_start: date | None = None,
    period_end: date | None = None,
    content_type: str | None = None,
    city: str | None = None,
    session: Session = Depends(get_db_session),
) -> list[dict]:
    """Liste les alertes, avec le type réel du contenu source.

    `city` restreint la liste aux alertes rattachées à cette ville. Une alerte
    appartient à une seule ville — celle de la source la plus spécifique —
    pour que la répartition par ville totalise exactement le nombre d'alertes
    de la période.
    """

    statement = (
        select(
            Alert,
            Organization.name,
            Source.name,
            Source.source_type,
            Mention,
            MentionAnalysis.sentiment_label,
        )
        .join(MentionOrganization, MentionOrganization.id == Alert.mention_organization_id)
        .join(Organization, Organization.id == MentionOrganization.organization_id)
        .join(Mention, Mention.id == MentionOrganization.mention_id)
        .join(Source, Source.id == Mention.source_id)
        # Le sentiment de la mention pilote la couleur de la carte dans le
        # portail (rouge / vert / bleu). L'outerjoin garantit qu'une alerte
        # sans analyse NLP courante reste affichée, en gris.
        .outerjoin(
            MentionAnalysis,
            (MentionAnalysis.mention_organization_id == MentionOrganization.id)
            & (MentionAnalysis.is_current.is_(True)),
        )
    )
    statuses = resolve_status_filter(status)
    if statuses is not None:
        statement = statement.where(Alert.status.in_(statuses))
    if organization is not None:
        statement = statement.where(Organization.name == organization)
    if content_type is not None:
        statement = statement.where(Mention.content_type == content_type)
    # Toutes les alertes sont rattachées à la période par la date de publication
    # réelle du contenu. La date de collecte ne déplace jamais une ancienne alerte.
    effective_date = func.coalesce(Mention.manual_published_at, Mention.published_at)
    if (period_start is None) != (period_end is None):
        raise HTTPException(422, "period_start et period_end doivent être fournis ensemble.")
    if period_start is not None and period_end is not None:
        if period_end < period_start:
            raise HTTPException(422, "period_end doit être >= period_start.")
        start_dt, end_dt = get_period_datetime_bounds(period_start, period_end)
        statement = statement.where(effective_date >= start_dt, effective_date < end_dt)
    elif days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 3650)))
        statement = statement.where(effective_date >= cutoff)
    # Dans une vue hebdomadaire, l'ordre utile est celui de la publication
    # réelle, pas celui de la création de l'alerte par le pipeline.
    statement = statement.order_by(
        effective_date.desc(), Alert.created_at.desc()
    ).limit(max(1, min(limit, 100)))

    results: list[dict] = []
    for (
        alert,
        organization_name,
        source_name,
        source_type,
        mention,
        analysis_sentiment,
    ) in session.execute(statement).all():
        triage = get_comment_triage(mention)
        # Tous les commentaires négatifs pertinents doivent apparaître dans les
        # alertes, même si une réponse publique n'est pas recommandée (ex. insulte
        # seule). Le bouton d'envoi reste alors masqué, mais le signal réputationnel
        # n'est plus perdu.
        if not alert_is_displayable(mention.content_type, mention.raw_payload):
            continue
        sentiment_label, sentiment_source = resolve_sentiment(mention, analysis_sentiment)
        parent = session.get(Mention, mention.parent_mention_id) if mention.parent_mention_id else None
        source_display = clean_source_name(mention.author_name, source_name, mention.url)
        title_display = clean_display_text(mention.display_title or mention.title, mention.raw_text, social=mention.content_type.startswith("social"))["display_title"]
        results.append(
            {
                "id": alert.id,
                "mention_id": mention.id,
                "data_type": "demo" if (mention.raw_payload or {}).get("is_demo") else "real",
                "organization_name": organization_name,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "reason": alert.reason,
                "status": alert.status,
                "source_name": source_display,
                "content_type": mention.content_type,
                "content_label": get_content_label(mention.content_type, source_type),
                "author_name": mention.author_name,
                "published_at": mention.manual_published_at or mention.published_at,
                "collected_at": mention.collected_at,
                "parent_title": (parent.display_title or parent.title) if parent else title_display,
                "parent_url": parent.url if parent else None,
                "engagement": mention.engagement or {},
                "mention_url": mention.url or (parent.url if parent else None),
                "mention_excerpt": (mention.clean_text or mention.raw_text or "")[:MENTION_EXCERPT_LENGTH],
                # La ville n'est stockee dans aucune colonne : elle est lue dans
                # le texte, puis le titre, puis la publication parente, puis
                # l'URL. `parent.title` vaut souvent le seul nom du media
                # (« Le360 ») : c'est le TEXTE du post qui porte le territoire,
                # d'ou parent_text avant parent_title.
                **detect_city(
                    text=mention.clean_text or mention.raw_text,
                    title=mention.display_title or mention.title,
                    parent_text=(parent.clean_text or parent.raw_text) if parent else None,
                    parent_title=(parent.display_title or parent.title) if parent else title_display,
                    url=mention.url or (parent.url if parent else None),
                ),
                "comment_triage": triage,
                "sentiment_label": sentiment_label,
                "sentiment_source": sentiment_source,
                "risk_categories": list((alert.extra_data or {}).get("risk_categories") or []),
                "assigned_to": alert.assigned_to,
                "acknowledged_at": alert.acknowledged_at,
                "resolved_at": alert.resolved_at,
                **get_validation_details(alert),
                "created_at": alert.created_at,
                "grouped_count": 1,
                "grouped_alert_ids": [alert.id],
                "related_sources": [{"name": source_display, "url": mention.url, "mention_id": mention.id}],
                "facebook_capture": find_latest_capture_for_url(parent.url if parent else mention.url),
                "collection_provider": get_collection_provider(mention),
                "_event": {"title": (parent.display_title or parent.title) if parent else title_display, "summary": mention.clean_text or mention.raw_text, "category": alert.alert_type},
                "_parent_mention_id": mention.parent_mention_id,
                "_content_type": mention.content_type,
            }
        )
    grouped: list[dict] = []
    for item in results:
        target = None
        for existing in grouped:
            # Chaque commentaire négatif est une alerte individuelle. Deux
            # citoyens sous le même post ne doivent jamais être fusionnés.
            if item["_content_type"] == "social_comment" or existing["_content_type"] == "social_comment":
                continue
            same_parent = item["_parent_mention_id"] and item["_parent_mention_id"] == existing["_parent_mention_id"]
            if same_parent or event_similarity(item["_event"], existing["_event"]) >= 0.72:
                target = existing
                break
        if target is None:
            grouped.append(item)
            continue
        target["grouped_count"] += 1
        target["grouped_alert_ids"].extend(item["grouped_alert_ids"])
        for source in item["related_sources"]:
            if source not in target["related_sources"]:
                target["related_sources"].append(source)
        severity_rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        if severity_rank.get(item["severity"], 0) > severity_rank.get(target["severity"], 0):
            target["severity"] = item["severity"]
        # Une carte regroupée prend la couleur du signal le plus défavorable :
        # un événement qui contient une mention négative reste rouge.
        sentiment_rank = {"positive": 1, "neutral": 2, "negative": 3}
        if sentiment_rank.get(item["sentiment_label"], 0) > sentiment_rank.get(
            target["sentiment_label"], 0
        ):
            target["sentiment_label"] = item["sentiment_label"]
            target["sentiment_source"] = item["sentiment_source"]
    for item in grouped:
        item.pop("_event", None)
        item.pop("_parent_mention_id", None)
        item.pop("_content_type", None)

    # Le filtre ville est appliqué après le regroupement, sur la ville retenue
    # pour l'alerte. Compter une alerte sous chacune des villes qu'elle cite
    # gonflerait la répartition au-delà du nombre réel d'alertes.
    if city:
        wanted = city.strip().casefold()
        grouped = [
            item
            for item in grouped
            if (item.get("city") or "").casefold() == wanted
        ]

    return grouped


@router.get("/{alert_id}/response", response_model=ResponseDraftResponse)
def read_alert_response(
    alert_id: int,
    session: Session = Depends(get_db_session),
) -> dict:
    draft = session.scalar(select(ResponseDraft).where(ResponseDraft.alert_id == alert_id))
    if draft is None:
        raise HTTPException(
            status_code=404,
            detail=f"Aucun brouillon de réponse pour l'alerte {alert_id}.",
        )
    details = draft.extra_data or {}
    return {
        "id": draft.id,
        "alert_id": draft.alert_id,
        "content_by_language": draft.content_by_language,
        "tone": draft.tone,
        "status": draft.status,
        "generated_at": draft.generated_at,
        "action": details.get("action", "monitor"),
        "action_label": details.get("action_label", "Surveillance"),
        "category": details.get("category", "negative_mention_to_review"),
        "reply_eligible": bool(details.get("reply_eligible", False)),
        "requires_human_validation": bool(
            details.get("requires_human_validation", True)
        ),
        "internal_note": details.get("internal_note"),
        "rationale": details.get("rationale"),
        "recommended_channel": details.get("recommended_channel"),
        "model_provider": draft.model_provider,
        "model_name": draft.model_name,
        "model_version": draft.model_version,
    }


@router.patch("/{alert_id}/status", response_model=AlertResponse)
def update_alert_status(
    alert_id: int,
    payload: AlertStatusUpdate,
    session: Session = Depends(get_db_session),
    x_arma_user: str | None = Header(default=None),
) -> dict:
    """Met à jour le statut opérationnel d'une alerte depuis le portail.

    C'est l'action derrière le bouton « Valider » : l'alerte reste en base et
    reste consultable, elle est simplement marquée comme traitée, avec qui l'a
    validée et quand.
    """

    row = session.execute(
        select(
            Alert,
            Organization.name,
            Source.name,
            Source.source_type,
            Mention,
            MentionAnalysis.sentiment_label,
        )
        .join(MentionOrganization, MentionOrganization.id == Alert.mention_organization_id)
        .join(Organization, Organization.id == MentionOrganization.organization_id)
        .join(Mention, Mention.id == MentionOrganization.mention_id)
        .join(Source, Source.id == Mention.source_id)
        .outerjoin(
            MentionAnalysis,
            (MentionAnalysis.mention_organization_id == MentionOrganization.id)
            & (MentionAnalysis.is_current.is_(True)),
        )
        .where(Alert.id == alert_id)
    ).first()

    if row is None:
        raise HTTPException(status_code=404, detail="Alerte introuvable.")

    alert, organization_name, source_name, source_type, mention, analysis_sentiment = row
    alert.status = payload.status
    now = datetime.now(timezone.utc)
    details = dict(alert.extra_data or {})
    if payload.status == "acknowledged":
        alert.acknowledged_at = alert.acknowledged_at or now
    elif payload.status in {"resolved", "ignored"}:
        alert.resolved_at = now
    elif payload.status == "open":
        # Réouverture : on efface la trace de validation pour ne pas laisser
        # croire que l'alerte a déjà été traitée.
        alert.resolved_at = None
        alert.acknowledged_at = None
        details.pop("validated_by", None)
        details.pop("validation_note", None)
        details.pop("validated_at", None)

    if payload.status in HANDLED_ALERT_STATUSES:
        validated_by = (payload.validated_by or x_arma_user or "human_user").strip()[:200]
        details["validated_by"] = validated_by
        details["validated_at"] = now.isoformat()
        if payload.note is not None:
            note = payload.note.strip()
            details["validation_note"] = note or None

    # Réaffectation explicite : SQLAlchemy ne détecte pas la mutation en place
    # d'un dictionnaire JSONB.
    alert.extra_data = details
    session.commit()
    session.refresh(alert)

    sentiment_label, sentiment_source = resolve_sentiment(mention, analysis_sentiment)
    parent = session.get(Mention, mention.parent_mention_id) if mention.parent_mention_id else None
    return {
        "id": alert.id,
        "mention_id": mention.id,
        "data_type": "demo" if (mention.raw_payload or {}).get("is_demo") else "real",
        "organization_name": organization_name,
        "alert_type": alert.alert_type,
        "severity": alert.severity,
        "reason": alert.reason,
        "status": alert.status,
        "source_name": clean_source_name(mention.author_name, source_name, mention.url),
        "content_type": mention.content_type,
        "content_label": get_content_label(mention.content_type, source_type),
        "author_name": mention.author_name,
        "published_at": mention.manual_published_at or mention.published_at,
        "collected_at": mention.collected_at,
        "parent_title": parent.title if parent else None,
        "parent_url": parent.url if parent else None,
        "engagement": mention.engagement or {},
        "mention_url": mention.url,
        "mention_excerpt": (mention.clean_text or mention.raw_text or "")[:MENTION_EXCERPT_LENGTH],
        **detect_city(
            text=mention.clean_text or mention.raw_text,
            title=mention.display_title or mention.title,
            parent_text=(parent.clean_text or parent.raw_text) if parent else None,
            parent_title=(parent.display_title or parent.title) if parent else None,
            url=mention.url or (parent.url if parent else None),
        ),
        "comment_triage": get_comment_triage(mention),
        "sentiment_label": sentiment_label,
        "sentiment_source": sentiment_source,
        "risk_categories": list((alert.extra_data or {}).get("risk_categories") or []),
        "assigned_to": alert.assigned_to,
        "acknowledged_at": alert.acknowledged_at,
        "resolved_at": alert.resolved_at,
        **get_validation_details(alert),
        "created_at": alert.created_at,
        "facebook_capture": find_latest_capture_for_url(parent.url if parent else mention.url),
        "collection_provider": get_collection_provider(mention),
    }
