from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai.comment_triage.base import CommentTriageProvider, CommentTriageResult
from backend.ai.comment_triage.claude_provider import ClaudeCommentTriageProvider
from backend.ai.comment_triage.rules_provider import RulesCommentTriageProvider
from backend.database.connection import SessionLocal
from backend.database.models import (
    Alert,
    Mention,
    MentionAnalysis,
    MentionOrganization,
    Organization,
)

DEFAULT_PROVIDER_NAME = "rules"
OWN_ORGANIZATION_NAME = "ARMA"
TRIAGE_PAYLOAD_KEY = "_comment_triage"
TRIAGE_POLICY_VERSION = "final-actionable-comments-v4-sentiment-target-arma"
TRIAGE_FLAGS = {
    "comment_noise",
    "comment_relevant",
    "comment_actionable",
    "comment_not_actionable",
    "reputation_signal",
    "negative_alert_candidate",
    "defends_arma",
    "strong_sentiment_guardrail",
    "sentiment_guardrail_neutral",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_provider(provider_name: str | None = None) -> CommentTriageProvider:
    resolved = (
        provider_name
        or os.getenv("COMMENT_TRIAGE_PROVIDER")
        or DEFAULT_PROVIDER_NAME
    ).strip().lower()
    if resolved == "rules":
        return RulesCommentTriageProvider()
    if resolved == "claude":
        return ClaudeCommentTriageProvider()
    raise ValueError("COMMENT_TRIAGE_PROVIDER doit valoir 'rules' ou 'claude'.")


def _needs_current_policy(comment: Mention) -> bool:
    triage = (comment.raw_payload or {}).get(TRIAGE_PAYLOAD_KEY)
    if not isinstance(triage, dict):
        return True
    return triage.get("policy_version") != TRIAGE_POLICY_VERSION


def get_comments_to_triage(
    session: Session,
    *,
    replace_existing: bool,
    limit: int | None,
) -> list[Mention]:
    """Retourne tous les commentaires collectés, sans filtre d'âge.

    Les dates restent utilisées au moment du score et de l'affichage des alertes,
    mais la classification est conservée pour tous les commentaires publics afin
    de pouvoir recalculer n'importe quelle période historique.
    """

    statement = (
        select(Mention)
        .where(Mention.content_type == "social_comment")
        .order_by(Mention.id)
    )
    comments = list(session.scalars(statement))
    if not replace_existing:
        comments = [
            comment
            for comment in comments
            if comment.processing_status == "new" or _needs_current_policy(comment)
        ]
    if limit is not None:
        comments = comments[: max(0, limit)]
    return comments


def _relation_rows(session: Session, mention_id: int) -> list[tuple[MentionOrganization, Organization]]:
    return list(
        session.execute(
            select(MentionOrganization, Organization)
            .join(Organization, Organization.id == MentionOrganization.organization_id)
            .where(MentionOrganization.mention_id == mention_id)
        ).all()
    )


def _belongs_to_arma(
    session: Session,
    comment: Mention,
    parent: Mention | None,
) -> bool:
    for _, organization in _relation_rows(session, comment.id):
        if organization.name == OWN_ORGANIZATION_NAME:
            return True
    if parent is not None:
        for _, organization in _relation_rows(session, parent.id):
            if organization.name == OWN_ORGANIZATION_NAME:
                return True
    return False


def _sentiment_scores(label: str, confidence: float) -> tuple[float, float, float]:
    confidence = max(0.34, min(1.0, float(confidence or 0.5)))
    remainder = max(0.0, 1.0 - confidence)
    if label == "positive":
        return confidence, remainder * 0.7, remainder * 0.3
    if label == "negative":
        return remainder * 0.3, remainder * 0.7, confidence
    return remainder / 2, confidence, remainder / 2


def _upsert_triage_analysis(
    session: Session,
    relation: MentionOrganization,
    result: CommentTriageResult,
    *,
    should_include: bool,
) -> bool:
    """Rend le sentiment du tri directement disponible au score et aux alertes."""

    current_analyses = list(
        session.scalars(
            select(MentionAnalysis)
            .where(
                MentionAnalysis.mention_organization_id == relation.id,
                MentionAnalysis.is_current.is_(True),
            )
            .order_by(MentionAnalysis.id.desc())
        )
    )

    if not should_include:
        for analysis in current_analyses:
            analysis.is_current = False
        return bool(current_analyses)

    existing = current_analyses[0] if current_analyses else None
    existing_details = (existing.details or {}) if existing is not None else {}
    same_policy = (
        existing is not None
        and existing_details.get("source") == "comment_triage"
        and existing_details.get("policy_version") == TRIAGE_POLICY_VERSION
        and existing.sentiment_label == result.sentiment
        and existing.model_name == result.model_name
    )

    positive_score, neutral_score, negative_score = _sentiment_scores(
        result.sentiment, result.confidence
    )
    details = {
        "source": "comment_triage",
        "policy_version": TRIAGE_POLICY_VERSION,
        "category": result.category,
        "reply_recommended": result.reply_recommended,
        "quality_flags": result.quality_flags,
    }

    if same_policy and existing is not None:
        existing.positive_score = positive_score
        existing.neutral_score = neutral_score
        existing.negative_score = negative_score
        existing.confidence = result.confidence
        existing.explanation = result.reason
        existing.analysis_language = None
        existing.details = details
        existing.analyzed_at = utc_now()
        for duplicate in current_analyses[1:]:
            duplicate.is_current = False
        return False

    for analysis in current_analyses:
        analysis.is_current = False

    session.add(
        MentionAnalysis(
            mention_organization_id=relation.id,
            model_provider=result.model_provider,
            model_name=result.model_name,
            model_version=result.model_version,
            sentiment_label=result.sentiment,
            positive_score=positive_score,
            neutral_score=neutral_score,
            negative_score=negative_score,
            confidence=result.confidence,
            explanation=result.reason,
            analysis_language=None,
            is_current=True,
            analyzed_at=utc_now(),
            details=details,
        )
    )
    return True


def _close_obsolete_alerts(
    session: Session,
    relation: MentionOrganization,
    *,
    relevant: bool,
    sentiment: str,
    reply_recommended: bool,
) -> int:
    # Une plainte négative ou un commentaire actionnable (question, suggestion,
    # demande de précision) reste une alerte. Les autres signaux continuent de
    # contribuer au score sans encombrer la file de traitement.
    if relevant and (sentiment == "negative" or reply_recommended):
        return 0
    changed = 0
    alerts = session.scalars(
        select(Alert).where(
            Alert.mention_organization_id == relation.id,
            Alert.status.in_(["open", "acknowledged"]),
        )
    )
    for alert in alerts:
        alert.status = "ignored"
        alert.resolved_at = utc_now()
        alert.extra_data = {
            **(alert.extra_data or {}),
            "ignored_by_comment_triage": True,
            "triage_sentiment": sentiment,
            "triage_policy_version": TRIAGE_POLICY_VERSION,
        }
        changed += 1
    return changed


def apply_triage_to_relations(
    session: Session,
    mention: Mention,
    *,
    result: CommentTriageResult,
) -> dict[str, int]:
    rows = _relation_rows(session, mention.id)
    collection = (mention.raw_payload or {}).get("_collection") or {}
    source_allowed = bool(collection.get("include_in_reputation", True))
    counters = {"relations_changed": 0, "analyses_created": 0, "alerts_ignored": 0}

    for relation, _organization in rows:
        should_include = bool(result.relevant and source_allowed)
        if relation.include_in_reputation != should_include:
            relation.include_in_reputation = should_include
            counters["relations_changed"] += 1
        if _upsert_triage_analysis(
            session,
            relation,
            result,
            should_include=should_include,
        ):
            counters["analyses_created"] += 1
        counters["alerts_ignored"] += _close_obsolete_alerts(
            session,
            relation,
            relevant=result.relevant,
            sentiment=result.sentiment,
            reply_recommended=result.reply_recommended,
        )
    return counters


def triage_social_comments(
    provider_name: str | None = None,
    *,
    replace_existing: bool = False,
    limit: int | None = None,
) -> dict[str, int | str]:
    session = SessionLocal()
    try:
        resolved = (provider_name or os.getenv("COMMENT_TRIAGE_PROVIDER") or DEFAULT_PROVIDER_NAME).strip().lower()
        bootstrap_fallback = False
        try:
            provider = get_provider(resolved)
        except Exception as provider_error:
            if resolved != "claude":
                raise
            print(f"Claude indisponible au démarrage ({provider_error}). Repli temporaire sur les règles strictes.")
            provider = RulesCommentTriageProvider()
            bootstrap_fallback = True
        rules_fallback = RulesCommentTriageProvider()
        comments = get_comments_to_triage(
            session,
            replace_existing=replace_existing,
            limit=limit,
        )
        print(f"Tri des commentaires avec : {resolved}")
        print(f"Commentaires à examiner : {len(comments)}")

        counters = {
            "comments_examined": len(comments),
            "relevant": 0,
            "positive": 0,
            "neutral": 0,
            "negative": 0,
            "reply_recommended": 0,
            "noise_excluded": 0,
            "failed": 0,
            "analyses_created": 0,
            "relations_changed": 0,
            "alerts_ignored": 0,
            "claude_fallbacks": 0,
        }

        for comment in comments:
            try:
                parent = session.get(Mention, comment.parent_mention_id) if comment.parent_mention_id else None
                parent_title = parent.display_title or parent.title if parent else None
                parent_text = (parent.clean_text or parent.raw_text) if parent else None
                # Le rattachement SQL à ARMA est un signal plus fiable que le seul
                # texte du titre, notamment pour les posts Serper tronqués.
                if _belongs_to_arma(session, comment, parent):
                    parent_title = f"[Publication rattachée à ARMA] {parent_title or ''}".strip()

                classify_kwargs = {
                    "comment_text": comment.clean_text or comment.raw_text,
                    "parent_title": parent_title,
                    "parent_text": parent_text,
                    "organization_name": OWN_ORGANIZATION_NAME,
                    "language_hint": comment.detected_language,
                }
                try:
                    result = provider.classify(**classify_kwargs)
                except Exception as provider_error:
                    if resolved != "claude":
                        raise
                    # Le manque de crédit Claude ne doit plus casser la chaîne
                    # collecte -> tri -> alertes. Le fallback privilégie la
                    # précision et exclut les sujets hors périmètre.
                    print(
                        f"Commentaire {comment.id}: Claude indisponible ({provider_error}); "
                        "repli sur les règles strictes."
                    )
                    result = rules_fallback.classify(**classify_kwargs)
                    counters["claude_fallbacks"] += 1
                    # Pour éviter des dizaines d'appels API voués à échouer
                    # (par exemple crédit Anthropic épuisé), le reste de ce run
                    # utilise directement les règles. Au prochain run, Claude
                    # sera retenté automatiquement avec la même configuration.
                    provider = rules_fallback
                    bootstrap_fallback = True
                else:
                    if bootstrap_fallback:
                        counters["claude_fallbacks"] += 1

                payload = dict(comment.raw_payload or {})
                triage_payload = result.to_dict()
                triage_payload["policy_version"] = TRIAGE_POLICY_VERSION
                triage_payload["classified_at"] = utc_now().isoformat()
                payload[TRIAGE_PAYLOAD_KEY] = triage_payload
                comment.raw_payload = payload

                preserved_flags = [
                    flag for flag in (comment.quality_flags or [])
                    if flag not in TRIAGE_FLAGS
                ]
                comment.quality_flags = list(dict.fromkeys(preserved_flags + result.quality_flags))
                comment.processing_status = "qualified" if result.relevant else "ignored"
                comment.display_in_marketing = False
                relation_counts = apply_triage_to_relations(session, comment, result=result)
                session.commit()

                counters["relations_changed"] += relation_counts["relations_changed"]
                counters["analyses_created"] += relation_counts["analyses_created"]
                counters["alerts_ignored"] += relation_counts["alerts_ignored"]
                if result.relevant:
                    counters["relevant"] += 1
                    counters[result.sentiment] += 1
                else:
                    counters["noise_excluded"] += 1
                if result.reply_recommended:
                    counters["reply_recommended"] += 1
                print(
                    f"Commentaire {comment.id} -> {result.category} | "
                    f"sentiment={result.sentiment} | score={result.relevant} | "
                    f"réponse={result.reply_recommended}"
                )
            except Exception as item_error:
                session.rollback()
                counters["failed"] += 1
                print(f"Commentaire {comment.id} ignoré (erreur) : {item_error}")

        print("\nClassification des commentaires terminée.")
        print(f"- Positifs : {counters['positive']}")
        print(f"- Neutres : {counters['neutral']}")
        print(f"- Négatifs : {counters['negative']}")
        print(f"- Bruit exclu du score : {counters['noise_excluded']}")
        print(f"- Réponses recommandées : {counters['reply_recommended']}")
        print(f"- Replis Claude -> règles : {counters['claude_fallbacks']}")
        print(f"- Échecs : {counters['failed']}")
        if counters["failed"]:
            raise RuntimeError(
                f"Tri des commentaires incomplet : {counters['failed']} échec(s)."
            )
        return {"provider": str(resolved), "policy_version": TRIAGE_POLICY_VERSION, **counters}
    finally:
        session.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classe tous les commentaires sociaux pour le score et les alertes.")
    parser.add_argument("--provider", choices=["rules", "claude"], default=None)
    parser.add_argument("--replace-existing", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    triage_social_comments(
        provider_name=args.provider,
        replace_existing=args.replace_existing,
        limit=args.limit,
    )
