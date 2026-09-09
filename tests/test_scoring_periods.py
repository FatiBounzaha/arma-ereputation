from datetime import date

from backend.scoring.formulas import get_period_bounds, get_previous_period_bounds


def test_weekly_previous_period_is_adjacent_and_non_overlapping():
    # 2026-07-31 est un vendredi : la période retenue est la semaine civile
    # qui le contient, lundi 27/07 -> dimanche 02/08. Avant l'alignement V11.5,
    # cet appel produisait une fenêtre glissante samedi -> vendredi, visible
    # telle quelle dans le sélecteur de semaines du portail.
    current_start, current_end = get_period_bounds("weekly", date(2026, 7, 31))
    previous_start, previous_end = get_previous_period_bounds("weekly", current_start)
    assert (current_start, current_end) == (date(2026, 7, 27), date(2026, 8, 2))
    assert (previous_start, previous_end) == (date(2026, 7, 20), date(2026, 7, 26))
    assert previous_end < current_start


def test_weekly_bounds_always_run_monday_to_sunday():
    # Quel que soit le jour demandé, la semaine métier reste une semaine civile.
    for day in range(20, 27):
        start, end = get_period_bounds("weekly", date(2026, 7, day))
        assert (start, end) == (date(2026, 7, 20), date(2026, 7, 26))
        assert start.weekday() == 0
        assert end.weekday() == 6


def test_daily_and_monthly_stay_sliding_windows():
    # Seul l'hebdomadaire est aligné sur le calendrier.
    assert get_period_bounds("daily", date(2026, 7, 31)) == (
        date(2026, 7, 31),
        date(2026, 7, 31),
    )
    assert get_period_bounds("monthly", date(2026, 7, 31)) == (
        date(2026, 7, 2),
        date(2026, 7, 31),
    )


def test_default_week_is_last_complete_monday_to_sunday():
    from datetime import datetime, timedelta
    from backend.scoring.formulas import BUSINESS_TIMEZONE

    start, end = get_period_bounds("weekly")
    today = datetime.now(BUSINESS_TIMEZONE).date()
    assert start.weekday() == 0
    assert end.weekday() == 6
    assert (end - start).days == 6
    assert end < today
    assert start == end - timedelta(days=6)
