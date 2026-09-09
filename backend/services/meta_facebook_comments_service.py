from __future__ import annotations

import os
from typing import Any

from backend.collectors.meta_graph_client import MetaGraphClient


def _configured(value: str | None) -> bool:
    value = (value or "").strip()
    return bool(value and not value.lower().startswith(("your_", "vxx")) and value != "...")


def integration_status() -> dict[str, Any]:
    token = _configured(os.getenv("META_ACCESS_TOKEN"))
    version = _configured(os.getenv("META_GRAPH_API_VERSION") or os.getenv("META_GRAPH_VERSION"))
    page = _configured(os.getenv("META_PAGE_ID")) or _configured(os.getenv("META_FACEBOOK_PAGE_IDS"))
    available = token and version and page
    return {
        "status": "available" if available else "permission_required",
        "available": available,
        "message": (
            "Intégration Meta configurée pour la collecte autorisée et l’envoi de réponses."
            if available
            else "Envoi Facebook indisponible : une Page et des autorisations Meta sont requises."
        ),
        "demo_enabled": (os.getenv("DEMO_FACEBOOK_COMMENTS") or "false").strip().lower() == "true",
    }


def send_reply(platform_comment_id: str, response_text: str) -> dict[str, Any]:
    state = integration_status()
    if not state["available"]:
        raise RuntimeError("Envoi indisponible : connectez une Page Facebook autorisée via Meta.")
    client = MetaGraphClient(graph_version=os.getenv("META_GRAPH_API_VERSION") or os.getenv("META_GRAPH_VERSION"))
    return client.post_comment_reply(platform_comment_id, response_text)
