from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from backend.database.connection import SessionLocal
from backend.database.models import Organization, ReputationSnapshot, Topic
from backend.scoring.formulas import FORMULA_VERSION, get_period_bounds
from backend.processing.mention_governance import confidence_level


def get_benchmark(
    period_type: str = "weekly",
    period_end: date | None = None,
    formula_version: str = FORMULA_VERSION,
) -> list[dict]:
    """
    Retourne le classement des organisations pour une période
    donnée : score de réputation, volume de mentions et taux de
    sentiment (positif/négatif). Trié du meilleur au moins bon
    score, comme le benchmark concurrents attendu par le POC
    Réputation Sociale.

    Si period_end n'est pas fourni, la dernière période déjà
    calculée pour ce period_type est utilisée automatiquement.
    """

    session = SessionLocal()

    try:
        resolved_period_end = period_end

        if resolved_period_end is None:
            if period_type == "weekly":
                # Le benchmark par défaut suit exactement la période métier T-1
                # (dernière semaine civile complète), pas un ancien snapshot
                # glissant ni la semaine en cours.
                _, resolved_period_end = get_period_bounds("weekly")
            else:
                resolved_period_end = session.scalar(
                    select(func.max(ReputationSnapshot.period_end)).where(
                        ReputationSnapshot.period_type == period_type,
                        ReputationSnapshot.formula_version == formula_version,
                    )
                )

        if resolved_period_end is None:
            return []

        rows = session.execute(
            select(
                ReputationSnapshot,
                Organization.name,
                Organization.organization_type,
                Topic.name,
            )
            .join(
                Organization,
                Organization.id == ReputationSnapshot.organization_id,
            )
            .outerjoin(
                Topic,
                Topic.id == ReputationSnapshot.dominant_topic_id,
            )
            .where(
                ReputationSnapshot.period_type == period_type,
                ReputationSnapshot.period_end == resolved_period_end,
                ReputationSnapshot.formula_version == formula_version,
            )
            .order_by(ReputationSnapshot.reputation_score.desc())
        ).all()

        entries = []
        for snapshot, organization_name, organization_type, dominant_topic_name in rows:
            has_data = snapshot.mention_count > 0
            entries.append(
                {
                    "organization_id": snapshot.organization_id,
                    "organization_name": organization_name,
                    "organization_type": organization_type,
                    "period_start": snapshot.period_start,
                    "period_end": snapshot.period_end,
                    # 50 est la valeur neutre interne quand il n'existe aucune
                    # donnée. Le portail affiche alors « données insuffisantes »
                    # au lieu de présenter 50 comme une vraie performance.
                    "reputation_score": snapshot.reputation_score if has_data else None,
                    "mention_count": snapshot.mention_count,
                    "has_data": has_data,
                    "positive_rate": snapshot.positive_rate if has_data else None,
                    "negative_rate": snapshot.negative_rate if has_data else None,
                    "delta_previous_period": snapshot.delta_previous_period if has_data else None,
                    "dominant_topic": dominant_topic_name if has_data else None,
                    "confidence": confidence_level(snapshot.mention_count),
                }
            )
        entries.sort(
            key=lambda item: (
                item["has_data"],
                item["reputation_score"] if item["reputation_score"] is not None else -1,
            ),
            reverse=True,
        )
        return entries

    finally:
        session.close()


def get_reputation_history(
    organization_id: int,
    period_type: str = "weekly",
    limit: int = 12,
    formula_version: str = FORMULA_VERSION,
) -> list[dict]:
    """
    Retourne l'historique du score de réputation d'une
    organisation, du plus ancien au plus récent (pratique pour
    tracer une courbe sur le portail).

    C'est ce qui permet d'agréger le score dans le temps, au-delà
    de la simple comparaison d'une période isolée que fournit
    get_benchmark().
    """

    session = SessionLocal()

    try:
        candidates = list(
            session.scalars(
                select(ReputationSnapshot)
                .where(
                    ReputationSnapshot.organization_id == organization_id,
                    ReputationSnapshot.period_type == period_type,
                    ReputationSnapshot.formula_version == formula_version,
                )
                .order_by(ReputationSnapshot.period_end.desc())
                .limit(max(limit * 8, 40))
            )
        )

        # Pour le reporting weekly, l'historique ne doit contenir que des
        # semaines civiles complètes lundi -> dimanche, et jamais la semaine
        # courante encore incomplète.
        latest_complete_end = get_period_bounds("weekly")[1] if period_type == "weekly" else None

        selected: list[ReputationSnapshot] = []
        next_latest_start = None
        for snapshot in candidates:
            if period_type == "weekly":
                is_calendar_week = (
                    snapshot.period_start.weekday() == 0
                    and snapshot.period_end.weekday() == 6
                    and (snapshot.period_end - snapshot.period_start).days == 6
                )
                if not is_calendar_week:
                    continue
                if latest_complete_end is not None and snapshot.period_end > latest_complete_end:
                    continue
            if next_latest_start is None or snapshot.period_end < next_latest_start:
                selected.append(snapshot)
                next_latest_start = snapshot.period_start
            if len(selected) >= max(1, limit):
                break

        history = [
            {
                "period_start": snapshot.period_start,
                "period_end": snapshot.period_end,
                "reputation_score": snapshot.reputation_score,
                "mention_count": snapshot.mention_count,
                "positive_rate": snapshot.positive_rate,
                "negative_rate": snapshot.negative_rate,
                "delta_previous_period": snapshot.delta_previous_period,
            }
            for snapshot in reversed(selected)
        ]
        return history

    finally:
        session.close()


def print_benchmark(period_type: str = "weekly") -> None:
    """Affiche le benchmark en console, pour un test rapide."""

    benchmark = get_benchmark(period_type=period_type)

    if not benchmark:
        print("Aucun score de réputation calculé pour l'instant.")
        return

    print(f"BENCHMARK CONCURRENTS ({period_type})")
    print("=" * 72)

    for rank, entry in enumerate(benchmark, start=1):
        score_text = (
            f"{entry['reputation_score']:.1f}/100"
            if entry["reputation_score"] is not None
            else "données insuffisantes"
        )
        print(
            f"{rank}. {entry['organization_name']} "
            f"({entry['organization_type']}) : "
            f"{score_text}, {entry['mention_count']} mention(s)"
        )


def print_reputation_history(
    organization_id: int,
    period_type: str = "weekly",
) -> None:
    """Affiche l'historique d'une organisation en console."""

    history = get_reputation_history(
        organization_id=organization_id,
        period_type=period_type,
    )

    if not history:
        print("Aucun historique disponible pour cette organisation.")
        return

    print(f"HISTORIQUE DU SCORE (organization_id={organization_id})")
    print("=" * 72)

    for entry in history:
        delta = entry["delta_previous_period"]
        delta_text = f" ({delta:+.1f})" if delta is not None else ""

        print(
            f"{entry['period_start']} -> {entry['period_end']} : "
            f"{entry['reputation_score']:.1f}/100{delta_text}, "
            f"{entry['mention_count']} mention(s)"
        )


if __name__ == "__main__":
    print_benchmark()
