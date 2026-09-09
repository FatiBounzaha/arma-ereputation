from __future__ import annotations

import os
import secrets
import time
import traceback
from datetime import timedelta
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import select
from pydantic import BaseModel

from backend.database.connection import SessionLocal
from backend.database.models import PipelineRun
from backend.orchestration.registry import ORCHESTRATION_STEPS, STEP_BY_KEY

router = APIRouter(prefix="/api/orchestration", tags=["orchestration"])


class StartRunRequest(BaseModel):
    trigger: str = "n8n"
    workflow: str | None = None
    execution_id: str | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _check_token(x_arma_orchestration_key: str | None) -> None:
    """Protège les routes n8n quand un token est configuré.

    En local, la variable peut rester vide pour simplifier le POC. Dès que
    l'API est exposée hors de la machine, définir N8N_ORCHESTRATION_TOKEN et
    envoyer la même valeur dans l'en-tête X-ARMA-Orchestration-Key.
    """

    expected = (os.getenv("N8N_ORCHESTRATION_TOKEN") or "").strip()
    provided = x_arma_orchestration_key or ""
    if expected and not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Clé d'orchestration invalide.")


def _normalise_statistics(run: PipelineRun) -> dict[str, Any]:
    stats = dict(run.statistics or {})
    stats.setdefault("step_count", len(ORCHESTRATION_STEPS))
    stats.setdefault("steps", [])
    return stats


@router.get("/steps")
def list_orchestration_steps() -> dict[str, Any]:
    return {
        "count": len(ORCHESTRATION_STEPS),
        "steps": [
            {"key": step.key, "name": step.name, "phase": step.phase}
            for step in ORCHESTRATION_STEPS
        ],
    }


@router.post("/runs/start")
def start_orchestration_run(
    payload: StartRunRequest | None = None,
    x_arma_orchestration_key: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_token(x_arma_orchestration_key)
    payload = payload or StartRunRequest()
    session = SessionLocal()
    try:
        # Empêche un double lancement par le déclencheur planifié et un clic
        # manuel. Un ancien run sans fin est considéré comme obsolète après 6 h.
        active_cutoff = utc_now() - timedelta(hours=6)
        active_run = session.scalar(
            select(PipelineRun)
            .where(
                PipelineRun.run_type == "n8n_daily_pipeline",
                PipelineRun.status.in_(["running", "partial"]),
                PipelineRun.started_at >= active_cutoff,
                PipelineRun.finished_at.is_(None),
            )
            .order_by(PipelineRun.started_at.desc())
            .limit(1)
        )
        if active_run is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Un pipeline n8n est déjà en cours.",
                    "run_id": active_run.id,
                    "started_at": active_run.started_at.isoformat(),
                },
            )

        run = PipelineRun(
            run_type="n8n_daily_pipeline",
            source_id=None,
            watch_query_id=None,
            status="running",
            started_at=utc_now(),
            statistics={
                "orchestrator": "n8n",
                "trigger": payload.trigger,
                "workflow": payload.workflow,
                "execution_id": payload.execution_id,
                "step_count": len(ORCHESTRATION_STEPS),
                "steps": [],
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        return {
            "ok": True,
            "run_id": run.id,
            "status": run.status,
            "started_at": run.started_at,
            "step_count": len(ORCHESTRATION_STEPS),
        }
    finally:
        session.close()


@router.post("/runs/{run_id}/steps/{step_key}")
def run_orchestration_step(
    run_id: int,
    step_key: str,
    x_arma_orchestration_key: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_token(x_arma_orchestration_key)
    step = STEP_BY_KEY.get(step_key)
    if step is None:
        raise HTTPException(status_code=404, detail=f"Étape inconnue : {step_key}")

    session = SessionLocal()
    run = session.get(PipelineRun, run_id)
    if run is None or run.run_type != "n8n_daily_pipeline":
        session.close()
        raise HTTPException(status_code=404, detail="Exécution n8n introuvable.")
    if run.status not in {"running", "partial"}:
        session.close()
        raise HTTPException(status_code=409, detail=f"Exécution déjà terminée : {run.status}")
    session.close()

    started = utc_now()
    perf_started = time.perf_counter()
    ok = True
    error_message: str | None = None
    step_result: Any = None

    try:
        step_result = step.run()
    except Exception as error:  # Le workflow continue pour produire un run partiel.
        ok = False
        error_message = str(error)[:1200]
        traceback.print_exc()

    finished = utc_now()
    duration_seconds = round(time.perf_counter() - perf_started, 3)

    session = SessionLocal()
    try:
        run = session.get(PipelineRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Exécution n8n introuvable.")
        stats = _normalise_statistics(run)
        existing = [item for item in stats["steps"] if item.get("key") != step.key]
        existing.append(
            {
                "key": step.key,
                "name": step.name,
                "phase": step.phase,
                "status": "ok" if ok else "failed",
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "duration_seconds": duration_seconds,
                "error": error_message,
                "result": step_result if isinstance(step_result, (dict, list, str, int, float, bool)) or step_result is None else str(step_result),
            }
        )
        # Conserver l'ordre métier dans la trace, même si n8n relance une étape.
        order = {item.key: index for index, item in enumerate(ORCHESTRATION_STEPS)}
        existing.sort(key=lambda item: order.get(str(item.get("key")), 999))
        stats["steps"] = existing
        stats["succeeded"] = sum(item.get("status") == "ok" for item in existing)
        stats["failed"] = sum(item.get("status") == "failed" for item in existing)
        run.statistics = stats
        run.items_received = len(existing)
        run.items_created = int(stats["succeeded"])
        run.status = "running" if ok else "partial"
        run.error_message = "; ".join(
            f"{item.get('name')}: {item.get('error')}"
            for item in existing
            if item.get("status") == "failed"
        )[:4000] or None
        session.commit()
    finally:
        session.close()

    return {
        "ok": ok,
        "run_id": run_id,
        "step": {"key": step.key, "name": step.name, "phase": step.phase},
        "started_at": started,
        "finished_at": finished,
        "duration_seconds": duration_seconds,
        "error": error_message,
        "result": step_result if isinstance(step_result, (dict, list, str, int, float, bool)) or step_result is None else str(step_result),
    }


@router.post("/runs/{run_id}/finish")
def finish_orchestration_run(
    run_id: int,
    x_arma_orchestration_key: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_token(x_arma_orchestration_key)
    session = SessionLocal()
    try:
        run = session.get(PipelineRun, run_id)
        if run is None or run.run_type != "n8n_daily_pipeline":
            raise HTTPException(status_code=404, detail="Exécution n8n introuvable.")
        stats = _normalise_statistics(run)
        succeeded = int(stats.get("succeeded", 0))
        failed = int(stats.get("failed", 0))
        executed = len(stats.get("steps", []))
        missing = max(0, len(ORCHESTRATION_STEPS) - executed)
        if missing:
            stats["missing"] = missing
        run.status = "completed" if failed == 0 and missing == 0 else "partial"
        run.finished_at = utc_now()
        run.statistics = stats
        run.items_received = executed
        run.items_created = succeeded
        session.commit()
        session.refresh(run)
        # Couvre aussi les collectes executees comme etapes du workflow n8n.
        from backend.services.facebook_retained_links_service import (
            export_retained_facebook_links,
        )

        facebook_registry = export_retained_facebook_links(session)
        return {
            "ok": run.status == "completed",
            "run_id": run.id,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "succeeded": succeeded,
            "failed": failed,
            "missing": missing,
            "steps": stats.get("steps", []),
            "facebook_retained_links": facebook_registry["count"],
        }
    finally:
        session.close()


@router.get("/runs/{run_id}")
def read_orchestration_run(
    run_id: int,
    x_arma_orchestration_key: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_token(x_arma_orchestration_key)
    session = SessionLocal()
    try:
        run = session.get(PipelineRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Exécution introuvable.")
        return {
            "id": run.id,
            "type": run.run_type,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "error_message": run.error_message,
            "statistics": run.statistics,
        }
    finally:
        session.close()
