from __future__ import annotations

import os

from dotenv import load_dotenv

from backend.ai.sentiment.base import SentimentProvider, SentimentResult
from backend.ai.json_utils import extract_json_object, positive_int_env

try:
    import anthropic
except ImportError:  # pragma: no cover - dépend de l'environnement d'exécution
    anthropic = None

load_dotenv()

# Modèle économique, adapté à une classification répétée sur un
# grand volume de mentions.
DEFAULT_MODEL_NAME = "claude-haiku-4-5-20251001"

MAX_INPUT_CHARACTERS = 4000

SYSTEM_PROMPT = (
    "Tu es un analyste e-réputation pour des entreprises marocaines "
    "de propreté urbaine (ARMA, OZONE, Averda, Suez, SOS). "
    "Tu réponds uniquement avec un objet JSON valide, sans texte "
    "autour, respectant exactement ce format : "
    '{"sentiment_label": "positive|neutral|negative", '
    '"positive_score": 0-1, "neutral_score": 0-1, "negative_score": 0-1, '
    '"confidence": 0-1, "analysis_language": "fr|ar|darija|mixed", '
    '"explanation": "une phrase courte en français"}. '
    "Les trois scores doivent être cohérents avec le label choisi "
    "et sommer approximativement à 1. Le champ analysis_language doit "
    "distinguer l'arabe standard (ar) du darija marocain (darija)."
)


class ClaudeSentimentProvider(SentimentProvider):
    """
    Analyse de sentiment via l'API Claude (Anthropic).

    Nécessite le paquet 'anthropic' installé et une clé
    ANTHROPIC_API_KEY valide dans le fichier .env. Recommandé à
    terme pour sa bonne couverture du darija marocain, que les
    modèles NLP locaux gèrent mal.
    """

    def __init__(self, model_name: str | None = None) -> None:
        if anthropic is None:
            raise RuntimeError(
                "Le paquet 'anthropic' n'est pas installé. "
                "Lancez : pip install anthropic"
            )

        api_key = os.getenv("ANTHROPIC_API_KEY")

        if not api_key or api_key == "your_anthropic_api_key":
            raise RuntimeError(
                "ANTHROPIC_API_KEY est absente ou vide dans le fichier "
                ".env. Renseignez une clé valide pour utiliser ce "
                "fournisseur, ou utilisez SENTIMENT_PROVIDER=huggingface "
                "en attendant."
            )

        self.model_name = model_name or DEFAULT_MODEL_NAME
        self._client = anthropic.Anthropic(api_key=api_key)

    def analyze(
        self,
        text: str,
        language_hint: str | None = None,
    ) -> SentimentResult:
        cleaned_text = (text or "").strip()[:MAX_INPUT_CHARACTERS]

        if not cleaned_text:
            raise ValueError(
                "Impossible d'analyser un texte vide."
            )

        user_prompt = (
            "Analyse le sentiment du texte suivant (langue détectée "
            f"à la collecte : {language_hint or 'inconnue'}) :\n\n"
            f"{cleaned_text}"
        )

        attempts = positive_int_env("LLM_MAX_RETRIES", 2, maximum=5) + 1
        max_tokens = positive_int_env("SENTIMENT_MAX_TOKENS", 450, minimum=250, maximum=1500)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            response = self._client.messages.create(
                model=self.model_name,
                max_tokens=max_tokens,
                system=SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": user_prompt},
                ],
            )
            try:
                payload = parse_response_payload(response.content[0].text)
                return build_result_from_payload(
                    payload=payload,
                    model_name=self.model_name,
                    model_version=response.model,
                )
            except RuntimeError as error:
                last_error = error
                print(f"Sentiment Claude invalide, tentative {attempt}/{attempts}.")
        raise RuntimeError(f"Sentiment Claude invalide après {attempts} tentatives : {last_error}")


def parse_response_payload(raw_output: str) -> dict:
    try:
        return extract_json_object(raw_output)
    except RuntimeError as error:
        raise RuntimeError("Réponse Claude non exploitable (JSON invalide ou tronqué).") from error


def build_result_from_payload(
    payload: dict,
    model_name: str,
    model_version: str | None,
) -> SentimentResult:
    """Construit un SentimentResult à partir du JSON renvoyé par Claude."""

    if "sentiment_label" not in payload:
        raise RuntimeError(
            "Réponse Claude incomplète, 'sentiment_label' manquant : "
            f"{payload}"
        )

    return SentimentResult(
        sentiment_label=payload["sentiment_label"],
        positive_score=payload.get("positive_score"),
        neutral_score=payload.get("neutral_score"),
        negative_score=payload.get("negative_score"),
        confidence=payload.get("confidence"),
        analysis_language=payload.get("analysis_language"),
        explanation=payload.get("explanation"),
        model_provider="anthropic",
        model_name=model_name,
        model_version=model_version,
        details=payload,
    )


def test_parse_response() -> None:
    """Test local sans clé API ni appel réseau."""

    print("TEST DU PARSING DES RÉPONSES CLAUDE")
    print("=" * 72)

    valid_response = (
        '{"sentiment_label": "negative", "positive_score": 0.05, '
        '"neutral_score": 0.15, "negative_score": 0.80, '
        '"confidence": 0.80, "analysis_language": "darija", '
        '"explanation": "Plainte sur un retard de collecte."}'
    )

    payload = parse_response_payload(valid_response)
    result = build_result_from_payload(
        payload=payload,
        model_name="test-model",
        model_version="test-version",
    )

    print(
        f"\nRéponse valide -> label={result.sentiment_label}, "
        f"langue={result.analysis_language}"
    )

    fenced_response = f"```json\n{valid_response}\n```"
    fenced_payload = parse_response_payload(fenced_response)

    print(
        "Réponse encadrée de ```json : "
        f"{'OK' if fenced_payload == payload else 'ÉCHEC'}"
    )

    try:
        parse_response_payload("ceci n'est pas du JSON")
        print("ERREUR : aucune exception levée pour un JSON invalide.")
    except RuntimeError as error:
        print(f"\nJSON invalide correctement détecté : {error}")


if __name__ == "__main__":
    test_parse_response()
