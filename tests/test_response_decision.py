from backend.ai.response_drafts.decision import decide_response_action
from backend.ai.response_drafts.template_provider import TemplateResponseDraftProvider


def test_direct_social_complaint_gets_public_reply() -> None:
    context = {
        "content_type": "social_post",
        "source_type": "social",
        "source_name": "X / Twitter",
        "mention_text": (
            "Cela fait 3 jours que les poubelles ne sont pas ramassées "
            "dans mon quartier. @ARMA_MA pouvez-vous nous expliquer ?"
        ),
        "quality_flags": [],
    }
    decision = decide_response_action(context)
    assert decision.action == "public_reply"
    assert decision.reply_eligible is True


def test_general_arabic_criticism_is_not_treated_as_private_complaint() -> None:
    context = {
        "content_type": "social_post",
        "source_type": "social",
        "source_name": "X / Twitter",
        "mention_text": (
            "يسود غضب كبير وسط مدينة الجديدة عقب فوز شركة أرما بصفقة النظافة"
        ),
        "quality_flags": [],
    }
    decision = decide_response_action(context)
    assert decision.action == "monitor"
    assert decision.reply_eligible is False
    assert decision.place_hint is not None

    result = TemplateResponseDraftProvider().draft(
        organization_name="ARMA",
        alert_reason="Mention négative",
        mention_text=context["mention_text"],
        severity="high",
        context=context,
    )
    assert "lieu exact" not in result.content_by_language["fr"].lower()
    assert "message privé" not in result.content_by_language["fr"].lower()


def test_press_article_requires_escalation() -> None:
    context = {
        "content_type": "news_article",
        "source_type": "online_press",
        "source_name": "Le360 Afrique",
        "title": "ARMA dans le viseur des autorités de Nouakchott",
        "mention_text": "Un avertissement officiel a été adressé à ARMA pour des manquements.",
        "quality_flags": [],
    }
    decision = decide_response_action(context)
    assert decision.action == "internal_escalation"
    assert decision.reply_eligible is False
    assert decision.requires_human_validation is True

    result = TemplateResponseDraftProvider().draft(
        organization_name="ARMA",
        alert_reason="Article négatif",
        mention_text=context["mention_text"],
        severity="high",
        context=context,
    )
    assert "lieu" not in result.content_by_language["fr"].lower()
    assert result.details["action"] == "internal_escalation"


def test_comment_with_known_city_does_not_ask_for_location() -> None:
    context = {
        "content_type": "social_comment",
        "source_type": "social",
        "source_name": "Facebook",
        "mention_text": "À Casablanca centre, les déchets ne sont toujours pas collectés.",
        "city": "Casablanca",
        "quality_flags": [],
    }
    decision = decide_response_action(context)
    assert decision.action == "public_reply"
    assert decision.ask_for_private_details is False

    result = TemplateResponseDraftProvider().draft(
        organization_name="ARMA",
        alert_reason="Commentaire négatif",
        mention_text=context["mention_text"],
        severity="medium",
        context=context,
    )
    assert "lieu exact" not in result.content_by_language["fr"].lower()


def test_high_severity_salary_signal_is_escalated() -> None:
    context = {
        "content_type": "social_post",
        "source_type": "social",
        "source_name": "X / Twitter",
        "mention_text": "Les salaires des employés ARMA accusent un retard important.",
        "severity": "high",
        "quality_flags": [],
    }
    decision = decide_response_action(context)
    assert decision.action == "internal_escalation"
    assert decision.reply_eligible is False
