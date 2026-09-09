from __future__ import annotations

import os
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()


class InstagramGraphClient:
    """Client Meta Graph pour le compte Instagram professionnel ARMA."""

    def __init__(self, access_token: str | None = None, graph_version: str | None = None, timeout: int = 30) -> None:
        self.access_token = access_token or os.getenv("META_ACCESS_TOKEN")
        self.graph_version = (graph_version or os.getenv("META_GRAPH_VERSION") or "").strip("/")
        self.timeout = timeout
        if not self.access_token or not self.graph_version:
            raise RuntimeError("META_ACCESS_TOKEN et META_GRAPH_VERSION sont requis.")
        self.base_url = f"https://graph.facebook.com/{self.graph_version}"

    def _get(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = path_or_url if path_or_url.startswith("https://") else f"{self.base_url}/{path_or_url.lstrip('/')}"
        request_params = dict(params or {})
        request_params.setdefault("access_token", self.access_token)
        response = requests.get(url, params=request_params, timeout=self.timeout)
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            try:
                details = response.json()
            except ValueError:
                details = response.text
            raise RuntimeError(f"Erreur Instagram Graph API HTTP {response.status_code}: {details}") from error
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Réponse Instagram Graph API inattendue.")
        return payload

    def _paginate(self, payload: dict[str, Any], max_pages: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        pages = 0
        while payload and pages < max_pages:
            pages += 1
            data = payload.get("data") or []
            if isinstance(data, list):
                items.extend(item for item in data if isinstance(item, dict))
            paging = payload.get("paging") or {}
            next_url = paging.get("next") if isinstance(paging, dict) else None
            if not next_url:
                break
            payload = self._get(str(next_url))
        return items

    def get_media(self, instagram_account_id: str, limit: int = 25, max_pages: int = 2) -> list[dict[str, Any]]:
        payload = self._get(
            f"{instagram_account_id}/media",
            params={
                "fields": "id,caption,media_type,permalink,timestamp,username,comments_count,like_count",
                "limit": max(1, min(limit, 100)),
            },
        )
        return self._paginate(payload, max_pages)

    def get_comments(self, media_id: str, limit: int = 100, max_pages: int = 3) -> list[dict[str, Any]]:
        payload = self._get(
            f"{media_id}/comments",
            params={
                "fields": "id,text,timestamp,username,like_count",
                "limit": max(1, min(limit, 100)),
            },
        )
        return self._paginate(payload, max_pages)
