from pathlib import Path

from backend.processing.mention_governance import (
    clean_source_name,
    confidence_level,
    geographic_scope,
    specific_business_insight,
)


ROOT = Path(__file__).resolve().parents[1]


def test_geography_distinguishes_morocco_international_and_unknown():
    assert geographic_scope("Contrat à Casablanca")["scope"] == "morocco"
    assert geographic_scope("Waste management", country="France")["scope"] == "international"
    assert geographic_scope("Waste management")["scope"] == "unknown"


def test_numeric_source_identifier_is_not_exposed():
    assert clean_source_name("source-123456789", "Serper", "https://example.ma/article") == "example.ma"


def test_business_reading_is_specific_to_legal_content():
    insight = specific_business_insight(
        "procedure_judiciaire", "Affaire concernant un concurrent", "", geographic_scope("Bouznika"), "fresh"
    )
    assert "validation juridique" in insight
    assert "Bouznika" not in insight  # the label stays Morocco; no invented city claim


def test_score_confidence_depends_on_sample_size():
    assert confidence_level(2)["level"] == "low"
    assert confidence_level(10)["level"] == "medium"
    assert confidence_level(25)["level"] == "high"


def test_frontends_expose_priority_controls_and_traceability():
    marketing = (ROOT / "frontend" / "MarketingContenuARMA.html").read_text(encoding="utf-8")
    reputation = (ROOT / "frontend" / "ReputationSocialeARMA.html").read_text(encoding="utf-8")
    assert "geography-filter" in marketing
    assert "Vérifier / corriger" in marketing
    assert "Sources utilisées pour ce brouillon" in marketing
    assert "Modèle LLM" in marketing
    assert "/api/facebook/comments?limit=100" not in reputation
    assert "/api/facebook/comments/summary" in reputation
    assert "commentaires négatifs apparaissent individuellement" in reputation
    assert "Voir la réponse proposée" in reputation
    assert "publiées sur la période" in reputation
    assert "Événement regroupé" in reputation
    assert "Niveau de confiance" in reputation
