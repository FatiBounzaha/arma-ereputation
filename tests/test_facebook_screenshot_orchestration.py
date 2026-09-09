import json
from pathlib import Path


def test_facebook_evidence_steps_are_registered_in_source():
    source = Path("backend/orchestration/registry.py").read_text(encoding="utf-8")
    assert '"export_facebook_retained_links"' in source
    assert '"capture_facebook_screenshots"' in source


def test_n8n_workflow_calls_facebook_evidence_steps():
    path = Path("n8n/workflows/ARMA_Pipeline_Quotidien_n8n.json")
    workflow = json.loads(path.read_text(encoding="utf-8"))
    names = {node["name"] for node in workflow["nodes"]}
    assert "09 - Export liens Facebook retenus" in names
    assert "18 - Captures Facebook publiques" in names
    urls = "\n".join(
        str(node.get("parameters", {}).get("url", ""))
        for node in workflow["nodes"]
    )
    assert "/steps/export_facebook_retained_links" in urls
    assert "/steps/capture_facebook_screenshots" in urls
