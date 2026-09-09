import json
import re
from pathlib import Path


def _registry_keys() -> list[str]:
    source = Path("backend/orchestration/registry.py").read_text(encoding="utf-8")
    return re.findall(r'OrchestrationStep\("([a-z0-9_]+)"', source)


def test_orchestration_registry_is_complete_and_unique():
    keys = _registry_keys()
    assert len(keys) == 21
    assert len(keys) == len(set(keys))
    assert keys[0] == "collect_serper_news"
    assert keys[-1] == "generate_posts"


def test_n8n_workflow_contains_every_step_without_secrets():
    path = Path("n8n/workflows/ARMA_Pipeline_Quotidien_n8n.json")
    workflow = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(workflow)

    for key in _registry_keys():
        assert f"/steps/{key}" in serialized

    assert "SERPER_API_KEY" not in serialized
    assert "ANTHROPIC_API_KEY" not in serialized
    assert "sk-ant-" not in serialized
    assert workflow["active"] is False
    assert workflow["settings"]["timezone"] == "Africa/Casablanca"
    assert any(node["name"] == "Préflight API ARMA" for node in workflow["nodes"])
    assert "ARMA — Pipeline quotidien n8n VERSION FINALE" == workflow["name"]


def test_n8n_numbered_nodes_follow_registry_order():
    path = Path("n8n/workflows/ARMA_Pipeline_Quotidien_n8n.json")
    workflow = json.loads(path.read_text(encoding="utf-8"))
    numbered = sorted(
        (node for node in workflow["nodes"] if re.match(r"^\d{2} - ", node["name"])),
        key=lambda node: int(node["name"][:2]),
    )
    urls = [str(node.get("parameters", {}).get("url", "")) for node in numbered]
    keys = _registry_keys()
    assert len(urls) == len(keys)
    for url, key in zip(urls, keys):
        assert f"/steps/{key}" in url
