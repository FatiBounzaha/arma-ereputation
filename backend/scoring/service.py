from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from backend.database.connection import SessionLocal
from backend.database.models import (
    Mention,
    MentionAnalysis,
    MentionOrganization,
    MentionTopic,
    Organization,
    PipelineRun,
    ReputationSnapshot,
    Topic,
)
from backend.scoring.formulas import (
    FORMULA_VERSION,
    build_analyst_summary,
    compute_rates,
    compute_reputation_score,
    get_period_bounds,
    get_period_datetime_bounds,
    get_previous_period_bounds,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_sentiment_counts(
    session: Session,
    organization_id: int,
    period_start: date,
    period_end: date,
) -> dict[str, int | float]:
    start_datetime, end_datetime_exclusive = get_period_datetime_bounds(
        period_start=period_start,
        period_end=period_end,
    )
    # La période réputationnelle est basée uniquement sur la date de publication.
    # Une collecte tardive ne déplace jamais une ancienne publication vers la semaine courante.
    effective_date = func.coalesce(Mention.manual_published_at, Mention.published_at)

    # Les commentaires utiles sont intégrés, mais avec un poids moindre afin
    # qu'un fil très actif ne domine pas seul le score hebdomadaire.
    reputation_weight = case(
        (Mention.content_type == "social_comment", 0.25),
        else_=1.0,
    )

    rows = session.execute(
        select(
            MentionAnalysis.sentiment_label,
            func.count(MentionAnalysis.id),
            func.sum(reputation_weight),
        )
        .join(
            MentionOrganization,
            MentionOrganization.id == MentionAnalysis.mention_organization_id,
        )
        .join(Mention, Mention.id == MentionOrganization.mention_id)
        .where(
            MentionOrganization.organization_id == organization_id,
            MentionOrganization.include_in_reputation.is_(True),
            MentionAnalysis.is_current.is_(True),
            effective_date >= start_datetime,
            effective_date < end_datetime_exclusive,
        )
        .group_by(MentionAnalysis.sentiment_label)
    ).all()

    counts_by_label = {label: int(count) for label, count, _ in rows}
    weights_by_label = {label: float(weight or 0) for label, _, weight in rows}
    return {
        "positive_count": counts_by_label.get("positive", 0),
        "neutral_count": counts_by_label.get("neutral", 0),
        "negative_count": counts_by_label.get("negative", 0),
        "positive_weight": weights_by_label.get("positive", 0.0),
        "neutral_weight": weights_by_label.get("neutral", 0.0),
        "negative_weight": weights_by_label.get("negative", 0.0),
    }


def get_dominant_topic(
    session: Session,
    organization_id: int,
    period_start: date,
    period_end: date,
) -> Topic | None:
    start_datetime, end_datetime_exclusive = get_period_datetime_bounds(
        period_start=period_start,
        period_end=period_end,
    )
    # La période réputationnelle est basée uniquement sur la date de publication.
    # Une collecte tardive ne déplace jamais une ancienne publication vers la semaine courante.
    effective_date = func.coalesce(Mention.manual_published_at, Mention.published_at)
    top_topic_id = session.execute(
        select(MentionTopic.topic_id, func.count(MentionTopic.id))
        .join(Mention, Mention.id == MentionTopic.mention_id)
        .join(MentionOrganization, MentionOrganization.mention_id == Mention.id)
        .where(
            MentionOrganization.organization_id == organization_id,
            MentionOrganization.include_in_reputation.is_(True),
            effective_date >= start_datetime,
            effective_date < end_datetime_exclusive,
        )
        .group_by(MentionTopic.topic_id)
        .order_by(func.count(MentionTopic.id).desc())
        .limit(1)
    ).first()
    return session.get(Topic, top_topic_id[0]) if top_topic_id is not None else None


def get_existing_snapshot(
    session: Session,
    organization_id: int,
    period_start: date,
    period_end: date,
    formula_version: str = FORMULA_VERSION,
) -> ReputationSnapshot | None:
    return session.scalar(
        select(ReputationSnapshot).where(
            ReputationSnapshot.organization_id == organization_id,
            ReputationSnapshot.period_start == period_start,
            ReputationSnapshot.period_end == period_end,
            ReputationSnapshot.formula_version == formula_version,
        )
    )


def calculate_snapshot_values(
    session: Session,
    organization: Organization,
    period_start: date,
    period_end: date,
) -> dict:
    counts = get_sentiment_counts(
        session=session,
        organization_id=organization.id,
        period_start=period_start,
        period_end=period_end,
    )
    mention_count = int(
        counts["positive_count"] + counts["neutral_count"] + counts["negative_count"]
    )
    reputation_score = compute_reputation_score(
        positive_count=counts["positive_weight"],
        neutral_count=counts["neutral_weight"],
        negative_count=counts["negative_weight"],
    )
    positive_rate, negative_rate = compute_rates(
        positive_count=int(counts["positive_count"]),
        neutral_count=int(counts["neutral_count"]),
        negative_count=int(counts["negative_count"]),
    )
    dominant_topic = get_dominant_topic(
        session=session,
        organization_id=organization.id,
        period_start=period_start,
        period_end=period_end,
    )
    return {
        **counts,
        "mention_count": mention_count,
        "reputation_score": reputation_score,
        "positive_rate": positive_rate,
        "negative_rate": negative_rate,
        "dominant_topic": dominant_topic,
    }


def upsert_snapshot(
    session: Session,
    *,
    organization: Organization,
    pipeline_run_id: int,
    period_type: str,
    period_start: date,
    period_end: date,
    previous_snapshot: ReputationSnapshot | None,
) -> ReputationSnapshot:
    values = calculate_snapshot_values(
        session=session,
        organization=organization,
        period_start=period_start,
        period_end=period_end,
    )
    delta = (
        values["reputation_score"] - previous_snapshot.reputation_score
        if previous_snapshot is not None and previous_snapshot.mention_count > 0
        else None
    )
    summary = build_analyst_summary(
        organization_name=organization.name,
        period_start=period_start,
        period_end=period_end,
        mention_count=values["mention_count"],
        positive_rate=values["positive_rate"],
        negative_rate=values["negative_rate"],
        reputation_score=values["reputation_score"],
        delta_previous_period=delta,
    )
    dominant_topic = values["dominant_topic"]
    if dominant_topic is not None:
        summary += f" Sujet dominant : {dominant_topic.name}."

    snapshot = get_existing_snapshot(
        session=session,
        organization_id=organization.id,
        period_start=period_start,
        period_end=period_end,
    )
    if snapshot is None:
        snapshot = ReputationSnapshot(
            organization_id=organization.id,
            period_start=period_start,
            period_end=period_end,
            period_type=period_type,
            formula_version=FORMULA_VERSION,
        )
        session.add(snapshot)

    snapshot.pipeline_run_id = pipeline_run_id
    snapshot.reputation_score = values["reputation_score"]
    snapshot.mention_count = values["mention_count"]
    snapshot.positive_count = int(values["positive_count"])
    snapshot.neutral_count = int(values["neutral_count"])
    snapshot.negative_count = int(values["negative_count"])
    snapshot.positive_rate = values["positive_rate"]
    snapshot.negative_rate = values["negative_rate"]
    snapshot.delta_previous_period = delta
    snapshot.analyst_summary = summary
    snapshot.dominant_topic_id = dominant_topic.id if dominant_topic is not None else None
    snapshot.computed_at = utc_now()
    snapshot.details = {
        "weighted_counts": {
            "positive": values["positive_weight"],
            "neutral": values["neutral_weight"],
            "negative": values["negative_weight"],
        },
        "comparison_policy": "adjacent_non_overlapping_period",
    }
    session.flush()
    return snapshot


def mark_pipeline_as_failed(
    session: Session,
    pipeline_run_id: int,
    error: Exception,
) -> None:
    session.rollback()
    pipeline_run = session.get(PipelineRun, pipeline_run_id)
    if pipeline_run is not None:
        pipeline_run.status = "failed"
        pipeline_run.finished_at = utc_now()
        pipeline_run.error_message = str(error)
        session.commit()


def compute_reputation_snapshots(
    period_type: str = "weekly",
    period_end: date | None = None,
    include_previous_period: bool = True,
) -> None:
    """Calcule le score courant et sa période précédente adjacente.

    La période précédente est créée dans le même run lorsqu'elle manque. Ainsi,
    le delta affiché ne compare jamais deux fenêtres qui partagent des jours.
    """

    session = SessionLocal()
    pipeline_run_id: int | None = None
    try:
        period_start, resolved_period_end = get_period_bounds(period_type, period_end)
        previous_start, previous_end = get_previous_period_bounds(period_type, period_start)

        print(
            f"Calcul du score ({period_type}) : {period_start} -> {resolved_period_end}; "
            f"comparaison : {previous_start} -> {previous_end}"
        )
        pipeline_run = PipelineRun(
            run_type="reputation_scoring",
            source_id=None,
            watch_query_id=None,
            status="running",
            started_at=utc_now(),
            statistics={
                "period_type": period_type,
                "period_start": str(period_start),
                "period_end": str(resolved_period_end),
                "previous_period_start": str(previous_start),
                "previous_period_end": str(previous_end),
                "formula_version": FORMULA_VERSION,
                "comparison_policy": "adjacent_non_overlapping_period",
            },
        )
        session.add(pipeline_run)
        session.commit()
        session.refresh(pipeline_run)
        pipeline_run_id = pipeline_run.id

        organizations = list(
            session.scalars(select(Organization).where(Organization.is_active.is_(True)))
        )
        created_or_updated = 0

        for organization in organizations:
            previous_snapshot = get_existing_snapshot(
                session,
                organization.id,
                previous_start,
                previous_end,
            )
            if include_previous_period:
                # Pour le snapshot précédent, on cherche une période encore plus
                # ancienne uniquement si elle existe déjà ; elle n'est pas requise
                # pour produire le delta courant.
                older_start, older_end = get_previous_period_bounds(
                    period_type, previous_start
                )
                older_snapshot = get_existing_snapshot(
                    session, organization.id, older_start, older_end
                )
                previous_snapshot = upsert_snapshot(
                    session,
                    organization=organization,
                    pipeline_run_id=pipeline_run.id,
                    period_type=period_type,
                    period_start=previous_start,
                    period_end=previous_end,
                    previous_snapshot=older_snapshot,
                )
                created_or_updated += 1

            current_snapshot = upsert_snapshot(
                session,
                organization=organization,
                pipeline_run_id=pipeline_run.id,
                period_type=period_type,
                period_start=period_start,
                period_end=resolved_period_end,
                previous_snapshot=previous_snapshot,
            )
            created_or_updated += 1
            print(
                f"Score calculé : {organization.name} -> "
                f"{current_snapshot.reputation_score:.1f}/100 "
                f"({current_snapshot.mention_count} mentions)"
            )

        pipeline_run.status = "completed"
        pipeline_run.finished_at = utc_now()
        pipeline_run.items_received = len(organizations) * (2 if include_previous_period else 1)
        pipeline_run.items_created = created_or_updated
        pipeline_run.statistics = {
            **(pipeline_run.statistics or {}),
            "organizations": len(organizations),
            "snapshots_upserted": created_or_updated,
        }
        session.commit()

        print("\nCalcul du score terminé.")
        print(f"- Organisations traitées : {len(organizations)}")
        print(f"- Snapshots créés/mis à jour : {created_or_updated}")

    except Exception as error:
        if pipeline_run_id is not None:
            mark_pipeline_as_failed(session, pipeline_run_id, error)
        else:
            session.rollback()
        print(f"\nErreur pendant le calcul du score : {error}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    compute_reputation_snapshots()
