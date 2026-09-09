from __future__ import annotations

import math
import os
from datetime import date, datetime, timezone
from collections import defaultdict
from itertools import cycle

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai.content.base import PostContentProvider
from backend.ai.content.claude_provider import ClaudePostProvider
from backend.ai.content.template_provider import TemplatePostProvider
from backend.database.connection import SessionLocal
from backend.database.models import (
    GeneratedPost,
    Mention,
    Organization,
    PipelineRun,
    PostEvidenceMention,
    StrategicAngle,
)

# Fournisseur utilisé par défaut : gabarits fixes, sans clé API.
# Passer à "claude" une fois ANTHROPIC_API_KEY renseignée pour un
# contenu réellement publiable et correctement bilingue.
from backend.scoring.formulas import get_period_bounds

DEFAULT_PROVIDER_NAME = "template"

DEFAULT_PLATFORMS = ["linkedin", "instagram", "facebook", "x"]

# Nombre de posts visés par exécution, comme dans le POC
# Marketing Contenu ("8 posts bilingues prêts à publier").
DEFAULT_TARGET_POST_COUNT = 8


def utc_now() -> datetime:
    """Retourne la date et l'heure actuelles en UTC."""

    return datetime.now(timezone.utc)


def get_provider(provider_name: str | None = None) -> PostContentProvider:
    """
    Construit le générateur de posts demandé.

    L'appelant peut choisir explicitement le fournisseur
    (provider_name="template" ou "claude"), sinon la variable
    d'environnement POST_CONTENT_PROVIDER est utilisée, sinon
    DEFAULT_PROVIDER_NAME.
    """

    resolved_name = (
        provider_name
        or os.getenv("POST_CONTENT_PROVIDER")
        or DEFAULT_PROVIDER_NAME
    ).strip().lower()

    if resolved_name == "template":
        return TemplatePostProvider()

    if resolved_name == "claude":
        return ClaudePostProvider()

    raise ValueError(
        f"Fournisseur de posts inconnu : '{resolved_name}'. "
        "Valeurs acceptées : 'template', 'claude'."
    )


def get_angles_needing_posts(
    session: Session,
    limit: int | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> list[StrategicAngle]:
    """Retourne les angles proposés de LA période demandée seulement.

    Cela empêche un run sans veille Marketing de réutiliser par erreur les
    angles d'une ancienne semaine et de générer des brouillons hors période.
    """

    candidates = list(
        session.scalars(
            select(StrategicAngle)
            .where(StrategicAngle.status == "proposed")
            .order_by(StrategicAngle.generated_at.desc())
            .limit(200)
        )
    )

    if period_start is not None and period_end is not None:
        expected_start = str(period_start)
        expected_end = str(period_end)
        candidates = [
            angle for angle in candidates
            if str((angle.extra_data or {}).get("period_start") or "") == expected_start
            and str((angle.extra_data or {}).get("period_end") or "") == expected_end
        ]

    if not candidates:
        return []

    latest_run_id = candidates[0].pipeline_run_id
    angles = [angle for angle in candidates if angle.pipeline_run_id == latest_run_id]
    angles.sort(key=lambda item: item.priority_score or 0.0, reverse=True)
    return angles[:limit] if limit is not None else angles


def build_angle_platform_pairs(
    angles: list[StrategicAngle],
    target_post_count: int,
    platforms: list[str],
) -> list[tuple[StrategicAngle, str]]:
    """
    Répartit les plateformes entre les angles pour atteindre le
    nombre de posts visé, en alternant les plateformes comme dans
    le POC (chaque post successif change de plateforme).
    """

    if not angles:
        return []

    posts_per_angle = math.ceil(target_post_count / len(angles))
    platform_cycle = cycle(platforms)

    pairs = [
        (angle, next(platform_cycle))
        for angle in angles
        for _ in range(posts_per_angle)
    ]

    return pairs[:target_post_count]


def get_evidence_snippets(
    session: Session,
    angle: StrategicAngle,
) -> list[str]:
    """Récupère les textes des mentions citées comme preuves de l'angle."""

    mention_ids = (angle.extra_data or {}).get("mention_ids", [])

    if not mention_ids:
        return []

    mentions = session.scalars(
        select(Mention).where(Mention.id.in_(mention_ids))
    )

    snippets: list[str] = []
    for mention in mentions:
        title = (mention.title or "Sans titre").strip()
        summary = (
            mention.business_summary
            or mention.clean_text
            or mention.raw_text
            or ""
        ).strip()
        published = mention.manual_published_at or mention.published_at
        date_text = published.date().isoformat() if published is not None else "date inconnue"
        snippet = f"{date_text} — {title}"
        if summary and summary.casefold() not in title.casefold():
            snippet += f" — {summary[:280]}"
        if mention.url:
            snippet += f" — source: {mention.url}"
        snippets.append(snippet)
    return snippets


def generate_posts_for_proposed_angles(
    provider_name: str | None = None,
    target_post_count: int = DEFAULT_TARGET_POST_COUNT,
    platforms: list[str] | None = None,
    angle_limit: int | None = None,
    period_type: str = "weekly",
    period_end: date | None = None,
) -> None:
    """
    Génère des posts bilingues (FR + AR) pour les angles
    stratégiques encore proposés (agent "Rédacteur FR+AR" du POC
    Marketing Contenu).
    """

    session = SessionLocal()
    pipeline_run_id: int | None = None

    try:
        provider = get_provider(provider_name)
        resolved_platforms = platforms or DEFAULT_PLATFORMS
        resolved_target_post_count = target_post_count
        if target_post_count == DEFAULT_TARGET_POST_COUNT:
            try:
                resolved_target_post_count = max(1, min(int(os.getenv("POST_TARGET_COUNT", "8")), 20))
            except ValueError:
                resolved_target_post_count = DEFAULT_TARGET_POST_COUNT

        resolved_provider_name = (
            provider_name
            or os.getenv("POST_CONTENT_PROVIDER")
            or DEFAULT_PROVIDER_NAME
        )
        fallback_name = (os.getenv("POST_FALLBACK_PROVIDER") or "template").strip().lower()
        fallback_provider = None
        if fallback_name and fallback_name != resolved_provider_name.strip().lower():
            fallback_provider = get_provider(fallback_name)

        print(
            "Génération des posts avec le fournisseur : "
            f"{resolved_provider_name}"
        )

        target_period_start, target_period_end = get_period_bounds(period_type, period_end)
        angles = get_angles_needing_posts(
            session=session,
            limit=angle_limit,
            period_start=target_period_start,
            period_end=target_period_end,
        )

        if not angles:
            print(
                "Aucun angle stratégique pour la période "
                f"{target_period_start} -> {target_period_end} : aucun brouillon ne sera généré."
            )
            return

        pairs = build_angle_platform_pairs(
            angles=angles,
            target_post_count=resolved_target_post_count,
            platforms=resolved_platforms,
        )

        pipeline_run = PipelineRun(
            run_type="post_generation",
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

        items_created = 0
        items_skipped = 0
        items_failed = 0
        variant_counts: dict[tuple[int, str], int] = defaultdict(int)

        for display_order, (angle, platform) in enumerate(pairs, start=1):
            variant_key = (angle.id, platform)
            variant_counts[variant_key] += 1
            variant_number = variant_counts[variant_key]

            # Commit individuel par post : un échec isolé (JSON
            # invalide, fournisseur indisponible, ...) ne doit pas
            # faire perdre les posts déjà réussis du run.
            try:
                organization = session.get(
                    Organization, angle.organization_id
                )

                evidence_snippets = get_evidence_snippets(
                    session=session,
                    angle=angle,
                )

                variant_instruction = (
                    ""
                    if variant_number == 1
                    else (
                        f" Variante éditoriale n°{variant_number} : utiliser une accroche, "
                        "une structure et des formulations différentes des autres brouillons "
                        "du même angle, sans inventer de faits."
                    )
                )
                angle_description = f"{angle.description}{variant_instruction}"

                used_fallback = False
                try:
                    result = provider.write_post(
                        organization_name=organization.name,
                        platform=platform,
                        angle_title=angle.title,
                        angle_description=angle_description,
                        evidence_snippets=evidence_snippets,
                    )
                except Exception as primary_error:
                    if fallback_provider is None:
                        raise
                    print(
                        f"Claude indisponible/JSON invalide pour {platform}; "
                        f"secours {fallback_name} activé : {primary_error}"
                    )
                    result = fallback_provider.write_post(
                        organization_name=organization.name,
                        platform=platform,
                        angle_title=angle.title,
                        angle_description=angle_description,
                        evidence_snippets=evidence_snippets,
                    )
                    result.details = {
                        **(result.details or {}),
                        "fallback_used": True,
                        "primary_provider": resolved_provider_name,
                        "primary_error": str(primary_error)[:500],
                    }
                    used_fallback = True

                post = GeneratedPost(
                    organization_id=angle.organization_id,
                    strategic_angle_id=angle.id,
                    pipeline_run_id=pipeline_run.id,
                    display_order=display_order,
                    platform=platform,
                    content_by_language=result.content_by_language,
                    image_prompt=result.image_prompt,
                    tone=result.tone,
                    status="draft",
                    model_provider=result.model_provider,
                    model_name=result.model_name,
                    model_version=result.model_version,
                    generated_at=utc_now(),
                    extra_data={
                        **(result.details or {}),
                        "variant_number": variant_number,
                        "target_post_count": resolved_target_post_count,
                    },
                )

                session.add(post)
                session.flush()

                mention_ids = (angle.extra_data or {}).get("mention_ids", [])

                for mention_id in mention_ids:
                    session.add(
                        PostEvidenceMention(
                            generated_post_id=post.id,
                            mention_id=mention_id,
                        )
                    )

                session.commit()

                items_created += 1

                print(
                    f"Post {display_order}/{len(pairs)} créé : "
                    f"{platform} — {angle.title}"
                )

            except Exception as item_error:
                session.rollback()
                items_failed += 1

                print(
                    f"Post ignoré (erreur) : angle={angle.id}, "
                    f"plateforme={platform} -> {item_error}"
                )

        current_pipeline_run = session.get(PipelineRun, pipeline_run_id)

        if current_pipeline_run is not None:
            current_pipeline_run.status = "completed"
            current_pipeline_run.finished_at = utc_now()
            current_pipeline_run.items_received = len(pairs)
            current_pipeline_run.items_created = items_created
            current_pipeline_run.items_duplicated = items_skipped
            current_pipeline_run.statistics = {
                **(current_pipeline_run.statistics or {}),
                "target_post_count": resolved_target_post_count,
                "created": items_created,
                "failed": items_failed,
                "platforms": resolved_platforms,
            }
            session.commit()

        print("\nGénération des posts terminée.")
        print(f"- Posts créés : {items_created}")
        print(f"- Déjà existants (ignorés) : {items_skipped}")
        print(f"- Échoués : {items_failed}")

        if items_created < len(pairs):
            raise RuntimeError(
                f"Génération incomplète : {items_created}/{len(pairs)} posts créés."
            )

    except Exception as error:
        session.rollback()

        if pipeline_run_id is not None:
            pipeline_run = session.get(PipelineRun, pipeline_run_id)

            if pipeline_run is not None:
                pipeline_run.status = "failed"
                pipeline_run.finished_at = utc_now()
                pipeline_run.error_message = str(error)
                session.commit()

        print(f"\nErreur pendant la génération des posts : {error}")

        raise

    finally:
        session.close()


if __name__ == "__main__":
    generate_posts_for_proposed_angles()
