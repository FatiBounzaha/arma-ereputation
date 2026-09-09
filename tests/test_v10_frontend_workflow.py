import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_reputation_frontend_never_marks_sent_without_api_confirmation():
    html = (ROOT / "frontend" / "ReputationSocialeARMA.html").read_text(encoding="utf-8")
    assert "/api/facebook/comments/" in html
    assert "result.status === 'sent'" in html
    assert "human_approved: true" in html


def test_n8n_has_non_blocking_facebook_status_branch():
    payload = json.loads((ROOT / "n8n" / "workflows" / "ARMA_Pipeline_Quotidien_n8n.json").read_text(encoding="utf-8"))
    flat = json.dumps(payload, ensure_ascii=False)
    assert "/steps/collect_facebook_comments" in flat
    assert "/api/facebook/comments/sync" not in flat
    assert "/reply" not in flat


def test_reputation_frontend_integrates_retained_comments_into_alerts():
    html = (ROOT / "frontend" / "ReputationSocialeARMA.html").read_text(encoding="utf-8")
    assert "/api/facebook/comments?limit=100" not in html
    assert "alerts.map(alert =>" in html
    assert "Envoyer sur Facebook" in html
    assert "textarea class=\"response-text\"" in html
