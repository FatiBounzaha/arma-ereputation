from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai.sentiment.base import SentimentProvider
from backend.ai.sentiment.claude_provider import ClaudeSentimentProvider
from backend.ai.sentiment.huggingface_provider import (
    HuggingFaceSentimentProvider,
)
from backend.database.connection import SessionLocal
from backend.database.models import (
    Mention,
    MentionAnalysis,
    MentionOrganization,
    PipelineRun,
)

# Fournisseur utilisé par défaut si SENTIMENT_PROVIDER n'est pas
# défini dans le .env. Reste "huggingface" tant que le projet ne
# dispose pas d'une clé ANTHROPIC_API_KEY valide.
DEFAULT_PROVIDER_NAME = "huggingface"


def utc_now() -> datetime:
    """Retourne la date et l'heure actuelles en UTC."""

    return datetime.now(timezone.utc)


def get_provider(provider_name: str | None = None) -> SentimentProvider:
    """
    Construit le fournisseur de sentiment demandé.

    L'appelant peut choisir explicitement le fournisseur
    (provider_name="huggingface" ou "claude"), sinon la variable
    d'environnement SENTIMENT_PROVIDER est utilisée, sinon
    DEFAULT_PROVIDER_NAME.
    """

    resolved_name = (
        provider_name
        or os.getenv("SENTIMENT_PROVIDER")
        or DEFAULT_PROVIDER_NAME
    ).strip().lower()

    if resolved_name == "huggingface":
        return HuggingFaceSentimentProvider()

    if resolved_name == "claude":
        return ClaudeSentimentProvider()

    raise ValueError(
        f"Fournisseur de sentiment inconnu : '{resolved_name}'. "
        "Valeurs acceptées : 'huggingface', 'claude'."
    )


def get_pending_mention_organizations(
    session: Session,
    limit: int | None = None,
) -> list[MentionOrganization]:
    """
    Retourne les couples (mention, organisation) qui n'ont pas
    encore d'analyse de sentiment courante.
    """

    already_analyzed = select(
        MentionAnalysis.mention_organization_id
    ).where(MentionAnalysis.is_current.is_(True))

    statement = (
        select(MentionOrganization)
        .where(
            MentionOrganization.id.notin_(already_analyzed),
            MentionOrganization.include_in_reputation.is_(True),
        )
        .order_by(MentionOrganization.id)
    )

    if limit is not None:
        statement = statement.limit(limit)

    return list(session.scalars(statement))


def mark_previous_analyses_as_outdated(
    session: Session,
    mention_organization_id: int,
) -> None:
    """
    Marque les analyses précédentes comme non courantes avant
    d'en enregistrer une nouvelle (cas d'une réanalyse).
    """

    previous_analyses = session.scalars(
        select(MentionAnalysis).where(
            MentionAnalysis.mention_organization_id
            == mention_organization_id,
            MentionAnalysis.is_current.is_(True),
        )
    )

    for previous_analysis in previous_analyses:
        previous_analysis.is_current = False


def mark_pipeline_as_failed(
    session: Session,
    pipeline_run_id: int,
    error: Exception,
) -> None:
    """Enregistre l'échec d'une exécution du pipeline."""

    session.rollback()

    pipeline_run = session.get(PipelineRun, pipeline_run_id)

    if pipeline_run is None:
        return

    pipeline_run.status = "failed"
    pipeline_run.finished_at = utc_now()
    pipeline_run.error_message = str(error)

    session.commit()


def analyze_pending_mentions(
    provider_name: str | None = None,
    limit: int | None = None,
) -> None:
    """
    Analyse le sentiment de toutes les mentions en attente et
    enregistre les résultats dans mention_analyses.
    """

    session = SessionLocal()
    pipeline_run_id: int | None = None

    try:
        provider = get_provider(provider_name)

        resolved_provider_name = (
            provider_name
            or os.getenv("SENTIMENT_PROVIDER")
            or DEFAULT_PROVIDER_NAME
        )

        print(
            "Début de l'analyse de sentiment avec le fournisseur : "
            f"{resolved_provider_name}"
        )

        pipeline_run = PipelineRun(
            run_type="sentiment_analysis",
            source_id=None,
            watch_query_id=None,
            status="running",
            started_at=utc_now(),
            statistics={"provider": resolved_provider_name},
        )

        session.add(pipeline_run)
        session.commit()
        session.refresh(pipeline_run)

        pipeline_run_id = pipeline_run.id

        pending_mention_organizations = get_pending_mention_organizations(
            session=session,
            limit=limit,
        )

        items_received = len(pending_mention_organizations)
        items_created = 0
        items_ignored = 0
        items_failed = 0

        print(f"Mentions à analyser : {items_received}")

        for mention_organization in pending_mention_organizations:
            # Chaque mention est traitée dans sa propre mini-transaction
            # (commit immédiat) : un appel de fournisseur qui échoue
            # (JSON invalide, modèle indisponible, texte imprévu, ...)
            # ne doit pas faire perdre les analyses déjà réussies de
            # ce run.
            try:
                mention = session.get(
                    Mention,
                    mention_organization.mention_id,
                )

                if mention is None:
                    items_ignored += 1
                    continue

                text_to_analyze = mention.clean_text or mention.raw_text

                if not text_to_analyze or not text_to_analyze.strip():
                    items_ignored += 1
                    continue

                result = provider.analyze(
                    text=text_to_analyze,
                    language_hint=mention.detected_language,
                )

                mark_previous_analyses_as_outdated(
                    session=session,
                    mention_organization_id=mention_organization.id,
                )

                analysis = MentionAnalysis(
                    mention_organization_id=mention_organization.id,
                    model_provider=result.model_provider,
                    model_name=result.model_name,
                    model_version=result.model_version,
                    sentiment_label=result.sentiment_label,
                    positive_score=result.positive_score,
                    neutral_score=result.neutral_score,
                    negative_score=result.negative_score,
                    confidence=result.confidence,
                    explanation=result.explanation,
                    analysis_language=result.analysis_language,
                    is_current=True,
                    analyzed_at=utc_now(),
                    details=result.details,
                )

                session.add(analysis)
                session.commit()

                items_created += 1

                print(
                    "Analyse créée : mention_organization="
                    f"{mention_organization.id} -> {result.sentiment_label}"
                )

            except Exception as item_error:
                session.rollback()
                items_failed += 1

                print(
                    "Analyse ignorée (erreur) : mention_organization="
                    f"{mention_organization.id} -> {item_error}"
                )

        current_pipeline_run = session.get(PipelineRun, pipeline_run_id)

        if current_pipeline_run is None:
            raise RuntimeError(
                "Impossible de retrouver le pipeline créé."
            )

        current_pipeline_run.status = "completed"
        current_pipeline_run.finished_at = utc_now()
        current_pipeline_run.items_received = items_received
        current_pipeline_run.items_created = items_created
        current_pipeline_run.items_duplicated = 0
        current_pipeline_run.statistics = {
            "provider": resolved_provider_name,
            "items_received": items_received,
            "items_created": items_created,
            "items_ignored": items_ignored,
            "items_failed": items_failed,
        }

        session.commit()

        print("\nAnalyse de sentiment terminée.")
        print(f"- Mentions traitées : {items_received}")
        print(f"- Analyses créées : {items_created}")
        print(f"- Ignorées (texte vide ou mention absente) : {items_ignored}")
        print(f"- Échouées (erreur du fournisseur) : {items_failed}")
        if items_failed:
            raise RuntimeError(
                f"Analyse de sentiment incomplète : {items_failed} échec(s)."
            )

    except Exception as error:
        if pipeline_run_id is not None:
            mark_pipeline_as_failed(
                session=session,
                pipeline_run_id=pipeline_run_id,
                error=error,
            )
        else:
            session.rollback()

        print(f"\nErreur pendant l'analyse de sentiment : {error}")

        raise

    finally:
        session.close()


if __name__ == "__main__":
    analyze_pending_mentions()
