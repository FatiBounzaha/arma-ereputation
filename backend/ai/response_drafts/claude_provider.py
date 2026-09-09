from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv

from backend.ai.json_utils import extract_json_object, positive_int_env
from backend.ai.response_drafts.base import (
    ResponseDraftProvider,
    ResponseDraftResult,
)
from backend.ai.response_drafts.decision import decide_response_action

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

load_dotenv()

DEFAULT_MODEL_NAME = "claude-haiku-4-5-20251001"
MAX_INPUT_CHARACTERS = 4000

SYSTEM_PROMPT = """
Tu es le rédacteur du portail interne d'ARMA, entreprise marocaine de propreté urbaine.
Une étape de décision métier a déjà déterminé l'action recommandée. Tu dois respecter
cette décision et ne jamais transformer une alerte presse en simple réclamation client.

Règles :
- public_reply : réponse courte (2 à 4 phrases), empathique et opérationnelle, directement liée au commentaire.
  Ne jamais inventer une intervention. Si la décision contient ask_for_private_details=true, demander en message privé
  le quartier/rue et le moment du problème ; sinon ne pas poser de question générique inutile.
- official_statement : projet de communiqué prudent, sans reconnaître des faits non vérifiés.
- internal_escalation : projet de message de réserve destiné à validation Communication/Juridique ;
  ne pas demander lieu/date et ne pas prétendre qu'il sera publié automatiquement.
- monitor : expliquer qu'une vérification est nécessaire ; aucune réponse publique immédiate.
- no_reply : indiquer qu'aucune réponse publique n'est recommandée.
- Toute sortie exige une validation humaine avant diffusion.
- Réponds uniquement avec un objet JSON valide, sans markdown.

Format exact :
{
  "fr": "texte français",
  "ar": "texte arabe standard ou darija si le contenu d'origine est en darija",
  "tone": ["adjectif1", "adjectif2"],
  "internal_note": "note interne concise",
  "rationale": "raison concise"
}
""".strip()


class ClaudeResponseDraftProvider(ResponseDraftProvider):
    """Rédaction contextuelle via Claude, après décision métier déterministe."""

    def __init__(self, model_name: str | None = None) -> None:
        if anthropic is None:
            raise RuntimeError("Le paquet 'anthropic' n'est pas installé.")

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key or api_key == "your_anthropic_api_key":
            raise RuntimeError(
                "ANTHROPIC_API_KEY est absente ou vide. Utilisez RESPONSE_DRAFT_PROVIDER=template en attendant."
            )

        self.model_name = model_name or DEFAULT_MODEL_NAME
        self._client = anthropic.Anthropic(api_key=api_key)

    def draft(
        self,
        organization_name: str,
        alert_reason: str,
        mention_text: str,
        severity: str,
        context: dict[str, Any] | None = None,
    ) -> ResponseDraftResult:
        resolved_context = dict(context or {})
        resolved_context.setdefault("alert_reason", alert_reason)
        resolved_context.setdefault("mention_text", mention_text)
        resolved_context.setdefault("severity", severity)
        decision = decide_response_action(resolved_context)

        cleaned_text = (mention_text or "").strip()[:MAX_INPUT_CHARACTERS]
        context_json = json.dumps(
            {
                key: resolved_context.get(key)
                for key in (
                    "content_type", "source_type", "source_name", "title",
                    "author_name", "mention_url", "parent_title", "parent_excerpt",
                    "city", "business_category", "engagement", "comment_triage",
                )
            },
            ensure_ascii=False,
        )

        user_prompt = (
            f"Organisation : {organization_name}\n"
            f"Sévérité : {severity}\n"
            f"Décision obligatoire : {json.dumps(decision.to_dict(), ensure_ascii=False)}\n"
            f"Contexte source : {context_json}\n"
            f"Motif d'alerte : {alert_reason}\n\n"
            f"Contenu original :\n{cleaned_text or alert_reason}"
        )

        attempts = positive_int_env("LLM_MAX_RETRIES", 2, maximum=5) + 1
        max_tokens = positive_int_env("RESPONSE_MAX_TOKENS", 1800, minimum=600, maximum=5000)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            response = self._client.messages.create(
                model=self.model_name,
                max_tokens=max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            try:
                payload = parse_response_payload(response.content[0].text)
                return build_result_from_payload(
                    payload=payload,
                    model_name=self.model_name,
                    model_version=response.model,
                    decision=decision.to_dict(),
                )
            except RuntimeError as error:
                last_error = error
                print(f"Réponse Claude brouillon invalide, tentative {attempt}/{attempts}.")
        raise RuntimeError(f"Claude n'a pas renvoyé un JSON valide après {attempts} tentatives : {last_error}")


def parse_response_payload(raw_output: str) -> dict:
    try:
        return extract_json_object(raw_output)
    except RuntimeError as error:
        raise RuntimeError("Réponse Claude non exploitable (JSON invalide ou tronqué).") from error


def build_result_from_payload(
    payload: dict,
    model_name: str,
    model_version: str | None,
    decision: dict | None = None,
) -> ResponseDraftResult:
    if "fr" not in payload or "ar" not in payload:
        raise RuntimeError(f"Réponse Claude incomplète, 'fr'/'ar' manquant : {payload}")

    details = dict(decision or {})
    details.update(
        {
            "internal_note": payload.get("internal_note") or details.get("rationale", ""),
            "writer_rationale": payload.get("rationale", ""),
        }
    )

    return ResponseDraftResult(
        content_by_language={"fr": payload["fr"], "ar": payload["ar"]},
        tone=payload.get("tone", []),
        model_provider="anthropic",
        model_name=model_name,
        model_version=model_version,
        details=details,
    )


def test_parse_response() -> None:
    valid_response = (
        '{"fr":"Texte FR","ar":"نص عربي","tone":["factuel"],'
        '"internal_note":"Validation requise","rationale":"Article de presse"}'
    )
    payload = parse_response_payload(valid_response)
    result = build_result_from_payload(payload, "test", "v1", {"action": "official_statement"})
    print(result)


if __name__ == "__main__":
    test_parse_response()
