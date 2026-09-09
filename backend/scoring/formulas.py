from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

# v5 : période hebdomadaire métier = lundi -> dimanche, calculée le lundi suivant.
# Toutes les mentions, y compris les commentaires sociaux, sont rattachées à la
# période par leur date de publication réelle (manual_published_at/published_at).
FORMULA_VERSION = "v5_calendar_week_publication_date"
BUSINESS_TIMEZONE = ZoneInfo("Africa/Casablanca")

PERIOD_WINDOW_DAYS: dict[str, int] = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
}


def get_calendar_week_bounds(day: date) -> tuple[date, date]:
    """Lundi et dimanche de la semaine civile contenant `day`."""

    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def get_period_bounds(
    period_type: str,
    period_end: date | None = None,
) -> tuple[date, date]:
    """Calcule les bornes incluses d'une période.

    Une période hebdomadaire est toujours une **semaine civile complète**,
    du lundi au dimanche. Les périodes quotidiennes et mensuelles restent des
    fenêtres glissantes se terminant à la date demandée.
    """

    window_days = PERIOD_WINDOW_DAYS.get(period_type)
    if window_days is None:
        raise ValueError(
            f"period_type inconnu : '{period_type}'. "
            f"Valeurs acceptées : {list(PERIOD_WINDOW_DAYS)}."
        )

    if period_end is not None:
        if period_type == "weekly":
            # Une date quelconque est ramenée à la semaine civile qui la
            # contient. Sans cet alignement, un appel du workflow un mercredi
            # produirait une fenêtre glissante mercredi -> mardi, et le
            # portail afficherait une période ne commençant pas un lundi.
            return get_calendar_week_bounds(period_end)
        resolved_end = period_end
        resolved_start = resolved_end - timedelta(days=window_days - 1)
        return resolved_start, resolved_end

    today_local = datetime.now(BUSINESS_TIMEZONE).date()
    if period_type == "weekly":
        # Le reporting hebdomadaire est exécuté le lundi à 07:00 et porte sur
        # la semaine civile complète précédente : lundi 00:00 -> dimanche 23:59.
        current_monday = today_local - timedelta(days=today_local.weekday())
        resolved_end = current_monday - timedelta(days=1)
        resolved_start = resolved_end - timedelta(days=6)
        return resolved_start, resolved_end

    resolved_end = today_local
    resolved_start = resolved_end - timedelta(days=window_days - 1)
    return resolved_start, resolved_end


def get_previous_period_bounds(
    period_type: str,
    current_period_start: date,
) -> tuple[date, date]:
    """Retourne la période adjacente précédente, sans chevauchement."""

    window_days = PERIOD_WINDOW_DAYS.get(period_type)
    if window_days is None:
        raise ValueError(f"period_type inconnu : '{period_type}'.")
    previous_end = current_period_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=window_days - 1)
    return previous_start, previous_end


def get_period_datetime_bounds(
    period_start: date,
    period_end: date,
) -> tuple[datetime, datetime]:
    # Les périodes sont définies en heure métier Maroc puis converties en UTC
    # pour comparer correctement les timestamps timezone-aware stockés en base.
    start_local = datetime.combine(period_start, time.min, tzinfo=BUSINESS_TIMEZONE)
    end_local = datetime.combine(period_end + timedelta(days=1), time.min, tzinfo=BUSINESS_TIMEZONE)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def compute_reputation_score(
    positive_count: int | float,
    neutral_count: int | float,
    negative_count: int | float,
) -> float:
    """Score net de sentiment entre 0 et 100, recentré sur 50."""

    total_count = positive_count + neutral_count + negative_count
    if total_count == 0:
        return 50.0
    net_sentiment = (positive_count - negative_count) / total_count
    return max(0.0, min(100.0, 50.0 + 50.0 * net_sentiment))


def compute_rates(
    positive_count: int,
    neutral_count: int,
    negative_count: int,
) -> tuple[float | None, float | None]:
    total_count = positive_count + neutral_count + negative_count
    if total_count == 0:
        return None, None
    return positive_count / total_count, negative_count / total_count


def build_analyst_summary(
    organization_name: str,
    period_start: date,
    period_end: date,
    mention_count: int,
    positive_rate: float | None,
    negative_rate: float | None,
    reputation_score: float,
    delta_previous_period: float | None,
) -> str:
    if mention_count == 0:
        return (
            f"Aucune mention détectée pour {organization_name} "
            f"entre le {period_start} et le {period_end}."
        )

    summary = (
        f"{mention_count} mention(s) analysée(s) pour {organization_name} "
        f"entre le {period_start} et le {period_end} : "
        f"{positive_rate:.0%} positives, {negative_rate:.0%} négatives. "
        f"Score de réputation : {reputation_score:.1f}/100"
    )
    if delta_previous_period is not None:
        summary += f" ({delta_previous_period:+.1f} pt vs période précédente non chevauchante)."
    else:
        summary += "."
    return summary
