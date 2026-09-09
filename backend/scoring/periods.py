from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.alerts.service import alert_is_displayable
from backend.database.models import (
    Alert,
    Mention,
    MentionOrganization,
    ReputationSnapshot,
)
from backend.scoring.formulas import (
    BUSINESS_TIMEZONE,
    FORMULA_VERSION,
    PERIOD_WINDOW_DAYS,
    get_calendar_week_bounds,
    get_period_bounds,
    get_period_datetime_bounds,
)

# Le portail hebdomadaire n'a de sens que sur quelques mois d'historique.
# Cette borne évite de générer des milliers de semaines vides si une mention
# porte une date de publication aberrante (ex. article archivé de 2011).
MAX_PERIOD_OPTIONS = 104

# Une alerte "traitée" est une alerte que l'utilisateur a validée depuis le
# portail : elle reste consultable, elle ne disparaît pas de l'historique.
HANDLED_ALERT_STATUSES = frozenset({"acknowledged", "resolved", "ignored"})


def calendar_week_bounds(day: date) -> tuple[date, date]:
    """Retourne le lundi et le dimanche de la semaine civile contenant `day`."""

    return get_calendar_week_bounds(day)


def is_calendar_week(period_start: date, period_end: date) -> bool:
    """Vrai si la période est bien une semaine civile complète lundi -> dimanche."""

    return (
        period_start.weekday() == 0
        and period_end.weekday() == 6
        and (period_end - period_start).days == 6
    )


def format_period_label(
    period_start: date,
    period_end: date,
    period_type: str = "weekly",
) -> str:
    """Libellé lisible pour le sélecteur de période du portail."""

    window = (
        f"{period_start.strftime('%d/%m/%Y')} → {period_end.strftime('%d/%m/%Y')}"
    )
    if period_type != "weekly":
        return window
    return f"Semaine {period_start.isocalendar().week:02d} · {window}"


def _as_utc(value: datetime) -> datetime:
    """Rend un timestamp comparable même si la base le renvoie sans fuseau."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _publication_date_range(
    session: Session,
    organization_id: int,
) -> tuple[date | None, date | None]:
    """Première et dernière date de publication réelle liée à l'organisation.

    C'est la date de publication (`manual_published_at`/`published_at`) qui
    définit la semaine métier, jamais la date de collecte ARMA.
    """

    effective_date = func.coalesce(Mention.manual_published_at, Mention.published_at)
    row = session.execute(
        select(func.min(effective_date), func.max(effective_date))
        .join(MentionOrganization, MentionOrganization.mention_id == Mention.id)
        .where(MentionOrganization.organization_id == organization_id)
    ).first()

    if row is None or row[0] is None or row[1] is None:
        return None, None

    first_local = _as_utc(row[0]).astimezone(BUSINESS_TIMEZONE).date()
    last_local = _as_utc(row[1]).astimezone(BUSINESS_TIMEZONE).date()
    return first_local, last_local


def _candidate_periods(
    session: Session,
    organization_id: int,
    period_type: str,
    limit: int,
    formula_version: str,
) -> list[tuple[date, date]]:
    """Fenêtres proposées à l'utilisateur, de la plus récente à la plus ancienne.

    Deux sources sont fusionnées :
    1. les snapshots déjà calculés par le pipeline ;
    2. les semaines civiles couvertes par des publications réelles.

    La seconde source est indispensable : une semaine peut contenir des
    commentaires et des alertes sans qu'un score ait été calculé (workflow non
    exécuté ce lundi-là). Sans elle, cette semaine resterait invisible.
    """

    periods: dict[tuple[date, date], None] = {}

    # Pour le portail hebdomadaire, la période la plus récente consultable est
    # TOUJOURS la dernière semaine civile complète (T-1), même si elle ne
    # contient aucune publication ou si le snapshot n'a pas encore été calculé.
    # La semaine en cours n'est jamais proposée : elle est encore incomplète.
    latest_complete_start = None
    latest_complete_end = None
    if period_type == "weekly":
        latest_complete_start, latest_complete_end = get_period_bounds("weekly")
        periods[(latest_complete_start, latest_complete_end)] = None

    for period_start, period_end in session.execute(
        select(ReputationSnapshot.period_start, ReputationSnapshot.period_end)
        .where(
            ReputationSnapshot.organization_id == organization_id,
            ReputationSnapshot.period_type == period_type,
            ReputationSnapshot.formula_version == formula_version,
        )
        .order_by(ReputationSnapshot.period_end.desc())
        .limit(MAX_PERIOD_OPTIONS)
    ).all():
        # Garde-fou : un snapshot hebdomadaire écrit par une ancienne version
        # ou par un appel manuel peut couvrir une fenêtre glissante. Le
        # sélecteur ne doit proposer que des semaines civiles complètes. La
        # semaine civile qui contient ce snapshot reste proposée ci-dessous,
        # via les dates de publication : aucune donnée n'est masquée.
        if period_type == "weekly":
            if not is_calendar_week(period_start, period_end):
                continue
            # Ne jamais exposer la semaine en cours / une semaine future.
            if latest_complete_end is not None and period_end > latest_complete_end:
                continue
        periods[(period_start, period_end)] = None

    if period_type == "weekly":
        first_day, last_day = _publication_date_range(session, organization_id)
        if first_day is not None and last_day is not None:
            oldest_start, _ = calendar_week_bounds(first_day)
            # Une publication de la semaine en cours ne doit pas créer une
            # période encore incomplète dans le sélecteur. On plafonne donc
            # l'historique à la dernière semaine civile complète (T-1).
            capped_last_day = min(last_day, latest_complete_end) if latest_complete_end else last_day
            if first_day <= capped_last_day:
                cursor_start, cursor_end = calendar_week_bounds(capped_last_day)
                for _ in range(MAX_PERIOD_OPTIONS):
                    if cursor_start < oldest_start:
                        break
                    periods[(cursor_start, cursor_end)] = None
                    cursor_start -= timedelta(days=7)
                    cursor_end -= timedelta(days=7)

    ordered = sorted(periods, key=lambda item: (item[1], item[0]), reverse=True)
    return ordered[: max(1, min(limit, MAX_PERIOD_OPTIONS))]


def _alert_counts_by_period(
    session: Session,
    organization_id: int,
    periods: list[tuple[date, date]],
) -> dict[tuple[date, date], dict[str, int]]:
    """Compte les alertes affichables de chaque période, ouvertes et traitées."""

    counts = {
        period: {"open": 0, "handled": 0, "total": 0} for period in periods
    }
    if not periods:
        return counts

    window_start, window_end = get_period_datetime_bounds(
        min(period_start for period_start, _ in periods),
        max(period_end for _, period_end in periods),
    )
    effective_date = func.coalesce(Mention.manual_published_at, Mention.published_at)
    rows = session.execute(
        select(
            Alert.status,
            effective_date,
            Mention.content_type,
            Mention.raw_payload,
        )
        .join(
            MentionOrganization,
            MentionOrganization.id == Alert.mention_organization_id,
        )
        .join(Mention, Mention.id == MentionOrganization.mention_id)
        .where(
            MentionOrganization.organization_id == organization_id,
            effective_date >= window_start,
            effective_date < window_end,
        )
    ).all()

    bounds = [
        (period, *get_period_datetime_bounds(period[0], period[1]))
        for period in periods
    ]
    for status, published_at, content_type, raw_payload in rows:
        if published_at is None:
            continue
        # Même règle que la liste des alertes : un commentaire non pertinent
        # ne doit pas être compté dans le sélecteur de période.
        if not alert_is_displayable(content_type, raw_payload):
            continue
        published = _as_utc(published_at)
        for period, start_dt, end_dt in bounds:
            if start_dt <= published < end_dt:
                bucket = counts[period]
                bucket["total"] += 1
                if status in HANDLED_ALERT_STATUSES:
                    bucket["handled"] += 1
                else:
                    bucket["open"] += 1
                break
    return counts


def list_available_periods(
    session: Session,
    organization_id: int,
    period_type: str = "weekly",
    limit: int = 26,
    formula_version: str = FORMULA_VERSION,
) -> list[dict]:
    """Périodes consultables dans le portail, de la plus récente à la plus ancienne.

    Le pipeline hebdomadaire écrase l'affichage avec la dernière semaine
    calculée. Cette liste permet à l'interface de revenir explicitement sur la
    semaine x-1, x-2, etc. : aucune collecte n'est perdue, elle redevient
    simplement consultable.
    """

    if period_type not in PERIOD_WINDOW_DAYS:
        raise ValueError(
            f"period_type inconnu : '{period_type}'. "
            f"Valeurs acceptées : {list(PERIOD_WINDOW_DAYS)}."
        )

    periods = _candidate_periods(
        session=session,
        organization_id=organization_id,
        period_type=period_type,
        limit=limit,
        formula_version=formula_version,
    )
    if not periods:
        return []

    snapshots = {
        (snapshot.period_start, snapshot.period_end): snapshot
        for snapshot in session.scalars(
            select(ReputationSnapshot).where(
                ReputationSnapshot.organization_id == organization_id,
                ReputationSnapshot.period_type == period_type,
                ReputationSnapshot.formula_version == formula_version,
                ReputationSnapshot.period_end >= periods[-1][1],
            )
        )
    }
    counts = _alert_counts_by_period(session, organization_id, periods)

    entries: list[dict] = []
    for index, (period_start, period_end) in enumerate(periods):
        snapshot = snapshots.get((period_start, period_end))
        bucket = counts.get(
            (period_start, period_end), {"open": 0, "handled": 0, "total": 0}
        )
        has_data = snapshot is not None and snapshot.mention_count > 0
        entries.append(
            {
                "period_start": period_start,
                "period_end": period_end,
                "period_type": period_type,
                "label": format_period_label(period_start, period_end, period_type),
                "has_snapshot": snapshot is not None,
                # 50 est la valeur neutre interne quand aucune mention n'existe :
                # on ne l'expose pas comme une vraie performance.
                "reputation_score": snapshot.reputation_score if has_data else None,
                "mention_count": snapshot.mention_count if snapshot is not None else 0,
                "open_alerts": bucket["open"],
                "handled_alerts": bucket["handled"],
                "total_alerts": bucket["total"],
                "is_latest": index == 0,
            }
        )
    return entries
