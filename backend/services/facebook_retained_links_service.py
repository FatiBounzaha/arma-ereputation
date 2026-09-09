from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.services.facebook_url_utils import (
    LEGACY_REGISTRY_PATH,
    REGISTRY_JSON_PATH,
    REGISTRY_PATH,
    canonicalize_facebook_url,
    extract_facebook_publication_urls,
    is_facebook_publication_url,
    is_public_facebook_url,
)

HEADER = """# Liens des publications Facebook à analyser pour les deux POC ARMA.
# Fichier généré automatiquement depuis PostgreSQL.
# Sont retenus :
# - tous les posts Facebook affichés dans la veille Marketing ;
# - tous les posts Facebook associés à une alerte Réputation ;
# - les posts Facebook qualifiés comme candidats métier ;
# - les liens déjà présents dans le registre (sauf désactivation explicite).
# Les commentaires publics de ces posts sont ensuite collectés, classés
# positif / neutre / négatif et intégrés au score de réputation.
# Ne jamais ajouter de token, cookie, mot de passe ou secret dans une URL.
# Un lien par ligne.

"""


def _truthy_env(name: str, default: str = "true") -> bool:
    return (os.getenv(name) or default).strip().casefold() in {"1", "true", "yes", "oui", "on"}


def _origin_for(source_mention: Any, target: Any, alert_ids: list[int]) -> list[str]:
    origins: list[str] = []
    if source_mention.display_in_marketing or target.display_in_marketing:
        origins.append("marketing")
    if alert_ids:
        origins.append("reputation_alert")
    if (
        target.content_type == "social_post"
        and (target.business_relevance_score or 0.0) >= 0.55
        and not target.display_in_marketing
    ):
        origins.append("reputation_candidate")
    return origins


def _existing_registry_links() -> list[str]:
    if not REGISTRY_PATH.exists():
        return []
    links: list[str] = []
    for line in REGISTRY_PATH.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#") or not is_facebook_publication_url(value):
            continue
        canonical = canonicalize_facebook_url(value)
        if canonical not in links:
            links.append(canonical)
    return links


def _mention_urls(source_mention: Any, target: Any) -> list[str]:
    return extract_facebook_publication_urls(
        target.url,
        source_mention.url,
        target.raw_payload,
        source_mention.raw_payload,
        target.route_metadata,
        source_mention.route_metadata,
        target.validation_notes,
        source_mention.validation_notes,
    )


def export_retained_facebook_links(session: Session) -> dict[str, object]:
    """Construit le registre des posts Facebook dont les commentaires comptent.

    La version finale ne dépend plus du nom de la source (« Facebook »,
    « facebook.com », « Serper »...). Elle recherche le permalink réel dans
    l'URL et le payload brut. Une alerte ou une veille visible garde donc son
    post Facebook même si sa qualification technique a changé entre deux runs.
    """

    from backend.database.models import Alert, Mention, MentionOrganization

    rows = session.execute(
        select(Mention, Alert.id)
        .outerjoin(
            MentionOrganization,
            MentionOrganization.mention_id == Mention.id,
        )
        .outerjoin(
            Alert,
            (Alert.mention_organization_id == MentionOrganization.id)
            & (Alert.status.in_(["open", "acknowledged"])),
        )
        .where(
            or_(
                Mention.display_in_marketing.is_(True),
                Alert.id.is_not(None),
                (
                    (Mention.content_type == "social_post")
                    & (Mention.business_relevance_score >= 0.55)
                ),
            )
        )
        .order_by(Mention.collected_at.desc(), Mention.id.desc())
    ).all()

    grouped: dict[str, dict[str, object]] = {}
    for mention, alert_id in rows:
        target = session.get(Mention, mention.parent_mention_id) if mention.parent_mention_id else mention
        if target is None:
            continue

        # Une mention exclue peut rester affichée dans une ancienne alerte.
        # Dans ce cas, le besoin opérationnel (alerte/veille visible) prime afin
        # de ne pas perdre les commentaires du post demandé par l'utilisatrice.
        visible_or_alerted = bool(mention.display_in_marketing or target.display_in_marketing or alert_id)
        if target.validation_status == "excluded" and not visible_or_alerted:
            continue

        urls = _mention_urls(mention, target)
        for clean_url in urls:
            record = grouped.setdefault(
                clean_url,
                {
                    "url": clean_url,
                    "mention_ids": [],
                    "source_mention_ids": [],
                    "alert_ids": [],
                    "origins": [],
                    "title": target.display_title or target.title,
                    "collected_at": target.collected_at.isoformat() if target.collected_at else None,
                },
            )
            if target.id not in record["mention_ids"]:
                record["mention_ids"].append(target.id)
            if mention.id not in record["source_mention_ids"]:
                record["source_mention_ids"].append(mention.id)
            if alert_id is not None and alert_id not in record["alert_ids"]:
                record["alert_ids"].append(alert_id)
            for origin in _origin_for(mention, target, record["alert_ids"]):
                if origin not in record["origins"]:
                    record["origins"].append(origin)

    # Évite qu'un export temporairement vide efface les liens déjà validés.
    # Peut être désactivé avec FACEBOOK_REGISTRY_PRESERVE_EXISTING=false.
    if _truthy_env("FACEBOOK_REGISTRY_PRESERVE_EXISTING", "true"):
        for link in _existing_registry_links():
            grouped.setdefault(
                link,
                {
                    "url": link,
                    "mention_ids": [],
                    "source_mention_ids": [],
                    "alert_ids": [],
                    "origins": ["registry_existing"],
                    "title": None,
                    "collected_at": None,
                },
            )

    records = list(grouped.values())
    links = [str(record["url"]) for record in records]
    now = datetime.now(timezone.utc).isoformat()

    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = HEADER + "\n".join(links) + ("\n" if links else "")
    for path in (REGISTRY_PATH, LEGACY_REGISTRY_PATH):
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    payload = {"generated_at": now, "count": len(records), "records": records}
    temporary_json = REGISTRY_JSON_PATH.with_suffix(".json.tmp")
    temporary_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_json.replace(REGISTRY_JSON_PATH)

    return {
        "path": str(REGISTRY_PATH),
        "legacy_path": str(LEGACY_REGISTRY_PATH),
        "registry_json": str(REGISTRY_JSON_PATH),
        "count": len(links),
        "links": links,
        "records": records,
    }


def export_retained_facebook_links_step() -> dict[str, object]:
    """Adaptateur sans argument pour l'orchestrateur Python et n8n."""

    from backend.database.connection import SessionLocal

    session = SessionLocal()
    try:
        result = export_retained_facebook_links(session)
        print(f"Facebook : {result['count']} lien(s) retenu(s) exporté(s) vers {result['path']}")
        return result
    finally:
        session.close()


__all__ = [
    "export_retained_facebook_links",
    "export_retained_facebook_links_step",
    "is_public_facebook_url",
]
