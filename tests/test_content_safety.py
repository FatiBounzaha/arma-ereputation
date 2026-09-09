import pytest

from backend.ai.content.safety import (
    PostSafetyError,
    prepare_and_validate_post_payload,
    sanitize_post_payload,
)


def base_payload(fr_body: str = "ARMA suit les évolutions du secteur.") -> dict:
    return {
        "fr": {"body": fr_body, "hashtags": ["#ARMA"]},
        "ar": {"body": "تتابع أرما تطورات القطاع.", "hashtags": ["#أرما"]},
        "image_prompt": "Photographie urbaine neutre au Maroc, sans logo.",
        "tone": ["factuel"],
    }


def test_sanitizer_removes_anglicism_and_inline_hashtags():
    payload = base_payload("Notre commitment reste prudent. #MarochesDemain")
    cleaned = sanitize_post_payload(payload, "linkedin")
    assert "commitment" not in cleaned["fr"]["body"]
    assert "engagement" in cleaned["fr"]["body"]
    assert "#MarocDeDemain" in cleaned["fr"]["hashtags"]


def test_absolute_unproved_claim_is_rejected():
    payload = base_payload("ARMA garantit une continuité sans interruption.")
    with pytest.raises(PostSafetyError):
        prepare_and_validate_post_payload(
            payload,
            platform="facebook",
            evidence_text="Le secteur de la propreté urbaine évolue.",
            angle_title="Stabilité & performance",
            angle_description="Communication prudente.",
        )


def test_number_not_in_evidence_is_rejected():
    payload = base_payload("ARMA mobilise 320 agents supplémentaires.")
    with pytest.raises(PostSafetyError):
        prepare_and_validate_post_payload(
            payload,
            platform="linkedin",
            evidence_text="ARMA mobilise ses équipes.",
            angle_title="Stabilité",
            angle_description="Rester factuel.",
        )


def test_safe_claim_passes_quality_control():
    cleaned = prepare_and_validate_post_payload(
        base_payload(),
        platform="linkedin",
        evidence_text="Le secteur marocain de la propreté urbaine évolue.",
        angle_title="Signal sectoriel",
        angle_description="Présenter la tendance sans inventer de performance.",
    )
    assert cleaned["fr"]["body"]


def test_technology_attributed_to_arma_without_evidence_is_rejected():
    payload = base_payload("ARMA déploie des capteurs pour optimiser la collecte.")
    with pytest.raises(PostSafetyError):
        prepare_and_validate_post_payload(
            payload,
            platform="linkedin",
            evidence_text="Le secteur étudie de nouvelles solutions.",
            angle_title="Innovation urbaine durable",
            angle_description="Présenter les tendances numériques sans les attribuer à ARMA.",
        )


def test_general_technology_trend_without_arma_attribution_is_allowed():
    payload = base_payload("Les capteurs transforment progressivement le secteur de la collecte.")
    cleaned = prepare_and_validate_post_payload(
        payload,
        platform="linkedin",
        evidence_text="Une étude sectorielle présente l'usage de capteurs dans la collecte.",
        angle_title="Innovation urbaine durable",
        angle_description="Présenter une tendance sectorielle.",
    )
    assert "capteurs" in cleaned["fr"]["body"]
