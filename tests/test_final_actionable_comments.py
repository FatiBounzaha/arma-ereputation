from types import SimpleNamespace

from backend.ai.comment_triage.rules_provider import RulesCommentTriageProvider
from backend.alerts.service import is_alertable_analysis
from backend.services.facebook_url_utils import extract_facebook_post_identifiers


def test_service_suggestion_under_arma_post_is_actionable_neutral() -> None:
    result = RulesCommentTriageProvider().classify(
        comment_text="Il faut nettoyer avec de l'eau et du détergent.",
        parent_title="[Publication rattachée à ARMA] Service de propreté",
    )
    assert result.relevant is True
    assert result.sentiment == "neutral"
    assert result.reply_recommended is True
    assert result.category == "suggestion"


def test_negative_tanger_comment_under_arma_post_is_alertable() -> None:
    result = RulesCommentTriageProvider().classify(
        comment_text="Si c'est la même société à Tanger, c'est devenu vraiment catastrophique.",
        parent_title="[Publication rattachée à ARMA] Service de propreté",
    )
    mention = SimpleNamespace(
        content_type="social_comment",
        raw_payload={"_comment_triage": result.to_dict()},
    )
    analysis = SimpleNamespace(sentiment_label=result.sentiment)
    assert is_alertable_analysis(mention, analysis) is True


def test_neutral_actionable_comment_is_alertable() -> None:
    mention = SimpleNamespace(
        content_type="social_comment",
        raw_payload={
            "_comment_triage": {
                "relevant": True,
                "sentiment": "neutral",
                "reply_recommended": True,
            }
        },
    )
    analysis = SimpleNamespace(sentiment_label="neutral")
    assert is_alertable_analysis(mention, analysis) is True


def test_facebook_post_id_is_extracted_from_slug_url() -> None:
    url = (
        "https://www.facebook.com/Le360.ma/posts/"
        "trois-semaines-apres-une-passation/1478372787652842"
    )
    identifiers = extract_facebook_post_identifiers(url)
    assert "1478372787652842" in identifiers
