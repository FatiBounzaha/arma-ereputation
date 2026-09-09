from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from backend.api.alerts import router as alerts_router
from backend.api.content import router as content_router
from backend.api.reputation import router as reputation_router
from backend.api.quality import router as quality_router
from backend.api.orchestration import router as orchestration_router
from backend.api.facebook import router as facebook_router
from backend.api.facebook_screenshots import router as facebook_screenshots_router
from backend.database.connection import engine

app = FastAPI(
    title="ARMA Marketing Intelligence API",
    description="API de veille marketing et d'e-réputation d'ARMA",
    version="1.0.3",
)

allowed_origins = [
    item.strip()
    for item in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5500,http://127.0.0.1:5500",
    ).split(",")
    if item.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(reputation_router)
app.include_router(alerts_router)
app.include_router(content_router)
app.include_router(quality_router)
app.include_router(orchestration_router)
app.include_router(facebook_router)
app.include_router(facebook_screenshots_router)

SCREENSHOT_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "facebook_screenshots"
SCREENSHOT_DIRECTORY.mkdir(parents=True, exist_ok=True)
app.mount(
    "/artifacts/facebook-screenshots",
    StaticFiles(directory=str(SCREENSHOT_DIRECTORY)),
    name="facebook-screenshots",
)


@app.get("/")
def home() -> dict[str, str]:
    return {"message": "Bienvenue dans l'API ARMA", "version": "1.0.3"}


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "ARMA Marketing Intelligence API"}


@app.get("/db-health")
def database_health_check() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception:
        # Ne pas exposer l'URL ou les détails PostgreSQL dans une API publique.
        return {"status": "error", "database": "not connected"}
