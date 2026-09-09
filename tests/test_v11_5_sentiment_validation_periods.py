"""V11.5 — Couleur par sentiment, bouton Valider, navigation par semaine."""

from datetime import date
from pathlib import Path

import pytest

from backend.alerts.service import alert_is_displayable
from backend.api.alerts import resolve_sentiment, resolve_status_filter
from backend.api.schemas import AlertResponse, AlertStatusUpdate, PeriodOption
from backend.database.models import Alert, Mention
from backend.scoring.periods import (
    HANDLED_ALERT_STATUSES,
    calendar_week_bounds,
    format_period_label,
)

ROOT = Path(__file__).resolve().parents[1]


def comment(**triage) -> Mention:
    return Mention(
        content_type="social_comment",
        raw_payload={"_comment_triage": triage} if triage else {},
    )


# --------------------------------------------------------------------------
# 1. Couleur pilotée par le sentiment
# --------------------------------------------------------------------------


def test_sentiment_of_a_comment_comes_from_its_own_triage():
    mention = comment(relevant=True, sentiment="negative")
    assert resolve_sentiment(mention, "positive") == ("negative", "comment_triage")


def test_sentiment_of_an_article_comes_from_the_nlp_analysis():
    article = Mention(content_type="news_article", raw_payload={})
    assert resolve_sentiment(article, "positive") == ("positive", "mention_analysis")
    assert resolve_sentiment(article, "neutral") == ("neutral", "mention_analysis")


def test_alert_without_any_sentiment_stays_visually_neutral():
    article = Mention(content_type="news_article", raw_payload={})
    label, source = resolve_sentiment(article, None)
    assert label is None
    assert source == "unknown"


def test_frontend_colours_alerts_by_sentiment_not_by_severity():
    page = (ROOT / "frontend" / "ReputationSocialeARMA.html").read_text(encoding="utf-8")
    assert ".alert.sentiment-negative" in page
    assert ".alert.sentiment-positive" in page
    assert ".alert.sentiment-neutral" in page
    assert ".alert.sentiment-unknown" in page
    # La sévérité ne doit plus décider de la couleur de la carte.
    assert "severityClass" not in page
    # Une légende explique les trois couleurs à l'utilisateur.
    assert "legend-item neg" in page and "legend-item pos" in page


# --------------------------------------------------------------------------
# 2. Bouton « Valider »
# --------------------------------------------------------------------------


def test_status_update_accepts_a_validation_note():
    payload = AlertStatusUpdate(status="resolved", note="Réponse publiée sur Facebook")
    assert payload.status == "resolved"
    assert payload.note == "Réponse publiée sur Facebook"


def test_status_update_stays_compatible_without_note():
    assert AlertStatusUpdate(status="acknowledged").note is None


def test_alert_response_exposes_the_handled_state():
    fields = AlertResponse.model_fields
    for name in ("is_handled", "validated_by", "validated_at", "validation_note"):
        assert name in fields


def test_handled_statuses_cover_every_validated_alert():
    assert HANDLED_ALERT_STATUSES == {"acknowledged", "resolved", "ignored"}


def test_frontend_shows_a_validate_button_and_a_handled_banner():
    page = (ROOT / "frontend" / "ReputationSocialeARMA.html").read_text(encoding="utf-8")
    assert 'data-action="validate-alert"' in page
    assert "Valider — alerte traitée" in page
    assert 'data-action="reopen-alert"' in page
    assert "Alerte traitée" in page
    # Le brouillon de réponse reste accessible sous l'alerte (règle V11.4).
    assert "Voir la réponse proposée" in page
    assert "publié le" in page


# --------------------------------------------------------------------------
# 3. Navigation par semaine
# --------------------------------------------------------------------------


def test_a_validated_alert_remains_reachable_through_the_status_filter():
    # Sans ce filtre, une alerte validée disparaissait définitivement.
    assert resolve_status_filter("all") is None
    assert resolve_status_filter("handled") == ["acknowledged", "ignored", "resolved"]
    assert resolve_status_filter("open") == ["open"]
    assert resolve_status_filter("resolved,acknowledged") == ["resolved", "acknowledged"]


def test_unknown_status_is_rejected_explicitly():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        resolve_status_filter("terminee")
    assert error.value.status_code == 422


def test_calendar_week_runs_from_monday_to_sunday():
    # 2026-08-27 est un jeudi.
    assert calendar_week_bounds(date(2026, 8, 27)) == (
        date(2026, 8, 24),
        date(2026, 8, 30),
    )
    # Un lundi et un dimanche renvoient la même semaine.
    assert calendar_week_bounds(date(2026, 8, 24)) == calendar_week_bounds(
        date(2026, 8, 30)
    )


def test_only_full_calendar_weeks_reach_the_period_selector():
    """Une fenêtre glissante ne doit jamais apparaître dans le sélecteur.

    Un snapshot hebdomadaire écrit par une ancienne version de la formule, ou
    par un appel manuel un jour de semaine, couvrait une fenêtre glissante
    (ex. samedi → vendredi). Le sélecteur affichait alors une période ne
    commençant pas un lundi.
    """

    from backend.scoring.periods import is_calendar_week

    assert is_calendar_week(date(2026, 7, 20), date(2026, 7, 26)) is True
    # Samedi -> vendredi : 7 jours, mais pas une semaine civile.
    assert is_calendar_week(date(2026, 7, 25), date(2026, 7, 31)) is False
    # Lundi -> samedi : incomplète.
    assert is_calendar_week(date(2026, 7, 20), date(2026, 7, 25)) is False
    # Lundi -> dimanche suivant : deux semaines.
    assert is_calendar_week(date(2026, 7, 20), date(2026, 8, 2)) is False


def test_period_label_names_the_week_and_its_dates():
    label = format_period_label(date(2026, 8, 24), date(2026, 8, 30), "weekly")
    assert "24/08/2026" in label and "30/08/2026" in label
    assert label.startswith("Semaine ")


def test_period_option_carries_the_alert_counters_of_the_week():
    option = PeriodOption(
        period_start=date(2026, 8, 24),
        period_end=date(2026, 8, 30),
        period_type="weekly",
        label="Semaine 35",
        has_snapshot=True,
        reputation_score=61.5,
        mention_count=12,
        open_alerts=3,
        handled_alerts=2,
        total_alerts=5,
        is_latest=False,
    )
    assert option.open_alerts + option.handled_alerts == option.total_alerts


def test_both_frontends_let_the_user_go_back_to_a_previous_week():
    for page_name in ("ReputationSocialeARMA.html", "MarketingContenuARMA.html"):
        page = (ROOT / "frontend" / page_name).read_text(encoding="utf-8")
        assert "/api/reputation/periods" in page, page_name
        assert 'id="period-select"' in page, page_name
        assert 'id="period-prev"' in page, page_name
        assert 'id="period-next"' in page, page_name
        # Plus aucune section ne se contente du dernier snapshot calculé.
        assert "period_start=" in page and "period_end=" in page, page_name


def test_marketing_still_documents_the_publication_week_rule():
    page = (ROOT / "frontend" / "MarketingContenuARMA.html").read_text(encoding="utf-8")
    assert "date de publication appartient à la semaine métier" in page


# --------------------------------------------------------------------------
# 4. Règle d'affichage partagée entre la liste et les compteurs
# --------------------------------------------------------------------------


def test_only_relevant_comments_are_displayed_as_alerts():
    assert alert_is_displayable("news_article", None) is True
    assert alert_is_displayable("social_comment", None) is False
    assert alert_is_displayable("social_comment", {"_comment_triage": {}}) is False
    assert (
        alert_is_displayable(
            "social_comment", {"_comment_triage": {"relevant": True, "sentiment": "positive"}}
        )
        is False
    )
    assert (
        alert_is_displayable(
            "social_comment",
            {"_comment_triage": {"relevant": True, "sentiment": "negative"}},
        )
        is True
    )
    assert (
        alert_is_displayable(
            "social_comment",
            {"_comment_triage": {"relevant": True, "reply_recommended": True}},
        )
        is True
    )


def test_validation_details_are_read_from_the_alert_metadata():
    from backend.api.alerts import get_validation_details

    open_alert = Alert(status="open", extra_data={})
    assert get_validation_details(open_alert)["is_handled"] is False

    handled = Alert(
        status="resolved",
        extra_data={"validated_by": "nouhaila", "validation_note": "Réponse envoyée"},
    )
    details = get_validation_details(handled)
    assert details["is_handled"] is True
    assert details["validated_by"] == "nouhaila"
    assert details["validation_note"] == "Réponse envoyée"


# --------------------------------------------------------------------------
# 5. Ordre d'affichage : négatif, puis positif, puis neutre
# --------------------------------------------------------------------------


def test_alerts_are_ordered_negative_then_positive_then_neutral():
    page = (ROOT / "frontend" / "ReputationSocialeARMA.html").read_text(encoding="utf-8")
    assert "const SENTIMENT_ORDER = { negative: 0, positive: 1, neutral: 2, unknown: 3 };" in page
    # Le tri est appliqué aux deux listes : commentaires et autres alertes.
    assert page.count(".sort(bySentimentThenDate)") == 2
    # Un intertitre sépare visuellement les trois groupes.
    assert "sentiment-group" in page
    assert "Alertes négatives" in page


# --------------------------------------------------------------------------
# 6. Cohérence Marketing stricte par date de publication
# --------------------------------------------------------------------------


def test_undated_evidence_is_not_attached_to_a_week_by_generation_date():
    """Une preuve sans published_at ne doit appartenir à aucune semaine.

    La date de génération du brouillon et la date de collecte sont seulement
    des informations de traçabilité.
    """

    from datetime import datetime, timezone

    from backend.api.content import post_evidence_period_filter

    start = datetime(2026, 8, 17, tzinfo=timezone.utc)
    end = datetime(2026, 8, 24, tzinfo=timezone.utc)
    sql = str(post_evidence_period_filter(start, end))

    assert "post_evidence_mentions" in sql
    assert "published_at" in sql
    assert "generated_at" not in sql
    assert "collected_at" not in sql


def test_marketing_strategist_accepts_press_and_public_social_posts_only():
    service = (ROOT / "backend" / "ai" / "content" / "angle_service.py").read_text(encoding="utf-8")
    assert 'Mention.content_type.in_(["news_article", "social_post"])' in service
    assert 'Mention.business_relevance_score >= 0.62' in service
    assert 'Mention.content_type == "news_article"' not in service


def test_post_generator_is_scoped_to_the_requested_week():
    service = (ROOT / "backend" / "ai" / "content" / "post_service.py").read_text(encoding="utf-8")
    assert "period_start=target_period_start" in service
    assert "period_end=target_period_end" in service
    assert "Aucun angle stratégique pour la période" in service
    assert "mention.manual_published_at or mention.published_at" in service
    assert "mention.published_at or mention.collected_at" not in service
