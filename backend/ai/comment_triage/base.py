from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol


@dataclass(frozen=True)
class CommentTriageResult:
    """Résultat auditable du tri d'un commentaire social."""

    relevant: bool
    reply_recommended: bool
    category: str
    sentiment: str
    confidence: float
    reason: str
    needs_more_details: bool
    quality_flags: list[str]
    model_provider: str
    model_name: str
    model_version: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class CommentTriageProvider(Protocol):
    def classify(
        self,
        *,
        comment_text: str,
        parent_title: str | None = None,
        parent_text: str | None = None,
        organization_name: str = "ARMA",
        language_hint: str | None = None,
    ) -> CommentTriageResult:
        ...
