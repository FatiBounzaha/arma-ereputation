from datetime import datetime, timedelta, timezone

from backend.processing.mention_governance import (
    analyse_comment,
    classify_business,
    clean_display_text,
    freshness,
    route_content,
)


NOW = datetime(2026, 8, 3, tzinfo=timezone.utc)


def test_publication_and_collection_dates_are_independent():
    published = datetime(2025, 11, 27, tzinfo=timezone.utc)
    collected = datetime(2026, 7, 27, 16, 20, tzinfo=timezone.utc)
    assert published != collected
    assert freshness(published, now=collected) == "historical"
    assert freshness(None, now=collected) == "unknown"


def test_freshness_boundaries():
    assert freshness(NOW - timedelta(days=6), now=NOW) == "fresh"
    assert freshness(NOW - timedelta(days=7), now=NOW) == "recent"
    assert freshness(NOW - timedelta(days=30), now=NOW) == "recent"
    assert freshness(NOW - timedelta(days=31), now=NOW) == "context"
    assert freshness(NOW - timedelta(days=91), now=NOW) == "historical"


def test_old_tender_is_not_current_opportunity():
    route = route_content("marche_public", NOW - timedelta(days=200), now=NOW)
    assert route["marketing_allowed"] is False
    assert route["destination"] == "Interne / Historique"


def test_legal_case_is_blocked_from_marketing():
    category = classify_business("Procédure judiciaire", "Accusation de surfacturation présumée")
    route = route_content(category, NOW, now=NOW)
    assert category == "procedure_judiciaire"
    assert route["legal_review_required"] is True
    assert route["public_communication_allowed"] is False


def test_contract_award_requires_official_source():
    blocked = route_content("attribution_contrat", NOW, official_source=False, now=NOW)
    allowed = route_content("attribution_contrat", NOW, official_source=True, now=NOW)
    assert blocked["marketing_allowed"] is False
    assert allowed["marketing_allowed"] is True


def test_title_and_excerpt_cleaning_preserves_raw_text():
    raw = "Déchets déchets  https://example.test/a ... ... service amélioré"
    cleaned = clean_display_text(None, raw, social=True)
    assert "http" not in cleaned["display_excerpt"]
    assert cleaned["raw_text"] == raw
    assert cleaned["display_title_generated"] is True


def test_spam_has_no_reply():
    assert analyse_comment("x")["decision"] == "no_reply"


def test_operational_complaint_can_get_human_validated_draft():
    result = analyse_comment("Les ordures ne sont pas collectées depuis deux jours")
    assert result["decision"] == "public_reply"
    assert result["human_validation_required"] is True


def test_legal_comment_is_escalated_not_replied():
    result = analyse_comment("Une enquête judiciaire pour corruption est ouverte")
    assert result["decision"] == "internal_escalation"
    assert result["reply_required"] is False
