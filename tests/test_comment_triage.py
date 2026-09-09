from backend.ai.comment_triage.rules_provider import RulesCommentTriageProvider
from backend.ai.response_drafts.decision import decide_response_action


def test_single_letter_is_noise() -> None:
    result = RulesCommentTriageProvider().classify(comment_text="l")
    assert result.relevant is False
    assert result.reply_recommended is False
    assert "comment_noise" in result.quality_flags


def test_concrete_tanger_complaint_is_actionable() -> None:
    result = RulesCommentTriageProvider().classify(
        comment_text="Si c'est la même société à Tanger, c'est devenu vraiment catastrophique."
    )
    assert result.relevant is True
    assert result.reply_recommended is True
    assert result.category == "operational_complaint"


def test_triage_result_controls_comment_reply_decision() -> None:
    context = {
        "content_type": "social_comment",
        "source_type": "social",
        "source_name": "Facebook",
        "mention_text": "Si c'est la même société à Tanger, c'est catastrophique.",
        "quality_flags": ["comment_relevant", "comment_actionable"],
        "comment_triage": {
            "relevant": True,
            "reply_recommended": True,
            "category": "operational_complaint",
            "reason": "Retour concret sur la qualité du service à Tanger.",
            "needs_more_details": True,
        },
    }
    decision = decide_response_action(context)
    assert decision.action == "public_reply"
    assert decision.reply_eligible is True
    assert decision.ask_for_private_details is True


def test_price_only_comment_is_noise() -> None:
    result = RulesCommentTriageProvider().classify(comment_text="17$")
    assert result.relevant is False
    assert result.category == "noise"


def test_negative_comment_explicitly_about_arma_is_actionable() -> None:
    result = RulesCommentTriageProvider().classify(
        comment_text="ARMA ne ramasse pas les poubelles depuis trois jours dans notre quartier."
    )
    assert result.relevant is True
    assert result.reply_recommended is True
    assert result.sentiment == "negative"


def test_competitor_only_comment_is_not_arma_alert() -> None:
    result = RulesCommentTriageProvider().classify(
        comment_text="Ozone ne ramasse jamais les déchets dans notre rue."
    )
    assert result.relevant is False
    assert result.category == "competitor_only"


def test_comment_defending_arma_is_neutral_without_alert() -> None:
    result = RulesCommentTriageProvider().classify(
        comment_text="ARMA n'y peut rien, la population jette les ordures partout."
    )
    assert result.relevant is True
    assert result.sentiment == "neutral"
    assert result.reply_recommended is False


def test_short_positive_feedback_under_arma_post_counts_in_score() -> None:
    result = RulesCommentTriageProvider().classify(
        comment_text="Bravo",
        parent_title="[Publication rattachée à ARMA] Campagne de propreté",
    )
    assert result.relevant is True
    assert result.sentiment == "positive"


def test_general_negative_arma_comment_is_alert_candidate() -> None:
    result = RulesCommentTriageProvider().classify(
        comment_text="ARMA c'est vraiment lamentable."
    )
    assert result.relevant is True
    assert result.sentiment == "negative"
    assert "negative_alert_candidate" in result.quality_flags


def test_unrelated_social_housing_request_under_arma_post_is_off_topic() -> None:
    result = RulesCommentTriageProvider().classify(
        comment_text=(
            "كنت ضحية الاقصاء من الاستفادة من السكن الاجتماعي بالدار البيضاء "
            "ونطلب المساعدة في طلب استعطاف إلى السيد عامل العمالة"
        ),
        parent_title="[Publication rattachée à ARMA] Service de propreté urbaine",
    )
    assert result.relevant is False
    assert result.category == "off_topic"
    assert result.reply_recommended is False


def test_unrelated_job_request_under_arma_post_is_off_topic() -> None:
    result = RulesCommentTriageProvider().classify(
        comment_text="Je cherche un emploi, merci de m'aider pour le recrutement.",
        parent_title="[Publication rattachée à ARMA] Service de propreté urbaine",
    )
    assert result.relevant is False
    assert result.category == "off_topic"


from backend.ai.comment_triage.claude_provider import result_from_payload


def test_claude_payload_off_topic_can_never_enter_score() -> None:
    result = result_from_payload(
        {
            "relevant": True,
            "reply_recommended": True,
            "category": "off_topic",
            "sentiment": "negative",
            "confidence": 0.91,
            "reason": "Sortie LLM incohérente simulée.",
            "needs_more_details": True,
            "quality_flags": ["comment_relevant", "comment_actionable", "reputation_signal"],
        },
        "test-model",
        "test-version",
    )
    assert result.relevant is False
    assert result.reply_recommended is False
    assert result.sentiment == "neutral"
    assert result.category == "off_topic"
    assert result.needs_more_details is False
    assert "comment_relevant" not in result.quality_flags
    assert "comment_actionable" not in result.quality_flags


def test_claude_payload_noise_can_never_enter_score() -> None:
    result = result_from_payload(
        {
            "relevant": True,
            "reply_recommended": True,
            "category": "noise",
            "sentiment": "positive",
            "confidence": 0.8,
        },
        "test-model",
        "test-version",
    )
    assert result.relevant is False
    assert result.reply_recommended is False
    assert result.sentiment == "neutral"


def test_claude_payload_competitor_only_can_never_enter_score() -> None:
    result = result_from_payload(
        {
            "relevant": True,
            "reply_recommended": False,
            "category": "competitor_only",
            "sentiment": "negative",
            "confidence": 0.85,
        },
        "test-model",
        "test-version",
    )
    assert result.relevant is False
    assert result.sentiment == "neutral"


def test_no_proprete_is_negative_not_positive() -> None:
    result = RulesCommentTriageProvider().classify(
        comment_text="Aucune propreté, il faut voir les ruelles derrière les grands boulevards.",
        parent_title="[Publication rattachée à ARMA] Propreté urbaine",
    )
    assert result.relevant is True
    assert result.sentiment == "negative"


def test_polite_complaint_with_merci_stays_negative() -> None:
    result = RulesCommentTriageProvider().classify(
        comment_text="Merci de faire le nécessaire, la rue est très sale et les déchets restent sur la voie publique.",
        parent_title="[Publication rattachée à ARMA] Service de propreté",
    )
    assert result.sentiment == "negative"


def test_citizen_blame_is_neutral_not_positive() -> None:
    result = RulesCommentTriageProvider().classify(
        comment_text="Le problème vient aussi des citoyens qui jettent les ordures partout; il faut les sensibiliser.",
        parent_title="[Publication rattachée à ARMA] Service de propreté",
    )
    assert result.relevant is True
    assert result.sentiment == "neutral"


def test_proprete_word_alone_is_not_positive() -> None:
    result = RulesCommentTriageProvider().classify(
        comment_text="Il faudrait revoir la propreté partout à Marrakech.",
        parent_title="[Publication rattachée à ARMA] Propreté urbaine",
    )
    assert result.relevant is True
    assert result.sentiment == "neutral"


def test_claude_positive_feedback_never_creates_actionable_reply() -> None:
    result = result_from_payload(
        {
            "relevant": True,
            "reply_recommended": True,
            "category": "positive_feedback",
            "sentiment": "positive",
            "confidence": 0.9,
        },
        "test-model",
        "test-version",
    )
    assert result.relevant is True
    assert result.sentiment == "positive"
    assert result.reply_recommended is False
