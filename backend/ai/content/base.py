from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class PostDraft:
    """
    Résultat normalisé d'une génération de post pour une
    plateforme.

    content_by_language suit le format attendu par le modèle
    GeneratedPost, par exemple :
    {"fr": {"body": "...", "hashtags": ["#ARMA"]},
     "ar": {"body": "...", "hashtags": []}}
    """

    content_by_language: dict[str, dict[str, object]]
    image_prompt: str | None
    tone: list[str]
    model_provider: str
    model_name: str
    model_version: str | None = None
    details: dict = field(default_factory=dict)


class PostContentProvider(ABC):
    """
    Interface commune aux générateurs de posts marketing.

    Même logique pluggable que sentiment et response_drafts : le
    fournisseur actif peut être un gabarit local (sans clé API) ou
    Claude, au choix de l'appelant.
    """

    @abstractmethod
    def write_post(
        self,
        organization_name: str,
        platform: str,
        angle_title: str,
        angle_description: str,
        evidence_snippets: list[str],
    ) -> PostDraft:
        """Rédige un post bilingue (FR + AR) pour une plateforme donnée."""

        raise NotImplementedError
