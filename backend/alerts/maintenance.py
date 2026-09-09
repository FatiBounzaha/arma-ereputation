from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from backend.database.connection import SessionLocal
from backend.database.models import Alert, Mention, MentionOrganization


def archive_stale_open_alerts(days: int = 90, apply: bool = False) -> int:
    """Identifie les alertes ouvertes anciennes.

    Par sécurité, le mode par défaut est un dry-run. Utiliser ``--apply`` pour
    les passer au statut ``ignored`` ; aucune mention source n'est supprimée.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    session = SessionLocal()
    try:
        effective_date = func.coalesce(Mention.manual_published_at, Mention.published_at)
        alerts = list(session.scalars(
            select(Alert)
            .join(MentionOrganization, MentionOrganization.id == Alert.mention_organization_id)
            .join(Mention, Mention.id == MentionOrganization.mention_id)
            .where(Alert.status == "open", effective_date < cutoff)
            .order_by(Alert.created_at)
        ))
        print(f"Alertes ouvertes antérieures au {cutoff.date()} : {len(alerts)}")
        if not apply:
            print("Dry-run : aucune modification. Relancez avec --apply pour archiver.")
            return len(alerts)
        now = datetime.now(timezone.utc)
        for alert in alerts:
            alert.status = "ignored"
            alert.resolved_at = now
            alert.extra_data = {**(alert.extra_data or {}), "archived_reason": "stale_open_alert"}
        session.commit()
        print(f"Alertes archivées : {len(alerts)}")
        return len(alerts)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    archive_stale_open_alerts(days=args.days, apply=args.apply)
