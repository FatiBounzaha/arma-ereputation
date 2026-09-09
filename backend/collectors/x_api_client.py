from __future__ import annotations

import os
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()


class XApiClient:
    """Client minimal X API v2 pour la recherche récente publique."""

    def __init__(self, bearer_token: str | None = None, timeout: int = 30) -> None:
        self.bearer_token = bearer_token or os.getenv("X_BEARER_TOKEN")
        self.base_url = (os.getenv("X_API_BASE_URL") or "https://api.x.com/2").rstrip("/")
        self.timeout = timeout
        if not self.bearer_token:
            raise RuntimeError("X_BEARER_TOKEN est absent du fichier .env.")

    def search_recent(self, query: str, max_results: int = 25) -> dict[str, Any]:
        response = requests.get(
            f"{self.base_url}/tweets/search/recent",
            headers={"Authorization": f"Bearer {self.bearer_token}"},
            params={
                "query": query,
                "max_results": max(10, min(max_results, 100)),
                "tweet.fields": "id,text,author_id,created_at,lang,public_metrics,conversation_id",
                "expansions": "author_id",
                "user.fields": "id,name,username,public_metrics,verified",
            },
            timeout=self.timeout,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            try:
                details = response.json()
            except ValueError:
                details = response.text
            raise RuntimeError(f"Erreur X API HTTP {response.status_code}: {details}") from error
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Réponse X API inattendue.")
        return payload
