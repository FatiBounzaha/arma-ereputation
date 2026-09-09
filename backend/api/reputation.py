from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import get_db_session
from backend.api.schemas import (
    BenchmarkEntry,
    PeriodOption,
    ReputationHistoryEntry,
    ReputationScoreResponse,
)
from backend.database.models import Organization, ReputationSnapshot, Topic
from backend.scoring.benchmark import get_benchmark, get_reputation_history
from backend.scoring.formulas import FORMULA_VERSION
from backend.scoring.periods import list_available_periods
from backend.processing.mention_governance import confidence_level

router = APIRouter(prefix="/api/reputation", tags=["reputation"])


def get_organization_by_name(session: Session, name: str) -> Organization:
    """Récupère une organisation par son nom, ou lève un 404 explicite."""

    organization = session.scalar(
        select(Organization).where(Organization.name == name)
    )

    if organization is None:
        raise HTTPException(
            status_code=404,
            detail=f"Organisation inconnue : {name}",
        )

    return organization


@router.get("/benchmark", response_model=list[BenchmarkEntry])
def read_benchmark(
    period_type: str = "weekly",
    period_end: date | None = None,
) -> list[dict]:
    """
    Classement des organisations (score, volume, sentiment) pour
    une période — alimente la section 4 du POC Réputation Sociale.
    """

    return get_benchmark(period_type=period_type, period_end=period_end)


@router.get("/history", response_model=list[ReputationHistoryEntry])
def read_reputation_history(
    organization: str,
    period_type: str = "weekly",
    limit: int = 12,
    session: Session = Depends(get_db_session),
) -> list[dict]:
    """Historique chronologique du score d'une organisation."""

    organization_row = get_organization_by_name(session, organization)

    return get_reputation_history(
        organization_id=organization_row.id,
        period_type=period_type,
        limit=limit,
    )


@router.get("/periods", response_model=list[PeriodOption])
def read_available_periods(
    organization: str,
    period_type: str = "weekly",
    limit: int = 26,
    session: Session = Depends(get_db_session),
) -> list[dict]:
    """
    Périodes consultables pour une organisation, de la plus récente à la
    plus ancienne.

    Le workflow hebdomadaire ne remplace pas les semaines précédentes : il
    ajoute une semaine. Cet endpoint permet au portail de proposer un
    sélecteur pour revenir sur la semaine x-1, x-2, etc. au lieu de n'afficher
    que la dernière semaine calculée.
    """

    organization_row = get_organization_by_name(session, organization)

    try:
        return list_available_periods(
            session=session,
            organization_id=organization_row.id,
            period_type=period_type,
            limit=max(1, min(limit, 104)),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/score", response_model=ReputationScoreResponse)
def read_latest_score(
    organization: str,
    period_type: str = "weekly",
    period_start: date | None = None,
    period_end: date | None = None,
    session: Session = Depends(get_db_session),
) -> dict:
    """
    Score de réputation d'une organisation — alimente la section 1
    (jauge + statistiques) du POC Réputation Sociale.

    Sans `period_end`, la dernière période calculée est retournée.
    Avec `period_start`/`period_end`, c'est la période demandée qui est
    retournée : c'est ce qui permet de consulter une semaine antérieure.
    """

    organization_row = get_organization_by_name(session, organization)

    if period_start is not None and period_end is not None and period_end < period_start:
        raise HTTPException(422, "period_end doit être >= period_start.")

    statement = select(ReputationSnapshot).where(
        ReputationSnapshot.organization_id == organization_row.id,
        ReputationSnapshot.period_type == period_type,
        ReputationSnapshot.formula_version == FORMULA_VERSION,
    )
    if period_end is not None:
        statement = statement.where(ReputationSnapshot.period_end == period_end)
    if period_start is not None:
        statement = statement.where(ReputationSnapshot.period_start == period_start)

    snapshot = session.scalar(
        statement.order_by(ReputationSnapshot.period_end.desc()).limit(1)
    )

    if snapshot is None:
        if period_end is not None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Aucun score calculé pour '{organization}' sur la période "
                    f"{period_start or '?'} → {period_end}. Les contenus publiés "
                    "sur cette période restent consultables dans les alertes."
                ),
            )
        raise HTTPException(
            status_code=404,
            detail=(
                f"Aucun score calculé pour '{organization}' ({period_type}). "
                "Exécutez le workflow quotidien n8n."
            ),
        )

    dominant_topic_name = None

    if snapshot.dominant_topic_id is not None:
        dominant_topic = session.get(Topic, snapshot.dominant_topic_id)
        dominant_topic_name = (
            dominant_topic.name if dominant_topic is not None else None
        )

    return {
        "organization_id": organization_row.id,
        "organization_name": organization_row.name,
        "period_start": snapshot.period_start,
        "period_end": snapshot.period_end,
        "period_type": snapshot.period_type,
        "reputation_score": snapshot.reputation_score,
        "mention_count": snapshot.mention_count,
        "positive_count": snapshot.positive_count,
        "neutral_count": snapshot.neutral_count,
        "negative_count": snapshot.negative_count,
        "positive_rate": snapshot.positive_rate,
        "negative_rate": snapshot.negative_rate,
        "delta_previous_period": snapshot.delta_previous_period,
        "analyst_summary": snapshot.analyst_summary,
        "dominant_topic": dominant_topic_name,
        "confidence": confidence_level(snapshot.mention_count),
    }
