from pathlib import Path


def test_frontends_present_n8n_as_primary_orchestrator():
    for filename in ("MarketingContenuARMA.html", "ReputationSocialeARMA.html"):
        text = Path("frontend", filename).read_text(encoding="utf-8")
        assert "workflow n8n" in text
        assert "backend.orchestration.run_daily_pipeline" not in text


def test_mark_analyzed_uses_acknowledged_status():
    text = Path("frontend/ReputationSocialeARMA.html").read_text(encoding="utf-8")
    assert "isReply ? 'resolved' : 'acknowledged'" in text
