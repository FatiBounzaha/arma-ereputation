from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from backend.database.connection import SessionLocal
from backend.services.facebook_retained_links_service import export_retained_facebook_links
from backend.services.facebook_screenshot_service import (
    capture_retained_facebook_posts,
    read_latest_capture_summary,
)

router = APIRouter(prefix="/api/facebook-screenshots", tags=["facebook-screenshots"])


class ScreenshotCaptureRequest(BaseModel):
    visible: bool = False
    scrolls: int | None = Field(default=None, ge=1, le=30)
    pause: float | None = Field(default=None, ge=0.5, le=10.0)
    max_links: int | None = Field(default=None, ge=1, le=100)


def _check_token(value: str | None) -> None:
    expected = (os.getenv("N8N_ORCHESTRATION_TOKEN") or "").strip()
    if expected and not secrets.compare_digest(value or "", expected):
        raise HTTPException(status_code=401, detail="Clé d'orchestration invalide.")


@router.get("/status")
def screenshot_status() -> dict:
    """Retourne le dernier résultat sans lancer Chrome."""

    return read_latest_capture_summary()


@router.post("/export-links")
def export_links(
    x_arma_orchestration_key: str | None = Header(default=None),
) -> dict:
    """Reconstruit ``data/fb.txt`` depuis les veilles et alertes retenues."""

    _check_token(x_arma_orchestration_key)
    session = SessionLocal()
    try:
        return export_retained_facebook_links(session)
    finally:
        session.close()


@router.post("/capture")
def capture_links(
    payload: ScreenshotCaptureRequest,
    x_arma_orchestration_key: str | None = Header(default=None),
) -> dict:
    """Lance une capture locale, publique et sans authentification."""

    _check_token(x_arma_orchestration_key)
    return capture_retained_facebook_posts(
        visible=payload.visible,
        scrolls=payload.scrolls,
        pause=payload.pause,
        max_links=payload.max_links,
    )
