from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SentimentResult:
    """
    Résultat normalisé d'une analyse de sentiment.

    Toutes les implémentations de SentimentProvider retournent
    ce même format, quel que soit le fournisseur utilisé.
    """

    sentiment_label: str
    positive_score: float | None
    neutral_score: float | None
    negative_score: float | None
    confidence: float | None
    analysis_language: str | None
    explanation: str | None
    model_provider: str
    model_name: str
    model_version: str | None = None
    details: dict = field(default_factory=dict)


class SentimentProvider(ABC):
    """
    Interface commune à tous les moteurs de sentiment.

    Le pipeline NLP (backend.ai.sentiment.service) ne dépend que
    de cette interface. On peut donc changer de fournisseur
    (modèles locaux, Claude, ...) sans toucher au reste du code.
    """

    @abstractmethod
    def analyze(
        self,
        text: str,
        language_hint: str | None = None,
    ) -> SentimentResult:
        """
        Analyse le sentiment d'un texte.

        language_hint est la langue détectée à la collecte
        (fr / ar), fournie à titre indicatif seulement :
        chaque fournisseur reste libre de la confirmer ou non.
        """

        raise NotImplementedError
