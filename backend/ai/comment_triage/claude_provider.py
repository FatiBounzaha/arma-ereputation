from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv

from backend.ai.comment_triage.base import CommentTriageResult
from backend.ai.json_utils import extract_json_object, positive_int_env
from backend.ai.comment_triage.rules_provider import RulesCommentTriageProvider, is_obvious_noise

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None


load_dotenv()

DEFAULT_MODEL_NAME = "claude-haiku-4-5-20251001"
MAX_COMMENT_CHARACTERS = 1500
MAX_PARENT_CHARACTERS = 1800

EXCLUDED_CATEGORIES = {"noise", "competitor_only", "off_topic"}
ALLOWED_CATEGORIES = {
    "operational_complaint",
    "service_question",
    "suggestion",
    "positive_feedback",
    "service_feedback",
    "general_feedback",
    "general_criticism",
    *EXCLUDED_CATEGORIES,
}

SYSTEM_PROMPT = """
Tu es l'agent de classification des commentaires du portail interne d'ARMA,
entreprise de propreté urbaine. Tous les commentaires publics liés à ARMA ou au
service doivent être classés pour calculer le score de réputation. Tu ne publies rien.

Objectif obligatoire :
1. conserver les retours positifs, neutres et négatifs liés à ARMA ;
2. attribuer exactement un sentiment : positive, neutral ou negative ;
3. recommander une réponse quand une plainte, une question, une suggestion ou une critique peut
   recevoir une réponse utile ;
4. exclure le bruit, le spam, les prix seuls, le hors-sujet et les
   commentaires qui concernent uniquement un concurrent sans parler d'ARMA ;
5. ne jamais considérer le simple rattachement au post parent comme une preuve
   suffisante de pertinence : une demande de logement social, d'emploi, de visa,
   d'aide administrative ou tout autre sujet sans lien avec la propreté urbaine
   doit être off_topic, même si elle est écrite sous une publication ARMA.

Règles de sentiment envers ARMA (et non le ton général du commentaire) :
- positive uniquement si le commentaire exprime un éloge, une satisfaction ou une amélioration
  explicitement attribuée à ARMA / à la qualité de son service ;
- neutral pour une question, une suggestion sans plainte, une information factuelle, une
  responsabilité partagée ou un commentaire qui accuse surtout les citoyens / un tiers ;
- negative dès que le commentaire décrit une mauvaise qualité de service, des déchets non
  ramassés, une rue sale, un manque de moyens/personnel, une absence de propreté, un retard,
  une odeur, une dégradation ou une autre plainte liée à ARMA, même si le message est poli,
  commence par « merci » ou propose ensuite une solution. Une critique constructive reste
  négative si elle décrit un dysfonctionnement réel.
- le mot « propreté » ne constitue jamais à lui seul un signal positif.
- « merci de faire le nécessaire » n'est pas un compliment : analyser le contenu qui suit.
- un commentaire qui défend ARMA ou attribue le problème aux citoyens est neutre par défaut,
  sauf s'il contient aussi un éloge explicite d'ARMA.
Toute critique négative réellement liée à ARMA doit être relevant=true et
sentiment=negative afin d'apparaître dans les alertes. reply_recommended peut
rester false pour une insulte seule ou un message auquel une réponse publique
serait inappropriée. Toute réponse sera validée par un humain.

Réponds uniquement avec un JSON valide, sans markdown :
{
  "relevant": true,
  "reply_recommended": true,
  "category": "operational_complaint|service_question|suggestion|positive_feedback|service_feedback|general_feedback|general_criticism|noise|competitor_only|off_topic",
  "sentiment": "positive|neutral|negative",
  "confidence": 0.0,
  "reason": "raison courte en français",
  "needs_more_details": true,
  "quality_flags": ["comment_relevant", "comment_actionable", "reputation_signal"]
}
""".strip()


class ClaudeCommentTriageProvider:
    """Filtre les commentaires utiles avec Claude, après préfiltre anti-bruit."""

    def __init__(self, model_name: str | None = None) -> None:
        if anthropic is None:
            raise RuntimeError("Le paquet 'anthropic' n'est pas installé.")
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key or api_key == "your_anthropic_api_key":
            raise RuntimeError("ANTHROPIC_API_KEY est absente ou vide.")
        self.model_name = model_name or os.getenv("COMMENT_TRIAGE_MODEL") or DEFAULT_MODEL_NAME
        self._client = anthropic.Anthropic(api_key=api_key)
        self._rules = RulesCommentTriageProvider()

    def classify(
        self,
        *,
        comment_text: str,
        parent_title: str | None = None,
        parent_text: str | None = None,
        organization_name: str = "ARMA",
        language_hint: str | None = None,
    ) -> CommentTriageResult:
        # Évite de payer un appel Claude pour « l », un emoji ou un commentaire vide.
        if is_obvious_noise(comment_text):
            return self._rules.classify(
                comment_text=comment_text,
                parent_title=parent_title,
                parent_text=parent_text,
                organization_name=organization_name,
                language_hint=language_hint,
            )

        user_prompt = (
            f"Organisation surveillée : {organization_name}\n"
            f"Langue détectée : {language_hint or 'inconnue'}\n"
            f"Titre du post parent : {(parent_title or '')[:500]}\n"
            f"Contexte du post parent : {(parent_text or '')[:MAX_PARENT_CHARACTERS]}\n\n"
            f"Commentaire à trier :\n{(comment_text or '')[:MAX_COMMENT_CHARACTERS]}"
        )
        attempts = positive_int_env("LLM_MAX_RETRIES", 2, maximum=5) + 1
        max_tokens = positive_int_env("COMMENT_TRIAGE_MAX_TOKENS", 600, minimum=300, maximum=2000)
        last_error: Exception | None = None
        response = None
        payload = None
        for attempt in range(1, attempts + 1):
            response = self._client.messages.create(
                model=self.model_name,
                max_tokens=max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            try:
                payload = parse_payload(response.content[0].text)
                break
            except RuntimeError as error:
                last_error = error
                print(f"Tri Claude invalide, tentative {attempt}/{attempts}.")
        if payload is None or response is None:
            raise RuntimeError(f"Tri Claude invalide après {attempts} tentatives : {last_error}")

        # Garde-fou métier : le LLM ne doit ni perdre un signal positif/négatif
        # évident, ni attribuer à ARMA une plainte qui concerne uniquement un concurrent.
        rules_result = self._rules.classify(
            comment_text=comment_text,
            parent_title=parent_title,
            parent_text=parent_text,
            organization_name=organization_name,
            language_hint=language_hint,
        )
        if not rules_result.relevant and rules_result.category in {"noise", "competitor_only", "off_topic"}:
            payload.update(
                {
                    "relevant": False,
                    "reply_recommended": False,
                    "category": rules_result.category,
                    "sentiment": "neutral",
                    "confidence": max(float(payload.get("confidence", 0.0) or 0.0), rules_result.confidence),
                    "reason": rules_result.reason,
                    "needs_more_details": False,
                    "quality_flags": rules_result.quality_flags + ["llm_with_business_guardrail"],
                }
            )
        elif rules_result.relevant:
            payload["relevant"] = True
            payload["confidence"] = max(
                float(payload.get("confidence", 0.0) or 0.0),
                rules_result.confidence,
            )
            # Invariant métier : une catégorie exclue ne peut jamais coexister
            # avec relevant=true. Si les règles strictes détectent un vrai signal
            # ARMA alors que Claude a renvoyé off_topic/noise/competitor_only,
            # on conserve la catégorie métier issue des règles.
            payload_category = str(payload.get("category") or "").strip().lower()
            if payload_category in EXCLUDED_CATEGORIES:
                payload["category"] = rules_result.category
                payload["sentiment"] = rules_result.sentiment
                payload["reason"] = rules_result.reason
            elif "strong_sentiment_guardrail" in rules_result.quality_flags or "sentiment_guardrail_neutral" in rules_result.quality_flags:
                # Les règles n'écrasent Claude que pour un signal vraiment
                # non ambigu (plainte explicite, éloge explicite ou défense/
                # responsabilité partagée). Sinon Claude garde le contexte.
                payload["sentiment"] = rules_result.sentiment
                payload["category"] = rules_result.category
                payload["reason"] = rules_result.reason
            if rules_result.reply_recommended:
                payload["reply_recommended"] = True
                payload["needs_more_details"] = rules_result.needs_more_details
            flags = [str(flag) for flag in payload.get("quality_flags", [])]
            payload["quality_flags"] = list(dict.fromkeys(
                flags + rules_result.quality_flags + ["llm_with_business_guardrail"]
            ))

        return result_from_payload(payload, self.model_name, response.model)


def parse_payload(raw_output: str) -> dict[str, Any]:
    try:
        return extract_json_object(raw_output)
    except RuntimeError as error:
        raise RuntimeError("Tri Claude non exploitable (JSON invalide ou tronqué).") from error


def result_from_payload(
    payload: dict[str, Any],
    model_name: str,
    model_version: str | None,
) -> CommentTriageResult:
    relevant = bool(payload.get("relevant", False))
    category = str(payload.get("category") or ("general_feedback" if relevant else "off_topic")).strip().lower()
    if category not in ALLOWED_CATEGORIES:
        category = "general_feedback" if relevant else "off_topic"

    sentiment = str(payload.get("sentiment") or "neutral").lower()
    if sentiment not in {"positive", "neutral", "negative"}:
        sentiment = "neutral"

    # Invariant final non négociable : noise / competitor_only / off_topic
    # sont toujours exclus du score et ne peuvent jamais recommander une réponse.
    if category in EXCLUDED_CATEGORIES:
        relevant = False
        sentiment = "neutral"
    reply_recommended = bool(payload.get("reply_recommended", False)) and relevant
    # Un simple compliment/soutien n'est pas une alerte « à traiter ». Les
    # réponses sont réservées aux plaintes, questions et suggestions actionnables.
    if category == "positive_feedback" and sentiment == "positive":
        reply_recommended = False
    try:
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5

    flags = [str(flag) for flag in payload.get("quality_flags", []) if str(flag).strip()]
    if not relevant:
        flags = [
            flag
            for flag in flags
            if flag not in {
                "comment_relevant",
                "comment_actionable",
                "reputation_signal",
                "negative_alert_candidate",
            }
        ]
    required_flag = "comment_relevant" if relevant else "comment_noise"
    if required_flag not in flags:
        flags.append(required_flag)
    action_flag = "comment_actionable" if reply_recommended else "comment_not_actionable"
    if action_flag not in flags:
        flags.append(action_flag)

    return CommentTriageResult(
        relevant=relevant,
        reply_recommended=reply_recommended,
        category=category,
        sentiment=sentiment,
        confidence=confidence,
        reason=str(payload.get("reason") or "Commentaire trié par Claude."),
        needs_more_details=bool(payload.get("needs_more_details", False)) if relevant else False,
        quality_flags=list(dict.fromkeys(flags)),
        model_provider="anthropic",
        model_name=model_name,
        model_version=model_version,
    )
