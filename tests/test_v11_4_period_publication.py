from datetime import date, datetime
import json
from pathlib import Path
from unittest.mock import patch

from backend.scoring.formulas import get_period_bounds, FORMULA_VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_formula_version_uses_publication_date():
    assert FORMULA_VERSION == "v5_calendar_week_publication_date"


def test_explicit_week_remains_seven_days():
    assert get_period_bounds("weekly", date(2026, 8, 30)) == (date(2026, 8, 24), date(2026, 8, 30))


def test_workflow_runs_monday_at_7_casablanca():
    data = json.loads((ROOT / "n8n" / "workflows" / "ARMA_Pipeline_Quotidien_n8n.json").read_text(encoding="utf-8"))
    trigger = next(n for n in data["nodes"] if n["type"] == "n8n-nodes-base.scheduleTrigger")
    interval = trigger["parameters"]["rule"]["interval"][0]
    assert interval["field"] == "weeks"
    assert interval["triggerAtDay"] == [1]
    assert interval["triggerAtHour"] == 7
    assert data["settings"]["timezone"] == "Africa/Casablanca"


def test_frontends_scope_by_publication_period_and_inline_drafts():
    rep = (ROOT / "frontend" / "ReputationSocialeARMA.html").read_text(encoding="utf-8")
    marketing = (ROOT / "frontend" / "MarketingContenuARMA.html").read_text(encoding="utf-8")
    assert "Voir la réponse proposée" in rep
    assert "publié le" in rep
    assert "period_start=" in marketing and "period_end=" in marketing
    assert "date de publication appartient à la semaine métier" in marketing
