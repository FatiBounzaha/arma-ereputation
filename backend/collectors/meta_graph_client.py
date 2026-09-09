from __future__ import annotations

import os
from typing import Any

import requests
from dotenv import load_dotenv


load_dotenv()


class MetaGraphClient:
    """Client minimal pour lire les commentaires Facebook via Graph API."""

    def __init__(
        self,
        access_token: str | None = None,
        graph_version: str | None = None,
        timeout: int = 30,
    ) -> None:
        self.access_token = access_token or os.getenv("META_ACCESS_TOKEN")
        self.graph_version = (
            graph_version or os.getenv("META_GRAPH_VERSION") or ""
        ).strip()
        self.timeout = timeout

        if not self.access_token:
            raise RuntimeError(
                "META_ACCESS_TOKEN est absent du fichier .env."
            )
        if not self.graph_version:
            raise RuntimeError(
                "META_GRAPH_VERSION est absent du fichier .env. "
                "Utilise la version affichée dans ton application Meta."
            )

        self.base_url = (
            f"https://graph.facebook.com/{self.graph_version.strip('/')}"
        )

    def _get(
        self,
        path_or_url: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = (
            path_or_url
            if path_or_url.startswith("https://")
            else f"{self.base_url}/{path_or_url.lstrip('/')}"
        )
        request_params = dict(params or {})
        request_params.setdefault("access_token", self.access_token)

        try:
            response = requests.get(
                url,
                params=request_params,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.Timeout as error:
            raise RuntimeError(
                "Meta Graph API a mis trop de temps à répondre."
            ) from error
        except requests.HTTPError as error:
            try:
                details = response.json()
            except ValueError:
                details = response.text
            raise RuntimeError(
                "Erreur Meta Graph API. "
                f"HTTP {response.status_code}. Détails : {details}"
            ) from error
        except requests.RequestException as error:
            raise RuntimeError(
                "Impossible de communiquer avec Meta Graph API."
            ) from error

        try:
            payload = response.json()
        except ValueError as error:
            raise RuntimeError(
                "La réponse Meta Graph API n'est pas un JSON valide."
            ) from error

        if not isinstance(payload, dict):
            raise RuntimeError("Réponse Meta Graph API inattendue.")
        return payload

    def post_comment_reply(self, comment_id: str, message: str) -> dict[str, Any]:
        """Reply through the official Graph API and return Meta's confirmation."""
        if not message.strip():
            raise ValueError("La réponse ne peut pas être vide.")
        try:
            response = requests.post(
                f"{self.base_url}/{comment_id}/comments",
                data={"message": message.strip(), "access_token": self.access_token},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout as error:
            raise RuntimeError("Meta Graph API a mis trop de temps à répondre.") from error
        except requests.HTTPError as error:
            try:
                detail = response.json().get("error", {})
                message_text = detail.get("message") or "permission refusée ou token expiré"
            except (ValueError, AttributeError):
                message_text = "erreur HTTP Meta"
            raise RuntimeError(f"Envoi Meta refusé (HTTP {response.status_code}) : {message_text}") from error
        except requests.RequestException as error:
            raise RuntimeError("Impossible de communiquer avec Meta Graph API.") from error
        if not isinstance(payload, dict) or not payload.get("id"):
            raise RuntimeError("Meta n'a pas confirmé l'envoi de la réponse.")
        return payload

    def get_comments(
        self,
        object_id: str,
        page_size: int = 100,
        max_pages: int = 3,
    ) -> list[dict[str, Any]]:
        """Lit les commentaires directs d'un post ou les réponses d'un commentaire."""

        fields = (
            "id,message,created_time,from,like_count,comment_count,"
            "permalink_url,parent"
        )
        payload = self._get(
            f"{object_id}/comments",
            params={
                "fields": fields,
                "limit": max(1, min(page_size, 100)),
                "order": "chronological",
            },
        )

        comments: list[dict[str, Any]] = []
        pages_read = 0

        while payload and pages_read < max_pages:
            pages_read += 1
            data = payload.get("data", [])
            if isinstance(data, list):
                comments.extend(
                    item for item in data if isinstance(item, dict)
                )

            paging = payload.get("paging") or {}
            next_url = paging.get("next") if isinstance(paging, dict) else None
            if not next_url or pages_read >= max_pages:
                break
            payload = self._get(str(next_url))

        return comments
