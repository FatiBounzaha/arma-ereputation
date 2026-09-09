from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.services.facebook_url_utils import (
    PROJECT_ROOT,
    REGISTRY_JSON_PATH,
    REGISTRY_PATH,
    canonicalize_facebook_url,
    is_facebook_publication_url,
)

SCREENSHOT_ROOT = PROJECT_ROOT / "data" / "facebook_screenshots"
LATEST_SUMMARY_PATH = SCREENSHOT_ROOT / "latest_run.json"


def _bool_env(name: str, default: bool) -> bool:
    value = (os.getenv(name) or str(default)).strip().lower()
    return value in {"1", "true", "yes", "oui", "on"}


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def _float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def load_facebook_urls(path: Path = REGISTRY_PATH) -> list[str]:
    if not path.exists():
        return []
    urls: list[str] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = raw_line.strip()
        if not value or value.startswith("#"):
            continue
        if not is_facebook_publication_url(value):
            print(f"Lien Facebook ignoré ligne {line_number} : format non pris en charge.")
            continue
        canonical = canonicalize_facebook_url(value)
        if canonical not in urls:
            urls.append(canonical)
    return urls


def _load_registry_metadata() -> dict[str, dict[str, Any]]:
    if not REGISTRY_JSON_PATH.exists():
        return {}
    try:
        payload = json.loads(REGISTRY_JSON_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(item.get("url")): item
        for item in payload.get("records", [])
        if isinstance(item, dict) and item.get("url")
    }


def build_driver(visible: bool):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    if not visible:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1440,1000")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--lang=fr-FR")
    options.add_argument("--no-first-run")
    options.add_argument("--disable-dev-shm-usage")
    options.page_load_strategy = "eager"
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(45)
    return driver


def _page_status(driver) -> tuple[str, list[str]]:
    warnings: list[str] = []
    try:
        title = (driver.title or "").casefold()
        current_url = (driver.current_url or "").casefold()
        text = (driver.find_element("tag name", "body").text or "")[:6000].casefold()
    except Exception:
        return "unknown", ["Impossible d'inspecter le contenu de la page."]

    login_markers = (
        "connectez-vous à facebook",
        "log in to facebook",
        "adresse e-mail ou numéro de tél",
        "email or phone",
    )
    unavailable_markers = (
        "ce contenu n’est pas disponible",
        "this content isn't available",
        "page introuvable",
    )
    if "login" in current_url or any(marker in text for marker in login_markers):
        warnings.append("Facebook demande une connexion ; les captures peuvent montrer le mur de connexion.")
        return "login_required", warnings
    if any(marker in text for marker in unavailable_markers) or "page not found" in title:
        warnings.append("La publication semble indisponible ou non publique.")
        return "unavailable", warnings
    return "captured_public_page", warnings


def _public_artifact_url(path: Path) -> str:
    try:
        relative = path.relative_to(SCREENSHOT_ROOT).as_posix()
    except ValueError:
        return str(path)
    return f"/artifacts/facebook-screenshots/{relative}"


def capture_url(driver, url: str, run_directory: Path, scrolls: int, pause: float, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    import hashlib
    from selenium.common.exceptions import TimeoutException, WebDriverException

    identifier = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    target = run_directory / identifier
    target.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc)
    warnings: list[str] = []

    try:
        driver.get(url)
    except TimeoutException:
        warnings.append("Chargement partiel après 45 secondes.")
    time.sleep(max(1.0, pause))

    final_url = driver.current_url
    captures: list[Path] = []
    previous_height = -1
    previous_y = -1

    for index in range(max(1, min(scrolls, 30))):
        screenshot = target / f"viewport_{index + 1:02d}.png"
        try:
            if driver.save_screenshot(str(screenshot)):
                captures.append(screenshot)
        except WebDriverException as error:
            warnings.append(f"Échec capture {index + 1}: {str(error)[:180]}")
            break

        metrics = driver.execute_script(
            "return {h: document.documentElement.scrollHeight || 0, y: window.scrollY || 0, v: window.innerHeight || 0};"
        ) or {}
        height = int(metrics.get("h") or 0)
        current_y = int(metrics.get("y") or 0)
        viewport = int(metrics.get("v") or 0)
        at_bottom = current_y + viewport >= max(0, height - 5)
        if index >= 2 and (at_bottom or (height == previous_height and current_y == previous_y)):
            break
        previous_height, previous_y = height, current_y
        driver.execute_script("window.scrollBy(0, Math.floor(window.innerHeight * 0.85));")
        time.sleep(max(0.75, pause))

    page_status, page_warnings = _page_status(driver)
    warnings.extend(page_warnings)
    finished_at = datetime.now(timezone.utc)
    result = {
        "input_url": url,
        "final_url": final_url,
        "status": page_status if captures else "failed",
        "captured_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "captures_count": len(captures),
        "screenshots": [_public_artifact_url(path) for path in captures],
        "warnings": warnings,
        "metadata": metadata or {},
    }
    (target / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (target / "manifest.txt").write_text(
        "\n".join(
            [
                f"input_url={url}",
                f"final_url={final_url}",
                f"captured_at={finished_at.isoformat()}",
                f"status={result['status']}",
                "platform=facebook",
                "method=selenium_public_facebook_screenshot",
                "authentication=false",
                f"captures_count={len(captures)}",
                *[f"screenshot={item}" for item in result["screenshots"]],
                *[f"warning={item}" for item in warnings],
            ]
        ),
        encoding="utf-8",
    )
    return result


def _cleanup_old_runs(keep_runs: int) -> None:
    if not SCREENSHOT_ROOT.exists():
        return
    runs = sorted(
        [path for path in SCREENSHOT_ROOT.iterdir() if path.is_dir() and path.name.startswith("run_")],
        key=lambda path: path.name,
        reverse=True,
    )
    for old in runs[keep_runs:]:
        shutil.rmtree(old, ignore_errors=True)


def capture_retained_facebook_posts(
    links_path: Path = REGISTRY_PATH,
    output_root: Path = SCREENSHOT_ROOT,
    *,
    visible: bool | None = None,
    scrolls: int | None = None,
    pause: float | None = None,
    max_links: int | None = None,
) -> dict[str, Any]:
    """Capture les posts de ``fb.txt`` sans authentification ni contournement."""

    SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    enabled = _bool_env("FACEBOOK_SCREENSHOT_ENABLED", False)
    if not enabled:
        return {"status": "disabled", "count": 0, "captures": 0, "results": []}

    visible = _bool_env("FACEBOOK_SCREENSHOT_VISIBLE", False) if visible is None else visible
    scrolls = _int_env("FACEBOOK_SCREENSHOT_SCROLLS", 8, 1, 30) if scrolls is None else max(1, min(scrolls, 30))
    pause = _float_env("FACEBOOK_SCREENSHOT_PAUSE_SECONDS", 2.0, 0.5, 10.0) if pause is None else max(0.5, min(pause, 10.0))
    max_links = _int_env("FACEBOOK_SCREENSHOT_MAX_LINKS", 20, 1, 100) if max_links is None else max(1, min(max_links, 100))
    keep_runs = _int_env("FACEBOOK_SCREENSHOT_KEEP_RUNS", 10, 1, 100)

    urls = load_facebook_urls(links_path)[:max_links]
    if not urls:
        summary = {
            "status": "no_links",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "count": 0,
            "captures": 0,
            "results": [],
            "links_path": str(links_path),
        }
        output_root.mkdir(parents=True, exist_ok=True)
        LATEST_SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary

    run_name = "run_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    run_directory = output_root / run_name
    run_directory.mkdir(parents=True, exist_ok=True)
    metadata_by_url = _load_registry_metadata()
    results: list[dict[str, Any]] = []
    driver = None
    started_at = datetime.now(timezone.utc)

    try:
        driver = build_driver(visible)
        for url in urls:
            try:
                results.append(
                    capture_url(
                        driver,
                        url,
                        run_directory,
                        scrolls,
                        pause,
                        metadata_by_url.get(url),
                    )
                )
            except Exception as error:
                results.append(
                    {
                        "input_url": url,
                        "final_url": None,
                        "status": "failed",
                        "captured_at": datetime.now(timezone.utc).isoformat(),
                        "duration_seconds": 0,
                        "captures_count": 0,
                        "screenshots": [],
                        "warnings": [str(error)[:500]],
                        "metadata": metadata_by_url.get(url, {}),
                    }
                )
    except Exception as error:
        summary = {
            "status": "unavailable",
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "count": len(urls),
            "captures": 0,
            "results": [],
            "links_path": str(links_path),
            "error": f"Selenium/Chrome indisponible : {str(error)[:500]}",
        }
        LATEST_SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

    finished_at = datetime.now(timezone.utc)
    total_captures = sum(int(item.get("captures_count") or 0) for item in results)
    failed = sum(item.get("status") == "failed" for item in results)
    summary = {
        "status": "completed" if failed == 0 else "partial",
        "run": run_name,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "count": len(urls),
        "captures": total_captures,
        "failed": failed,
        "links_path": str(links_path),
        "output_directory": str(run_directory),
        "results": results,
    }
    (run_directory / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    LATEST_SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _cleanup_old_runs(keep_runs)
    print(f"Facebook screenshots : {len(urls)} post(s), {total_captures} capture(s), statut {summary['status']}.")
    return summary


def capture_retained_facebook_posts_step() -> dict[str, Any]:
    """Étape non bloquante pour l'orchestration quotidienne."""

    result = capture_retained_facebook_posts()
    if result.get("status") in {"unavailable", "disabled", "no_links"}:
        print(f"AVERTISSEMENT capture Facebook : {result.get('status')} — {result.get('error', '')}")
    return result


def read_latest_capture_summary() -> dict[str, Any]:
    if not LATEST_SUMMARY_PATH.exists():
        return {"status": "not_run", "count": 0, "captures": 0, "results": []}
    try:
        return json.loads(LATEST_SUMMARY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "invalid_summary", "count": 0, "captures": 0, "results": []}


def find_latest_capture_for_url(url: str | None) -> dict[str, Any] | None:
    """Retrouve les captures du dernier run pour une URL Facebook donnée."""

    if not url or not is_facebook_publication_url(url):
        return None
    canonical = canonicalize_facebook_url(url)
    summary = read_latest_capture_summary()
    for item in summary.get("results", []):
        if not isinstance(item, dict):
            continue
        candidates = [item.get("input_url"), item.get("final_url")]
        for candidate in candidates:
            if candidate and is_facebook_publication_url(candidate):
                if canonicalize_facebook_url(candidate) == canonical:
                    return {
                        "status": item.get("status"),
                        "captured_at": item.get("captured_at"),
                        "captures_count": int(item.get("captures_count") or 0),
                        "screenshots": list(item.get("screenshots") or []),
                        "warnings": list(item.get("warnings") or []),
                    }
    return None
