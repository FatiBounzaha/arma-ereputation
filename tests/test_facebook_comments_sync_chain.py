"""Vérifie le correctif : un commentaire Facebook collecté doit être trié
puis transformé en alerte, sans étape manuelle supplémentaire.

Avant ce correctif, ``POST /api/facebook/comments/sync`` et
``scripts/sync_apify_facebook_comments.py`` appelaient uniquement
``collect_facebook_comments`` : les commentaires arrivaient bien en base de
données mais n'étaient jamais triés (``_comment_triage`` absent), donc aucune
alerte n'était créée et la section "Commentaires Facebook à traiter" du
portail restait vide.
"""

from __future__ import annotations

import runpy

import backend.api.facebook as facebook_api


def test_sync_comments_endpoint_chains_collect_triage_and_alerts(monkeypatch) -> None:
    call_order: list[str] = []

    monkeypatch.setattr(
        facebook_api,
        "comments_collection_status",
        lambda: {"collection_available": True, "provider": "apify"},
    )

    def fake_collect():
        call_order.append("collect")
        return {"status": "completed", "synced": 3, "comments_created": 3, "comments_updated": 0}

    def fake_triage():
        call_order.append("triage")
        return {"relevant": 2, "reply_recommended": 1}

    def fake_alerts():
        call_order.append("alerts")
        return {"created": 1, "candidates": 1, "failed": 0}

    monkeypatch.setattr(facebook_api, "collect_facebook_comments", fake_collect)
    monkeypatch.setattr(facebook_api, "triage_social_comments", fake_triage)
    monkeypatch.setattr(facebook_api, "generate_alerts_for_negative_mentions", fake_alerts)

    result = facebook_api.sync_comments()

    # Les trois étapes doivent s'enchaîner, dans cet ordre, sans intervention
    # manuelle : sinon un commentaire actionnable reste invisible en alerte.
    assert call_order == ["collect", "triage", "alerts"]
    assert result["synced"] == 3
    assert result["alerts_created"] == 1
    assert result["alerts"]["created"] == 1
    assert result["triage"]["reply_recommended"] == 1


def test_sync_comments_endpoint_still_runs_triage_and_alerts_when_collection_partial(monkeypatch) -> None:
    """Même un run 'no_links' ou partiel ne doit pas empêcher de trier et
    d'alerter les commentaires déjà en base issus d'un run précédent."""

    call_order: list[str] = []
    monkeypatch.setattr(
        facebook_api,
        "comments_collection_status",
        lambda: {"collection_available": True, "provider": "apify"},
    )
    monkeypatch.setattr(
        facebook_api,
        "collect_facebook_comments",
        lambda: call_order.append("collect") or {"status": "no_links", "synced": 0},
    )
    monkeypatch.setattr(
        facebook_api,
        "triage_social_comments",
        lambda: call_order.append("triage") or {"relevant": 0},
    )
    monkeypatch.setattr(
        facebook_api,
        "generate_alerts_for_negative_mentions",
        lambda: call_order.append("alerts") or {"created": 0},
    )

    facebook_api.sync_comments()

    assert call_order == ["collect", "triage", "alerts"]


def test_manual_sync_script_chains_collect_triage_and_alerts(monkeypatch) -> None:
    """Le script scripts/sync_apify_facebook_comments.py doit reproduire la
    même chaîne complète que le pipeline quotidien."""

    call_order: list[str] = []

    import backend.services.facebook_comment_collection_service as collection_service
    import backend.ai.comment_triage.service as triage_service
    import backend.alerts.service as alerts_service

    monkeypatch.setattr(
        collection_service,
        "comments_collection_status",
        lambda: {"collection_available": True, "provider": "apify"},
    )
    monkeypatch.setattr(
        collection_service,
        "collect_facebook_comments",
        lambda: call_order.append("collect") or {"status": "completed", "synced": 5},
    )
    monkeypatch.setattr(
        triage_service,
        "triage_social_comments",
        lambda: call_order.append("triage") or {"relevant": 4, "reply_recommended": 2},
    )
    monkeypatch.setattr(
        alerts_service,
        "generate_alerts_for_negative_mentions",
        lambda: call_order.append("alerts") or {"created": 2},
    )

    exit_code = runpy.run_path(
        "scripts/sync_apify_facebook_comments.py", run_name="not_main"
    )["main"]()

    assert call_order == ["collect", "triage", "alerts"]
    assert exit_code == 0
