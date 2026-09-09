from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResponseDraftResult:
    """Résultat normalisé d'une décision et d'une rédaction de réponse."""

    content_by_language: dict[str, str]
    tone: list[str]
    model_provider: str
    model_name: str
    model_version: str | None = None
    details: dict = field(default_factory=dict)


class ResponseDraftProvider(ABC):
    """Interface commune aux générateurs de brouillons contextuels."""

    @abstractmethod
    def draft(
        self,
        organization_name: str,
        alert_reason: str,
        mention_text: str,
        severity: str,
        context: dict[str, Any] | None = None,
    ) -> ResponseDraftResult:
        """Décide de l'action puis génère, si nécessaire, un texte FR/AR."""

        raise NotImplementedError
