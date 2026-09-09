from types import SimpleNamespace

from backend.alerts.service import classify_risk, determine_severity


def mention(text: str, content_type: str = "social_post"):
    return SimpleNamespace(
        title=None,
        clean_text=None,
        raw_text=text,
        engagement={},
        content_type=content_type,
    )


def test_salary_delay_is_always_high_risk():
    item = mention("تأخير في صرف أجور عمال النظافة بشركة أرما في طنجة")
    assert "payroll_hr" in classify_risk(item)
    assert determine_severity(0.40, item) == "high"


def test_institutional_warning_article_is_high_risk():
    item = mention(
        "Les autorités ont adressé un avertissement officiel à ARMA.",
        content_type="news_article",
    )
    assert "legal_institutional" in classify_risk(item)
    assert determine_severity(0.40, item) == "high"


def test_low_confidence_general_criticism_can_stay_low():
    item = mention("Je ne suis pas satisfait.")
    assert determine_severity(0.30, item) == "low"
