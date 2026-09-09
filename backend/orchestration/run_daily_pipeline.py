from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone

from backend.database.connection import SessionLocal
from backend.database.models import PipelineRun
from backend.orchestration.registry import ORCHESTRATION_STEPS

def utc_now() -> datetime:
    """Retourne la date et l'heure actuelles en UTC."""

    return datetime.now(timezone.utc)


def _create_master_run() -> int | None:
    """Crée une trace globale de l'exécution quotidienne.

    Chaque collecteur garde ses propres ``PipelineRun`` détaillés, tandis que
    ce run maître permet au portail de répondre simplement à la question :
    « le pipeline quotidien complet a-t-il tourné et quelles étapes ont échoué ? ».
    """

    session = SessionLocal()
    try:
        run = PipelineRun(
            run_type="daily_pipeline",
            source_id=None,
            watch_query_id=None,
            status="running",
            started_at=utc_now(),
            statistics={"step_count": len(ORCHESTRATION_STEPS), "steps": []},
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        return run.id
    except Exception as error:
        session.rollback()
        print(f"AVERTISSEMENT : trace globale du pipeline indisponible : {error}")
        return None
    finally:
        session.close()


def _finish_master_run(
    pipeline_run_id: int | None,
    results: list[tuple[str, bool, str | None]],
) -> None:
    if pipeline_run_id is None:
        return

    session = SessionLocal()
    try:
        run = session.get(PipelineRun, pipeline_run_id)
        if run is None:
            return
        succeeded = sum(1 for _, ok, _ in results if ok)
        failed = len(results) - succeeded
        run.status = "completed" if failed == 0 else "partial"
        run.finished_at = utc_now()
        run.items_received = len(results)
        run.items_created = succeeded
        run.error_message = (
            "; ".join(f"{name}: {message}" for name, ok, message in results if not ok)[:4000]
            or None
        )
        run.statistics = {
            "step_count": len(results),
            "succeeded": succeeded,
            "failed": failed,
            "steps": [
                {"name": name, "status": "ok" if ok else "failed", "error": message}
                for name, ok, message in results
            ],
        }
        session.commit()
    except Exception as error:
        session.rollback()
        print(f"AVERTISSEMENT : impossible de finaliser la trace globale : {error}")
    finally:
        session.close()


def run_daily_pipeline() -> bool:
    """Exécute la chaîne quotidienne complète et en conserve une trace.

    Une étape en échec n'empêche pas les suivantes de travailler sur les
    données déjà présentes. La fonction retourne ``True`` seulement quand
    toutes les étapes ont réussi, ce qui permet à cron/Task Scheduler de
    détecter un run partiel.
    """

    print("=" * 72)
    print(f"PIPELINE QUOTIDIEN ARMA — démarré à {utc_now().isoformat()}")
    print("=" * 72)

    master_run_id = _create_master_run()
    results: list[tuple[str, bool, str | None]] = []

    for step in ORCHESTRATION_STEPS:
        print(f"\n--- Étape : {step.name} ---")

        try:
            step.run()
            results.append((step.name, True, None))

        except Exception as error:
            print(f"ÉCHEC de l'étape « {step.name} » :")
            traceback.print_exc()
            results.append((step.name, False, str(error)[:800]))

    _finish_master_run(master_run_id, results)

    print("\n" + "=" * 72)
    print("RÉSUMÉ DU PIPELINE QUOTIDIEN")
    print("=" * 72)

    all_succeeded = True

    for name, succeeded, _ in results:
        status = "OK" if succeeded else "ÉCHEC"
        print(f"- {status} : {name}")

        if not succeeded:
            all_succeeded = False

    print(f"\nTerminé à {utc_now().isoformat()}.")

    return all_succeeded


if __name__ == "__main__":
    success = run_daily_pipeline()
    sys.exit(0 if success else 1)
