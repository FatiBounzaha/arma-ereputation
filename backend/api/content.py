from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from backend.api.deps import get_db_session
from backend.api.schemas import (
    GeneratedPostResponse,
    RecentMentionResponse,
    StrategicAngleResponse,
)
from backend.processing.content_deduplication import rank_and_deduplicate
from backend.processing.mention_governance import (
    CATEGORY_LABELS, clean_display_text, clean_source_name, freshness,
    geographic_scope, route_content, specific_business_insight,
)
from backend.services.facebook_retained_links_service import export_retained_facebook_links
from backend.services.facebook_screenshot_service import find_latest_capture_for_url
from backend.scoring.formulas import get_period_datetime_bounds

from backend.database.models import (
    GeneratedPost,
    Mention,
    MentionTopic,
    PostEvidenceMention,
    Source,
    StrategicAngle,
    Topic,
)

router = APIRouter(prefix="/api/content", tags=["content"])


def published_at_expression():
    """Date de publication réelle d'une mention (V11.4)."""

    return func.coalesce(Mention.manual_published_at, Mention.published_at)


def post_evidence_period_filter(start_dt, end_dt):
    """Filtre strict des brouillons par date de publication de leurs preuves.

    Un brouillon appartient à une semaine seulement si au moins une source
    preuve possède une date de publication réelle dans cette semaine.
    `generated_at` et `collected_at` ne servent jamais à rattacher le contenu
    à une période métier.
    """

    published_at = published_at_expression()
    in_period_post_ids = (
        select(PostEvidenceMention.generated_post_id)
        .join(Mention, Mention.id == PostEvidenceMention.mention_id)
        .where(
            published_at >= start_dt,
            published_at < end_dt,
        )
    )
    return GeneratedPost.id.in_(in_period_post_ids)


def angle_has_published_evidence(
    session: Session,
    angle: StrategicAngle,
    period_start: date,
    period_end: date,
) -> bool:
    """Vérifie qu'un angle appartient réellement à la semaine demandée.

    Les bornes stockées dans `extra_data` identifient le run historique, puis
    les `mention_ids` sont revalidés sur leur vraie date de publication.
    Ainsi un ancien angle ou un angle sans publication datée ne peut jamais
    apparaître dans une semaine vide.
    """

    metadata = angle.extra_data or {}
    if str(metadata.get("period_start") or "") != str(period_start):
        return False
    if str(metadata.get("period_end") or "") != str(period_end):
        return False

    mention_ids = [int(value) for value in (metadata.get("mention_ids") or []) if str(value).isdigit()]
    if not mention_ids:
        return False

    start_dt, end_dt = get_period_datetime_bounds(period_start, period_end)
    published_at = published_at_expression()
    count = session.scalar(
        select(func.count(Mention.id)).where(
            Mention.id.in_(mention_ids),
            Mention.display_in_marketing.is_(True),
            Mention.content_type.in_(["news_article", "social_post"]),
            Mention.business_relevance_score >= 0.62,
            published_at >= start_dt,
            published_at < end_dt,
        )
    )
    return bool(count)


class MentionValidationRequest(BaseModel):
    manual_published_at: datetime | None = None
    manual_category: str | None = None
    manual_route: str | None = None
    business_insight: str | None = None
    decision: str = Field(pattern="^(garder|corriger|exclure|historique|transferer_reputation)$")
    notes: str | None = Field(default=None, max_length=4000)


BUSINESS_INSIGHTS: dict[str, str] = {
    "competitor": (
        "Lecture ARMA : surveiller l’impact de ce signal concurrentiel et "
        "valoriser la stabilité, la continuité de service et les preuves de performance d’ARMA."
    ),
    "opportunity": (
        "Lecture ARMA : opportunité à qualifier pour les équipes commerciales et "
        "à transformer en prise de parole sur l’expertise d’ARMA auprès des collectivités."
    ),
    "regulation": (
        "Lecture ARMA : vérifier les impacts opérationnels et préparer une communication "
        "factuelle sur la conformité, la traçabilité et les engagements environnementaux."
    ),
    "innovation": (
        "Lecture ARMA : relier cette tendance aux solutions numériques, circulaires ou "
        "bas-carbone réellement déployées par ARMA."
    ),
    "sector": (
        "Lecture ARMA : signal sectoriel à suivre pour contextualiser les enjeux des villes "
        "et renforcer le positionnement local d’ARMA."
    ),
}


@router.get("/recent-mentions", response_model=list[RecentMentionResponse])
def read_recent_mentions(
    limit: int = 8,
    days: int = 30,
    min_relevance: float = 0.62,
    category: str | None = None,
    include_social: bool = False,
    geography: str = "morocco",
    period_start: date | None = None,
    period_end: date | None = None,
    session: Session = Depends(get_db_session),
) -> list[dict]:
    """Veille métier qualifiée destinée à la vue Marketing Contenu.

    Contrairement à l'ancienne version, cette route n'affiche pas les dernières
    lignes brutes de la base. Elle conserve seulement les éléments validés par
    le filtre de pertinence : concurrence, opportunités, réglementation,
    innovation ou actualité sectorielle.
    """

    # A collection timestamp is never publication evidence.
    effective_date = func.coalesce(Mention.manual_published_at, Mention.published_at)
    if (period_start is None) != (period_end is None):
        raise HTTPException(422, "period_start et period_end doivent être fournis ensemble.")
    if period_start is not None and period_end is not None:
        if period_end < period_start:
            raise HTTPException(422, "period_end doit être >= period_start.")
        start_dt, end_dt = get_period_datetime_bounds(period_start, period_end)
    else:
        start_dt = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))
        end_dt = datetime.now(timezone.utc)

    statement = (
        select(Mention, Source.name)
        .join(Source, Source.id == Mention.source_id)
        .where(
            Mention.display_in_marketing.is_(True),
            Mention.business_relevance_score >= min_relevance,
            effective_date >= start_dt,
            effective_date < end_dt,
            Mention.content_type != "social_comment",
        )
        .order_by(
            Mention.business_relevance_score.desc().nulls_last(),
            effective_date.desc(),
        )
        .limit(min(max(50, limit * 8), 250))
    )

    # La maquette Marketing cible une veille Serper News. Les posts sociaux
    # restent dans le flux e-réputation et ne sont affichés ici que sur demande.
    if not include_social:
        statement = statement.where(Mention.content_type == "news_article")

    if category is not None:
        statement = statement.where(Mention.business_category == category)

    rows = session.execute(statement).all()
    results: list[dict] = []

    for mention, technical_source_name in rows:
        topic_names = session.scalars(
            select(Topic.name)
            .join(MentionTopic, MentionTopic.topic_id == Topic.id)
            .where(MentionTopic.mention_id == mention.id)
        ).all()

        display = clean_display_text(mention.display_title or mention.title, mention.raw_text, social=mention.content_type.startswith("social"))
        category_value = mention.manual_category or mention.business_category or "information_generale"
        published_value = mention.manual_published_at or mention.published_at
        geo = geographic_scope(mention.title, mention.raw_text, mention.city, country=mention.country)
        if geography in {"morocco", "international", "unknown"} and geo["scope"] != geography:
            continue
        route = route_content(category_value, published_value)
        results.append(
            {
                "id": mention.id,
                "title": display["display_title"],
                "summary": mention.display_excerpt or mention.business_summary or clean_display_text(mention.title, mention.clean_text or mention.raw_text)["display_excerpt"],
                # Pour une actualité Serper, author_name contient le média réel.
                "source_name": clean_source_name(mention.author_name, technical_source_name, mention.url),
                "url": mention.url,
                "published_at": mention.manual_published_at or mention.published_at,
                "collected_at": mention.collected_at,
                "published_at_confidence": "confirmed" if mention.manual_published_at else mention.published_at_confidence,
                "published_at_source": "manual" if mention.manual_published_at else mention.published_at_source,
                "topics": list(topic_names),
                "category": category_value,
                "category_label": CATEGORY_LABELS.get(category_value),
                "relevance_score": mention.business_relevance_score,
                "content_type": mention.content_type,
                "business_insight": (mention.route_metadata or {}).get("business_insight") or specific_business_insight(category_value, display["display_title"], mention.raw_text, geo, route["freshness"]),
                "freshness": freshness(mention.manual_published_at or mention.published_at),
                "route": route,
                "validation_status": mention.validation_status,
                "geography": geo,
                "facebook_capture": find_latest_capture_for_url(mention.url),
            }
        )

    return rank_and_deduplicate(results, limit=max(1, min(limit, 50)))


@router.post("/mentions/{mention_id}/validate")
def validate_mention(
    mention_id: int,
    payload: MentionValidationRequest,
    session: Session = Depends(get_db_session),
    x_arma_user: str | None = Header(default=None),
) -> dict:
    mention = session.get(Mention, mention_id)
    if mention is None:
        raise HTTPException(404, "Veille introuvable.")
    if payload.manual_category and payload.manual_category not in CATEGORY_LABELS:
        raise HTTPException(422, "Catégorie métier inconnue.")
    mention.validated_at = datetime.now(timezone.utc)
    mention.validated_by = (x_arma_user or "human_user")[:200]
    mention.validation_status = {"corriger": "corrected", "exclure": "excluded"}.get(payload.decision, "validated")
    mention.validation_notes = payload.notes
    mention.manual_published_at = payload.manual_published_at
    mention.manual_category = payload.manual_category
    mention.manual_route = payload.manual_route
    if payload.decision == "exclure":
        mention.display_in_marketing = False
    mention.route_metadata = {**(mention.route_metadata or {}), "manual_decision": payload.decision, "business_insight": payload.business_insight}
    session.commit()
    export_result = export_retained_facebook_links(session)
    return {"id": mention.id, "validation_status": mention.validation_status, "effective_published_at": mention.manual_published_at or mention.published_at, "facebook_registry_count": export_result["count"]}


@router.get("/angles", response_model=list[StrategicAngleResponse])
def read_angles(
    status: str | None = None,
    limit: int = 4,
    period_start: date | None = None,
    period_end: date | None = None,
    session: Session = Depends(get_db_session),
) -> list[StrategicAngle]:
    """
    Retourne uniquement les angles basés sur des contenus publiés
    pendant la période demandée.
    """

    if (period_start is None) != (period_end is None):
        raise HTTPException(
            422,
            "period_start et period_end doivent être fournis ensemble.",
        )

    statement = (
        select(StrategicAngle)
        .order_by(StrategicAngle.generated_at.desc())
    )

    if status is not None:
        statement = statement.where(StrategicAngle.status == status)

    if period_start is not None and period_end is not None:
        if period_end < period_start:
            raise HTTPException(
                422,
                "period_end doit être >= period_start.",
            )

    angles = list(session.scalars(statement.limit(120)))

    if period_start is not None and period_end is not None:
        angles = [
            angle for angle in angles
            if angle_has_published_evidence(
                session, angle, period_start, period_end
            )
        ]

    if not angles:
        return []

    latest_run_id = angles[0].pipeline_run_id

    latest = [
        angle
        for angle in angles
        if angle.pipeline_run_id == latest_run_id
    ]

    latest.sort(
        key=lambda item: item.priority_score or 0.0,
        reverse=True,
    )

    return latest[: max(1, min(limit, 8))]


@router.get("/posts", response_model=list[GeneratedPostResponse])
def read_posts(
    platform: str | None = None,
    status: str | None = None,
    limit: int = 8,
    period_start: date | None = None,
    period_end: date | None = None,
    session: Session = Depends(get_db_session),
) -> list[dict]:
    """
    Retourne uniquement les brouillons dont les sources ont été
    publiées pendant la période demandée.
    """

    if (period_start is None) != (period_end is None):
        raise HTTPException(
            422,
            "period_start et period_end doivent être fournis ensemble.",
        )

    statement = (
        select(GeneratedPost)
        .order_by(GeneratedPost.generated_at.desc())
    )

    if platform is not None:
        statement = statement.where(
            GeneratedPost.platform == platform
        )

    if status is not None:
        statement = statement.where(
            GeneratedPost.status == status
        )

    start_dt = None
    end_dt = None

    if period_start is not None and period_end is not None:
        if period_end < period_start:
            raise HTTPException(
                422,
                "period_end doit être >= period_start.",
            )

        start_dt, end_dt = get_period_datetime_bounds(
            period_start,
            period_end,
        )

        statement = statement.where(
            post_evidence_period_filter(start_dt, end_dt)
        ).distinct()

    posts = list(session.scalars(statement.limit(80)))

    if not posts:
        return []

    latest_run_id = posts[0].pipeline_run_id

    latest = [
        post
        for post in posts
        if post.pipeline_run_id == latest_run_id
    ]

    latest.sort(
        key=lambda item: (
            item.display_order is None,
            item.display_order or 999,
        )
    )

    output: list[dict] = []

    for post in latest[: max(1, min(limit, 20))]:

        evidence_statement = (
            select(Mention)
            .join(
                PostEvidenceMention,
                PostEvidenceMention.mention_id == Mention.id,
            )
            .where(
                PostEvidenceMention.generated_post_id == post.id
            )
        )

        # Si une période est demandée, seules les preuves dont la vraie date
        # de publication tombe dans cette semaine sont renvoyées. Une preuve
        # sans date ou hors période n'est jamais rattachée via collected_at ou
        # generated_at.
        if start_dt is not None and end_dt is not None:
            published_at = published_at_expression()
            evidence_mentions = list(
                session.scalars(
                    evidence_statement.where(
                        published_at >= start_dt,
                        published_at < end_dt,
                    )
                )
            )
            if not evidence_mentions:
                continue
        else:
            evidence_mentions = list(session.scalars(evidence_statement))

        output.append({
            "id": post.id,
            "organization_id": post.organization_id,
            "strategic_angle_id": post.strategic_angle_id,
            "platform": post.platform,
            "content_by_language": post.content_by_language,
            "image_prompt": post.image_prompt,
            "tone": post.tone,
            "status": post.status,
            "display_order": post.display_order,
            "generated_at": post.generated_at,
            "model_provider": post.model_provider,
            "model_name": post.model_name,
            "model_version": post.model_version,

            "quality_checked": bool(
                (post.extra_data or {}).get("quality_checked")
            ),

            "fallback_used": bool(
                (post.extra_data or {}).get("fallback_used")
                or (post.extra_data or {}).get("fallback")
            ),

            "evidence": [
                {
                    "mention_id": mention.id,
                    "title": (
                        mention.display_title
                        or mention.title
                        or "Source sans titre"
                    ),
                    "url": mention.url,
                    "published_at": (
                        mention.manual_published_at
                        or mention.published_at
                    ),
                    "source": clean_source_name(
                        mention.author_name,
                        None,
                        mention.url,
                    ),
                }
                for mention in evidence_mentions
            ],

            "claim_status": (
                (post.extra_data or {}).get(
                    "claim_status",
                    (
                        "verified"
                        if evidence_mentions
                        else "internal_validation_required"
                    ),
                )
            ),

            "warnings": list(
                (post.extra_data or {}).get("warnings")
                or (
                    []
                    if evidence_mentions
                    else ["Aucune preuve liée à ce brouillon"]
                )
            ),
        })

    return output
