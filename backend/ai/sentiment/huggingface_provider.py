from __future__ import annotations

import os

from backend.ai.sentiment.base import SentimentProvider, SentimentResult

try:
    from transformers import pipeline as hf_pipeline
except ImportError:  # pragma: no cover - dépend de l'environnement d'exécution
    hf_pipeline = None


# Modèle multilingue (8 langues, dont le français et l'arabe standard).
# Le darija marocain n'est pas spécifiquement couvert par ce modèle :
# c'est une limite connue, à documenter dans l'état de l'art NLP arabe
# du rapport de PFA.
DEFAULT_MODEL_NAME = "cardiffnlp/twitter-xlm-roberta-base-sentiment"

# Les modèles de type BERT/RoBERTa tronquent de toute façon à 512
# tokens : on limite la taille du texte envoyé pour rester rapide.
MAX_INPUT_CHARACTERS = 2000


class HuggingFaceSentimentProvider(SentimentProvider):
    """
    Analyse de sentiment via un modèle Transformers exécuté en local.

    Ne nécessite aucune clé API : le modèle est téléchargé une seule
    fois (cache HuggingFace, dossier ~/.cache/huggingface) puis
    exécuté localement pour chaque analyse.
    """

    def __init__(self, model_name: str | None = None) -> None:
        if hf_pipeline is None:
            raise RuntimeError(
                "Les paquets 'transformers' et 'torch' ne sont pas "
                "installés. Lancez : pip install -r requirements.txt"
            )

        self.model_name = (
            model_name
            or os.getenv("HF_SENTIMENT_MODEL")
            or DEFAULT_MODEL_NAME
        )

        # Le chargement du modèle est coûteux : il se fait une seule
        # fois par instance, réutilisée pour toutes les mentions
        # traitées pendant un même run.
        self._pipeline = hf_pipeline(
            task="text-classification",
            model=self.model_name,
            top_k=None,
            truncation=True,
            max_length=512,
        )

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

        predictions = self._pipeline(cleaned_text)[0]

        scores = {
            prediction["label"].lower(): float(prediction["score"])
            for prediction in predictions
        }

        return build_result_from_scores(
            scores=scores,
            model_name=self.model_name,
            language_hint=language_hint,
        )


def build_result_from_scores(
    scores: dict[str, float],
    model_name: str,
    language_hint: str | None,
) -> SentimentResult:
    """
    Construit un SentimentResult à partir des scores bruts du modèle.

    Séparée de analyze() pour être testable sans charger le modèle
    Transformers (voir test_score_mapping ci-dessous).
    """

    best_label = max(scores, key=scores.get)

    return SentimentResult(
        sentiment_label=best_label,
        positive_score=scores.get("positive"),
        neutral_score=scores.get("neutral"),
        negative_score=scores.get("negative"),
        confidence=scores[best_label],
        analysis_language=language_hint,
        explanation=None,
        model_provider="huggingface",
        model_name=model_name,
        model_version=None,
        details={"scores": scores},
    )


def test_score_mapping() -> None:
    """Test local sans modèle Transformers ni téléchargement."""

    print("TEST DU MAPPAGE DES SCORES HUGGINGFACE")
    print("=" * 72)

    cases = [
        {"negative": 0.05, "neutral": 0.10, "positive": 0.85},
        {"negative": 0.70, "neutral": 0.20, "positive": 0.10},
        {"negative": 0.34, "neutral": 0.33, "positive": 0.33},
    ]

    for scores in cases:
        result = build_result_from_scores(
            scores=scores,
            model_name="test-model",
            language_hint="fr",
        )

        print(f"\nScores : {scores}")
        print(f"Label retenu : {result.sentiment_label}")
        print(f"Confiance : {result.confidence:.2f}")


if __name__ == "__main__":
    test_score_mapping()
