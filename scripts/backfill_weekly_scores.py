"""Recalcule le score de réputation des semaines antérieures.

Pourquoi ce script existe
-------------------------
Le pipeline n8n ne calcule que la semaine qui vient de s'écouler. Toutes les
semaines antérieures à la mise à jour V11.4 portent donc une version de formule
obsolète (`v3_weighted_non_overlapping`, `v4_collection_date_social_comments`…),
que le portail ignore volontairement : ces anciens snapshots étaient des fenêtres
glissantes de 7 jours pouvant démarrer n'importe quel jour, et ils rattachaient
les commentaires à leur date de collecte au lieu de leur date de publication.
Les mélanger avec la formule courante produirait un historique incohérent.

Résultat : ces semaines s'affichent « score non calculé » alors que leurs
mentions et leurs alertes sont bien en base.

Ce script rejoue le calcul officiel, semaine civile par semaine civile
(lundi → dimanche), avec la formule courante. Il ne collecte rien et ne modifie
aucune mention : il ne fait qu'écrire des snapshots de score.

Usage
-----
    python -m scripts.backfill_weekly_scores              # 26 dernières semaines
    python -m scripts.backfill_weekly_scores --weeks 12
    python -m scripts.backfill_weekly_scores --force      # recalcule aussi l'existant
    python -m scripts.backfill_weekly_scores --dry-run    # liste sans rien écrire
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select  # noqa: E402

from backend.database.connection import SessionLocal  # noqa: E402
from backend.database.models import Organization, ReputationSnapshot  # noqa: E402
from backend.scoring.formulas import FORMULA_VERSION  # noqa: E402
from backend.scoring.periods import (  # noqa: E402
    calendar_week_bounds,
    _publication_date_range,
)
from backend.scoring.service import compute_reputation_snapshots  # noqa: E402

DEFAULT_WEEKS = 26
OWN_ORGANIZATION_NAME = "ARMA"


def weeks_to_process(session, organization_id: int, limit: int) -> list[tuple[date, date]]:
    """Semaines civiles couvertes par des publications réelles, de la plus ancienne
    à la plus récente."""

    first_day, last_day = _publication_date_range(session, organization_id)
    if first_day is None or last_day is None:
        return []

    oldest_start, _ = calendar_week_bounds(first_day)
    cursor_start, cursor_end = calendar_week_bounds(last_day)

    weeks: list[tuple[date, date]] = []
    while cursor_start >= oldest_start and len(weeks) < limit:
        weeks.append((cursor_start, cursor_end))
        cursor_start -= timedelta(days=7)
        cursor_end -= timedelta(days=7)

    # Du plus ancien au plus récent : chaque semaine peut alors comparer son
    # score à la période précédente, qui vient d'être écrite.
    weeks.reverse()
    return weeks


def has_current_snapshot(session, organization_id: int, week: tuple[date, date]) -> bool:
    return (
        session.scalar(
            select(ReputationSnapshot.id).where(
                ReputationSnapshot.organization_id == organization_id,
                ReputationSnapshot.period_type == "weekly",
                ReputationSnapshot.period_start == week[0],
                ReputationSnapshot.period_end == week[1],
                ReputationSnapshot.formula_version == FORMULA_VERSION,
            )
        )
        is not None
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weeks", type=int, default=DEFAULT_WEEKS)
    parser.add_argument(
        "--force",
        action="store_true",
        help="recalcule aussi les semaines déjà calculées avec la formule courante",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="affiche les semaines concernées sans rien écrire",
    )
    arguments = parser.parse_args()

    session = SessionLocal()
    try:
        organization = session.scalar(
            select(Organization).where(Organization.name == OWN_ORGANIZATION_NAME)
        )
        if organization is None:
            print(f"Organisation '{OWN_ORGANIZATION_NAME}' introuvable.")
            return 1

        weeks = weeks_to_process(
            session, organization.id, max(1, min(arguments.weeks, 104))
        )
        if not weeks:
            print("Aucune publication datée en base : rien à recalculer.")
            return 0

        pending = [
            week
            for week in weeks
            if arguments.force or not has_current_snapshot(session, organization.id, week)
        ]

        print(f"Formule courante : {FORMULA_VERSION}")
        print(f"Semaines examinées : {len(weeks)} — à calculer : {len(pending)}")
        for week in pending:
            print(f"  {week[0]} -> {week[1]}")

        if arguments.dry_run:
            print("\n--dry-run : aucune écriture effectuée.")
            return 0
        if not pending:
            print("\nToutes les semaines sont déjà calculées avec la formule courante.")
            return 0
    finally:
        session.close()

    failures = 0
    for period_start, period_end in pending:
        print(f"\n=== Semaine {period_start} -> {period_end} ===")
        try:
            # include_previous_period=False : chaque semaine est traitée
            # explicitement par la boucle, inutile de réécrire la précédente.
            compute_reputation_snapshots(
                period_type="weekly",
                period_end=period_end,
                include_previous_period=False,
            )
        except Exception as error:  # noqa: BLE001 - une semaine en échec ne bloque pas les autres
            failures += 1
            print(f"Échec sur {period_start} -> {period_end} : {error}")

    print(f"\nTerminé. {len(pending) - failures} semaine(s) calculée(s), {failures} échec(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
