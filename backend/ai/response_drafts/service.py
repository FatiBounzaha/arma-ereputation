from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai.response_drafts.base import ResponseDraftProvider
from backend.ai.response_drafts.claude_provider import ClaudeResponseDraftProvider
from backend.ai.response_drafts.template_provider import TemplateResponseDraftProvider
from backend.database.connection import SessionLocal
from backend.database.models import (
    Alert,
    Mention,
    MentionOrganization,
    Organization,
    ResponseDraft,
    Source,
)

DEFAULT_PROVIDER_NAME = "template"
OWN_ORGANIZATION_NAME = "ARMA"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_provider(provider_name: str | None = None) -> ResponseDraftProvider:
    resolved_name = (
        provider_name
        or os.getenv("RESPONSE_DRAFT_PROVIDER")
        or DEFAULT_PROVIDER_NAME
    ).strip().lower()

    if resolved_name == "template":
        return TemplateResponseDraftProvider()
    if resolved_name == "claude":
        return ClaudeResponseDraftProvider()
    raise ValueError(
        f"Fournisseur inconnu : {resolved_name}. Valeurs : template, claude."
    )


def get_open_alerts(
    session: Session,
    limit: int | None = None,
    include_existing_drafts: bool = False,
) -> list[tuple[Alert, MentionOrganization, Mention, Organization, Source, ResponseDraft | None]]:
    """Retourne les alertes ARMA ouvertes et leur éventuel brouillon."""

    statement = (
        select(
            Alert,
            MentionOrganization,
            Mention,
            Organization,
            Source,
            ResponseDraft,
        )
        .join(
            MentionOrganization,
            MentionOrganization.id == Alert.mention_organization_id,
        )
        .join(Mention, Mention.id == MentionOrganization.mention_id)
        .join(Organization, Organization.id == MentionOrganization.organization_id)
        .join(Source, Source.id == Mention.source_id)
        .outerjoin(ResponseDraft, ResponseDraft.alert_id == Alert.id)
        .where(
            Alert.status == "open",
            Organization.name == OWN_ORGANIZATION_NAME,
        )
        .order_by(Alert.id)
    )

    if not include_existing_drafts:
        statement = statement.where(ResponseDraft.id.is_(None))

    if limit is not None:
        statement = statement.limit(limit)

    return list(session.execute(statement).all())


def build_context(
    session: Session,
    alert: Alert,
    mention: Mention,
    source: Source,
) -> dict:
    parent = session.get(Mention, mention.parent_mention_id) if mention.parent_mention_id else None
    payload = mention.raw_payload or {}
    comment_triage = payload.get("_comment_triage") if isinstance(payload, dict) else None
    return {
        "alert_reason": alert.reason,
        "mention_text": mention.clean_text or mention.raw_text,
        "severity": alert.severity,
        "content_type": mention.content_type,
        "source_type": source.source_type,
        "source_name": source.name,
        "title": mention.title,
        "author_name": mention.author_name,
        "mention_url": mention.url,
        "parent_title": parent.title if parent else None,
        "parent_url": parent.url if parent else None,
        "parent_excerpt": ((parent.clean_text or parent.raw_text or "")[:1200] if parent else None),
        "comment_triage": comment_triage if isinstance(comment_triage, dict) else None,
        "city": mention.city,
        "country": mention.country,
        "business_category": mention.business_category,
        "business_relevance_score": mention.business_relevance_score,
        "quality_flags": mention.quality_flags or [],
        "engagement": mention.engagement or {},
        "detected_language": mention.detected_language,
    }


def generate_response_drafts_for_open_alerts(
    provider_name: str | None = None,
    limit: int | None = None,
    replace_existing: bool = False,
) -> None:
    """
    Décide de l'action adaptée puis génère un texte bilingue si utile.

    replace_existing=True régénère uniquement les brouillons encore au statut
    "draft". Les contenus déjà validés ou envoyés ne sont jamais écrasés.
    """

    session = SessionLocal()
    try:
        provider = get_provider(provider_name)
        resolved_provider_name = (
            provider_name
            or os.getenv("RESPONSE_DRAFT_PROVIDER")
            or DEFAULT_PROVIDER_NAME
        )
        print(
            "Génération contextuelle des décisions/réponses avec : "
            f"{resolved_provider_name}"
        )

        candidates = get_open_alerts(
            session=session,
            limit=limit,
            include_existing_drafts=replace_existing,
        )
        if not candidates:
            print("Aucune alerte ouverte à traiter.")
            return

        created = 0
        updated = 0
        skipped = 0
        failed = 0

        for alert, mention_organization, mention, organization, source, existing in candidates:
            try:
                if existing is not None and existing.status not in {"draft", "generated"}:
                    skipped += 1
                    print(
                        f"Brouillon conservé : alert_id={alert.id}, statut={existing.status}"
                    )
                    continue

                context = build_context(session, alert, mention, source)
                result = provider.draft(
                    organization_name=organization.name,
                    alert_reason=alert.reason,
                    mention_text=mention.clean_text or mention.raw_text,
                    severity=alert.severity,
                    context=context,
                )

                if existing is None:
                    draft = ResponseDraft(alert_id=alert.id)
                    session.add(draft)
                    created += 1
                else:
                    draft = existing
                    updated += 1

                draft.content_by_language = result.content_by_language
                draft.tone = result.tone
                draft.status = "draft"
                draft.model_provider = result.model_provider
                draft.model_name = result.model_name
                draft.model_version = result.model_version
                draft.generated_at = utc_now()
                draft.extra_data = result.details

                # La décision est aussi copiée dans l'alerte pour faciliter
                # le filtrage et l'audit, sans nouvelle migration SQL.
                alert.extra_data = {
                    **(alert.extra_data or {}),
                    "recommended_action": result.details.get("action"),
                    "reply_eligible": result.details.get("reply_eligible"),
                    "requires_human_validation": result.details.get(
                        "requires_human_validation", True
                    ),
                    "decision_category": result.details.get("category"),
                }

                session.commit()
                print(
                    f"Décision créée : alert_id={alert.id} -> "
                    f"{result.details.get('action', 'unknown')}"
                )
            except Exception as item_error:
                session.rollback()
                failed += 1
                print(f"Alerte ignorée : alert_id={alert.id} -> {item_error}")

        print("\nTraitement des réponses terminé.")
        print(f"- Créés : {created}")
        print(f"- Mis à jour : {updated}")
        print(f"- Conservés : {skipped}")
        print(f"- Échecs : {failed}")
        if failed:
            raise RuntimeError(
                f"Génération des réponses incomplète : {failed} échec(s)."
            )
    finally:
        session.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Génère des décisions et brouillons contextuels pour les alertes ARMA."
    )
    parser.add_argument("--provider", choices=["template", "claude"], default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Régénère les brouillons encore au statut draft.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    generate_response_drafts_for_open_alerts(
        provider_name=args.provider,
        limit=args.limit,
        replace_existing=args.replace_existing,
    )
