from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select

from backend.database.connection import SessionLocal
from backend.database.models import Mention, Organization, PipelineRun, StrategicAngle
from backend.scoring.formulas import get_period_bounds, get_period_datetime_bounds

OWN_ORGANIZATION_NAME = "ARMA"
DEFAULT_PLATFORMS = ["linkedin", "instagram", "facebook", "x"]
DEFAULT_ANGLE_COUNT = 4
MODEL_PROVIDER = "rule_based"
MODEL_NAME = "business-signal-strategist-v2"

CATEGORY_ANGLE_TEMPLATES: dict[str, tuple[str, str]] = {
    "competitor": (
        "Stabilité & performance",
        "Construire une prise de parole prudente sur la continuité et la qualité opérationnelle, sans attribuer à ARMA une performance qui n’est pas documentée et sans attaquer les concurrents.",
    ),
    "opportunity": (
        "Partenariat public-privé",
        "Présenter les enjeux des partenariats avec les collectivités et, uniquement si les références sont validées en interne, l’expérience d’ARMA sur des services comparables.",
    ),
    "regulation": (
        "Conformité & transparence",
        "Expliquer les évolutions réglementaires et les exigences de traçabilité ; ne présenter une pratique d’ARMA que lorsqu’une preuve interne ou publique la confirme.",
    ),
    "innovation": (
        "Innovation urbaine durable",
        "Présenter les tendances numériques, circulaires et bas-carbone du secteur, sans attribuer une technologie à ARMA si elle n’apparaît pas dans les preuves fournies.",
    ),
    "sector": (
        "Ancrage marocain durable",
        "Relier les enjeux des villes marocaines à une approche de proximité ; ne citer une ville, un contrat ou une présence d’ARMA que si la source le démontre.",
    ),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_own_organization(session) -> Organization:
    organization = session.scalar(
        select(Organization).where(
            Organization.name == OWN_ORGANIZATION_NAME,
            Organization.is_active.is_(True),
        )
    )
    if organization is None:
        raise RuntimeError("Organisation ARMA absente. Lancez backend.database.seed.")
    return organization


def get_category_signals(session, period_start: date, period_end: date) -> list[tuple[str, int, float]]:
    start_dt, end_dt = get_period_datetime_bounds(period_start, period_end)
    effective_date = func.coalesce(Mention.manual_published_at, Mention.published_at)
    rows = session.execute(
        select(
            Mention.business_category,
            func.count(Mention.id),
            func.avg(Mention.business_relevance_score),
        )
        .where(
            Mention.display_in_marketing.is_(True),
            Mention.content_type.in_(["news_article", "social_post"]),
            Mention.business_relevance_score >= 0.62,
            Mention.business_category.is_not(None),
            effective_date >= start_dt,
            effective_date < end_dt,
        )
        .group_by(Mention.business_category)
        .order_by(
            func.count(Mention.id).desc(),
            func.avg(Mention.business_relevance_score).desc(),
        )
    ).all()
    return [(str(category), int(count), float(avg_score or 0.0)) for category, count, avg_score in rows]


def get_evidence(session, category: str, period_start: date, period_end: date, limit: int = 3) -> list[Mention]:
    start_dt, end_dt = get_period_datetime_bounds(period_start, period_end)
    effective_date = func.coalesce(Mention.manual_published_at, Mention.published_at)
    return list(
        session.scalars(
            select(Mention)
            .where(
                Mention.display_in_marketing.is_(True),
                Mention.content_type.in_(["news_article", "social_post"]),
                Mention.business_relevance_score >= 0.62,
                Mention.business_category == category,
                effective_date >= start_dt,
                effective_date < end_dt,
            )
            .order_by(
                Mention.business_relevance_score.desc().nulls_last(),
                effective_date.desc(),
            )
            .limit(limit)
        )
    )


def generate_strategic_angles(
    period_type: str = "weekly",
    period_end: date | None = None,
    angle_count: int = DEFAULT_ANGLE_COUNT,
) -> None:
    """Transforme la veille qualifiée en quatre angles métier traçables."""

    session = SessionLocal()
    pipeline_id: int | None = None
    try:
        period_start, resolved_end = get_period_bounds(period_type, period_end)
        organization = get_own_organization(session)

        pipeline = PipelineRun(
            run_type="strategic_angle_generation",
            source_id=None,
            watch_query_id=None,
            status="running",
            started_at=utc_now(),
            statistics={
                "period_type": period_type,
                "period_start": str(period_start),
                "period_end": str(resolved_end),
                "input": "qualified_business_intelligence",
            },
        )
        session.add(pipeline)
        session.commit()
        session.refresh(pipeline)
        pipeline_id = pipeline.id

        signals = get_category_signals(session, period_start, resolved_end)
        selected = signals[: max(1, min(angle_count, 4))]

        created = 0
        for category, count, avg_score in selected:
            title, base_description = CATEGORY_ANGLE_TEMPLATES.get(
                category,
                ("Signal sectoriel à valoriser", "Transformer ce signal de veille en communication factuelle pour ARMA."),
            )
            evidence = get_evidence(session, category, period_start, resolved_end)
            titles = [item.title or item.business_summary or item.raw_text[:100] for item in evidence]
            rationale = (
                f"{count} signal(s) qualifié(s), pertinence moyenne {avg_score * 100:.0f} %. "
                + ("Sources principales : " + " ; ".join(titles) if titles else "")
            ).strip()

            angle = StrategicAngle(
                organization_id=organization.id,
                pipeline_run_id=pipeline.id,
                title=title,
                description=base_description,
                rationale=rationale,
                priority_score=round(count * max(avg_score, 0.1), 3),
                status="proposed",
                target_platforms=DEFAULT_PLATFORMS,
                model_provider=MODEL_PROVIDER,
                model_name=MODEL_NAME,
                model_version="2",
                generated_at=utc_now(),
                extra_data={
                    "business_category": category,
                    "period_start": str(period_start),
                    "period_end": str(resolved_end),
                    "mention_ids": [item.id for item in evidence],
                },
            )
            session.add(angle)
            created += 1
            print(f"Angle proposé : {title} ({category})")

        pipeline.status = "completed"
        pipeline.finished_at = utc_now()
        pipeline.items_received = len(signals)
        pipeline.items_created = created
        pipeline.statistics = {**(pipeline.statistics or {}), "categories": [item[0] for item in selected]}
        session.commit()

        print("\nGénération des angles stratégiques terminée.")
        print(f"- Angles créés : {created}")

    except Exception as error:
        session.rollback()
        if pipeline_id is not None:
            pipeline = session.get(PipelineRun, pipeline_id)
            if pipeline is not None:
                pipeline.status = "failed"
                pipeline.finished_at = utc_now()
                pipeline.error_message = str(error)
                session.commit()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    generate_strategic_angles()
