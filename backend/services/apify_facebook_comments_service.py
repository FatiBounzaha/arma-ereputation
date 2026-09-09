from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.database.connection import SessionLocal
from backend.database.models import Alert, Mention, MentionAnalysis, MentionOrganization, Organization, PipelineRun, Source
from backend.services.facebook_url_utils import (
    REGISTRY_JSON_PATH,
    REGISTRY_PATH,
    canonicalize_facebook_url,
    extract_facebook_post_identifiers,
    extract_facebook_publication_urls,
    is_facebook_publication_url,
)
from backend.services.social_collection_service_v2 import ensure_organization_links
from backend.services.rss_relevance_service import classify_article


DEFAULT_ACTOR_ID = "apify/facebook-comments-scraper"
DEFAULT_API_BASE_URL = "https://api.apify.com"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _configured(value: str | None) -> bool:
    value = (value or "").strip()
    return bool(value and not value.lower().startswith("your_") and value != "...")


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def apify_integration_status() -> dict[str, Any]:
    token_available = _configured(os.getenv("APIFY_API_TOKEN"))
    actor_id = (os.getenv("APIFY_FACEBOOK_ACTOR_ID") or DEFAULT_ACTOR_ID).strip()
    enabled = (os.getenv("APIFY_FACEBOOK_COMMENTS_ENABLED") or "true").strip().lower() == "true"
    available = bool(enabled and token_available and actor_id)
    return {
        "provider": "apify",
        "status": "available" if available else "configuration_required",
        "available": available,
        "enabled": enabled,
        "actor_id": actor_id,
        "message": (
            "Collecte Apify configurée pour les commentaires Facebook publics."
            if available
            else "Collecte Apify indisponible : ajoutez APIFY_API_TOKEN dans .env."
        ),
    }


def load_retained_facebook_urls(path: Path = REGISTRY_PATH) -> list[str]:
    """Lit les URLs publiques retenues dans data/fb.txt."""

    if not path.exists():
        return []
    urls: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        value = raw_line.strip()
        if not value or value.startswith("#"):
            continue
        if not is_facebook_publication_url(value):
            continue
        canonical = canonicalize_facebook_url(value)
        if canonical not in urls:
            urls.append(canonical)
    try:
        maximum = max(1, min(int(os.getenv("APIFY_MAX_POSTS_PER_RUN", "20")), 100))
    except ValueError:
        maximum = 20
    return urls[:maximum]


def _resolve_only_comments_newer_than() -> str:
    """Résout le cutoff « ne collecter que les commentaires plus récents que… ».

    Valeur de APIFY_ONLY_COMMENTS_NEWER_THAN dans le .env :
      - vide     → tout l'historique public (1er run : construit la base) ;
      - une date → cutoff FIXE (ex. 2026-08-24) ;
      - 'auto'   → REPÈRE GLISSANT (recommandé en production) : la fin de la
                   dernière période déjà rapportée (snapshot de réputation le
                   plus récent), sinon la date du commentaire le plus récent déjà
                   collecté. Ainsi chaque run hebdomadaire ne récupère QUE les
                   nouveaux commentaires — il ne re-scrape jamais 2018, et le
                   repère avance tout seul à mesure que les semaines sont
                   rapportées. La déduplication (par id de commentaire) protège
                   de tout recouvrement.
    """
    raw = (os.getenv("APIFY_ONLY_COMMENTS_NEWER_THAN") or "").strip()
    if raw.lower() != "auto":
        return raw
    try:
        from backend.database.connection import SessionLocal
        from backend.database.models import Mention, ReputationSnapshot

        with SessionLocal() as session:
            last_period_end = session.scalar(select(func.max(ReputationSnapshot.period_end)))
            if last_period_end is not None:
                return last_period_end.isoformat()
            last_comment = session.scalar(
                select(func.max(func.coalesce(Mention.manual_published_at, Mention.published_at)))
                .where(Mention.content_type == "social_comment")
            )
            if last_comment is not None:
                return last_comment.date().isoformat()
    except Exception as exc:  # ne jamais bloquer la collecte pour ça
        print(f"[apify] cutoff 'auto' indisponible ({type(exc).__name__}: {exc}) — collecte complète")
    return ""


def build_actor_input(urls: list[str]) -> dict[str, Any]:
    """Construit l'entrée selon le schéma courant de l'Actor Apify officiel.

    L'Actor ``apify/facebook-comments-scraper`` utilise désormais les champs
    ``resultsLimit``, ``includeNestedComments`` et ``viewOption``. Les variables
    d'environnement historiques du projet sont conservées pour ne pas casser
    la configuration locale de l'utilisateur.
    """

    collect_all = (os.getenv("APIFY_COLLECT_ALL_COMMENTS") or "true").strip().casefold() in {
        "1", "true", "yes", "oui", "on"
    }
    try:
        configured_limit = max(1, min(int(os.getenv("APIFY_MAX_COMMENTS_PER_POST", "500")), 10000))
    except ValueError:
        configured_limit = 500
    try:
        all_comments_limit = max(100, min(int(os.getenv("APIFY_ALL_COMMENTS_LIMIT", "500")), 10000))
    except ValueError:
        all_comments_limit = 500
    # L'Actor exige une limite numérique. En mode « tout collecter », on utilise
    # une limite haute par URL au lieu de rester bloqué à 20 commentaires.
    results_limit = max(configured_limit, all_comments_limit) if collect_all else configured_limit

    include_replies = (os.getenv("APIFY_INCLUDE_REPLIES") or "true").strip().lower() == "true"
    requested_mode = (os.getenv("APIFY_COMMENTS_MODE") or "Newest").strip().casefold()
    view_option = {
        "all": "RANKED_UNFILTERED",
        "most relevant": "RANKED_THREADED",
        "most_relevant": "RANKED_THREADED",
        "newest": "RECENT_ACTIVITY",
    }.get(requested_mode, "RECENT_ACTIVITY")
    # Apify recommande RECENT_ACTIVITY pour maximiser les commentaires publics
    # accessibles et parcourir les fils les plus récemment actifs.
    if collect_all:
        view_option = "RECENT_ACTIVITY"

    payload: dict[str, Any] = {
        "startUrls": [{"url": url} for url in urls],
        "resultsLimit": results_limit,
        "includeNestedComments": include_replies,
        "viewOption": view_option,
    }
    newer_than = _resolve_only_comments_newer_than()
    if newer_than:
        payload["onlyCommentsNewerThan"] = newer_than
    return payload


def run_apify_actor(urls: list[str]) -> list[dict[str, Any]]:
    """Lance l'Actor officiel et renvoie les éléments du Dataset.

    Le token est transmis dans l'en-tête Authorization afin qu'il n'apparaisse
    ni dans l'URL ni dans les logs du projet.
    """

    status = apify_integration_status()
    if not status["available"]:
        raise RuntimeError(status["message"])

    token = str(os.getenv("APIFY_API_TOKEN") or "").strip()
    actor_id = str(status["actor_id"])
    actor_path = quote(actor_id.replace("/", "~"), safe="~")
    base_url = (os.getenv("APIFY_API_BASE_URL") or DEFAULT_API_BASE_URL).rstrip("/")
    endpoint = f"{base_url}/v2/actors/{actor_path}/run-sync-get-dataset-items"

    try:
        timeout_seconds = max(60, min(int(os.getenv("APIFY_RUN_TIMEOUT_SECONDS", "300")), 900))
    except ValueError:
        timeout_seconds = 300

    response = requests.post(
        endpoint,
        params={"format": "json", "clean": "true"},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=build_actor_input(urls),
        timeout=(30, timeout_seconds),
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        detail = response.text[:1000]
        raise RuntimeError(
            f"Apify a retourné HTTP {response.status_code}: {detail}"
        ) from error

    try:
        payload = response.json()
    except json.JSONDecodeError as error:
        raise RuntimeError("Réponse Apify JSON invalide.") from error

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return [item for item in payload["items"] if isinstance(item, dict)]
    raise RuntimeError("Format de Dataset Apify inattendu.")


def sanitize_apify_raw_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Minimise les données personnelles stockées par défaut."""

    payload = dict(item)
    keep_profile_urls = (
        os.getenv("APIFY_STORE_PROFILE_URLS") or "false"
    ).strip().lower() == "true"
    if not keep_profile_urls:
        for key in ("profilePicture", "profileUrl", "pageAdLibrary"):
            payload.pop(key, None)
    return payload


def normalize_apify_item(item: dict[str, Any]) -> dict[str, Any] | None:
    comment_id = str(item.get("commentId") or item.get("id") or "").strip()
    text = str(item.get("text") or item.get("commentText") or "").strip()
    if not comment_id or not text:
        return None

    post_url = str(
        item.get("inputUrl")
        or item.get("facebookUrl")
        or item.get("postUrl")
        or ""
    ).strip()
    if post_url and is_facebook_publication_url(post_url):
        post_url = canonicalize_facebook_url(post_url)

    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    return {
        "comment_id": comment_id,
        "text": text,
        "comment_url": str(item.get("commentUrl") or item.get("url") or "").strip() or None,
        "post_url": post_url or None,
        "post_title": str(item.get("postTitle") or "").strip() or None,
        "published_at": parse_datetime(item.get("date") or item.get("createdAt") or item.get("timestamp")),
        "author_name": str(item.get("profileName") or item.get("authorName") or author.get("name") or "").strip() or None,
        "author_id": str(item.get("profileId") or item.get("authorId") or author.get("id") or "").strip() or None,
        "author_url": str(item.get("profileUrl") or item.get("authorUrl") or author.get("profileUrl") or "").strip() or None,
        "likes": safe_int(item.get("likesCount") or item.get("likeCount") or item.get("reactionCount")),
        "replies": safe_int(item.get("commentsCount") or item.get("repliesCount") or item.get("replyCount")),
        "threading_depth": safe_int(item.get("threadingDepth") or item.get("depth")),
        "facebook_post_id": str(item.get("facebookId") or item.get("postId") or "").strip() or None,
        "raw": sanitize_apify_raw_payload(item),
    }


def _facebook_source(session: Session) -> Source:
    source = session.scalar(select(Source).where(Source.name == "Facebook"))
    if source is None:
        source = Source(
            name="Facebook",
            source_type="social",
            base_url="https://www.facebook.com",
            reliability_weight=0.8,
            configuration={"collection_providers": ["serper", "apify", "meta"]},
            is_active=True,
        )
        session.add(source)
        session.flush()
    return source


def _parent_quality(post: Mention, facebook_source_id: int) -> tuple[int, float, int]:
    collection = (post.raw_payload or {}).get("_collection") or {}
    created_from_comments = bool(collection.get("created_from_comment_dataset"))
    score = 0
    if post.display_in_marketing:
        score += 100
    if post.validation_status != "excluded":
        score += 40
    if not created_from_comments:
        score += 30
    if post.source_id != facebook_source_id:
        # Les posts découverts par Serper/veille portent déjà les relations ARMA.
        score += 20
    if post.business_relevance_score is not None:
        score += int(max(0.0, min(1.0, post.business_relevance_score)) * 20)
    return score, float(post.business_relevance_score or 0.0), post.id


def _parent_maps(
    session: Session,
    source_id: int,
) -> tuple[dict[str, Mention], dict[str, Mention]]:
    """Associe les résultats Apify aux posts déjà visibles dans les POC.

    Le même post peut être représenté par une URL avec slug, ``story_fbid`` ou
    une URL canonique retournée par Facebook. On indexe donc à la fois les URLs
    et les identifiants de post afin de ne pas créer un parent technique orphelin.
    """

    candidates_by_url: dict[str, list[Mention]] = {}
    candidates_by_id: dict[str, list[Mention]] = {}
    posts = list(
        session.scalars(
            select(Mention)
            .where(Mention.content_type == "social_post")
            .order_by(Mention.collected_at.desc(), Mention.id.desc())
        )
    )
    for post in posts:
        urls = extract_facebook_publication_urls(
            post.url,
            post.raw_payload,
            post.route_metadata,
            post.validation_notes,
        )
        for url in urls:
            candidates_by_url.setdefault(url, []).append(post)
            for identifier in extract_facebook_post_identifiers(url):
                candidates_by_id.setdefault(identifier, []).append(post)

    # Le registre JSON conserve les IDs des mentions qui ont fourni chaque lien.
    # Il permet de retrouver le post Serper/Marketing même si l'URL Apify diffère.
    if REGISTRY_JSON_PATH.exists():
        try:
            registry = json.loads(REGISTRY_JSON_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            registry = {}
        for record in registry.get("records", []) if isinstance(registry, dict) else []:
            if not isinstance(record, dict):
                continue
            record_url = str(record.get("url") or "").strip()
            mention_ids = list(record.get("mention_ids") or []) + list(record.get("source_mention_ids") or [])
            rows = [session.get(Mention, int(mid)) for mid in mention_ids if str(mid).isdigit()]
            rows = [row for row in rows if row is not None and row.content_type == "social_post"]
            if record_url and rows:
                canonical = canonicalize_facebook_url(record_url) if is_facebook_publication_url(record_url) else record_url
                candidates_by_url.setdefault(canonical, []).extend(rows)
                for identifier in extract_facebook_post_identifiers(record_url):
                    candidates_by_id.setdefault(identifier, []).extend(rows)

    choose = lambda rows: max(rows, key=lambda post: _parent_quality(post, source_id))
    by_url = {url: choose(rows) for url, rows in candidates_by_url.items() if rows}
    by_id = {identifier: choose(rows) for identifier, rows in candidates_by_id.items() if rows}
    return by_url, by_id


def _find_parent(
    normalized: dict[str, Any],
    parents_by_url: dict[str, Mention],
    parents_by_id: dict[str, Mention],
) -> Mention | None:
    post_url = str(normalized.get("post_url") or "").strip()
    if post_url:
        parent = parents_by_url.get(post_url)
        if parent is not None:
            return parent
    identifiers = set(extract_facebook_post_identifiers(post_url))
    facebook_post_id = str(normalized.get("facebook_post_id") or "").strip()
    if facebook_post_id:
        identifiers.add(facebook_post_id)
    comment_url = str(normalized.get("comment_url") or "").strip()
    identifiers.update(extract_facebook_post_identifiers(comment_url))
    for identifier in identifiers:
        parent = parents_by_id.get(identifier)
        if parent is not None:
            return parent
    return None


def _repair_existing_comment_links(
    session: Session,
    *,
    source: Source,
    parents_by_url: dict[str, Mention],
    parents_by_id: dict[str, Mention],
    organizations: dict[str, Organization],
) -> int:
    """Répare les commentaires déjà collectés mais rattachés à un parent technique.

    Les commentaires réparés repassent au statut ``new`` afin d'être reclassés
    lors du même workflow et de pouvoir créer une alerte si nécessaire.
    """

    repaired = 0
    comments = list(session.scalars(select(Mention).where(Mention.content_type == "social_comment")))
    for comment in comments:
        payload = comment.raw_payload or {}
        collection = payload.get("_collection") if isinstance(payload, dict) else {}
        post_url = str((collection or {}).get("parent_post_url") or "").strip()
        normalized = {
            "post_url": canonicalize_facebook_url(post_url) if post_url and is_facebook_publication_url(post_url) else post_url,
            "comment_url": comment.url,
            "facebook_post_id": payload.get("facebookId") if isinstance(payload, dict) else None,
        }
        parent = _find_parent(normalized, parents_by_url, parents_by_id)
        if parent is None:
            continue
        old_parent_id = comment.parent_mention_id
        names, primary, method = _choose_organizations(
            session, parent, comment.clean_text or comment.raw_text, organizations
        )
        existing_names = {
            organization.name
            for _, organization in session.execute(
                select(MentionOrganization, Organization)
                .join(Organization, Organization.id == MentionOrganization.organization_id)
                .where(MentionOrganization.mention_id == comment.id)
            ).all()
        }
        changed = old_parent_id != parent.id or any(name not in existing_names for name in names)
        comment.parent_mention_id = parent.id
        if names:
            ensure_organization_links(
                session=session,
                mention=comment,
                detected_names=names,
                organizations=organizations,
                primary_name=primary or names[0],
                include_in_reputation=True,
                detection_method=method,
                relevance_score=1.0 if method == "comment_text_matching" else 0.8,
            )
        if changed:
            collection = dict(collection or {})
            collection["parent_mention_id"] = parent.id
            collection["parent_link_repaired"] = True
            payload = dict(payload)
            payload["_collection"] = collection
            comment.raw_payload = payload
            comment.processing_status = "new"
            repaired += 1
    return repaired


def _create_parent_post(
    session: Session,
    source: Source,
    pipeline: PipelineRun,
    normalized: dict[str, Any],
) -> Mention:
    post_url = normalized.get("post_url") or normalized.get("comment_url") or ""
    identity = post_url or normalized["comment_id"]
    digest = hashlib.sha256(f"apify_facebook_post:{identity}".encode("utf-8")).hexdigest()
    existing = session.scalar(select(Mention).where(Mention.content_hash == digest).limit(1))
    if existing is not None:
        return existing

    title = normalized.get("post_title") or "Publication Facebook publique"
    parent = Mention(
        source_id=source.id,
        content_type="social_post",
        pipeline_run_id=pipeline.id,
        external_id=f"apify_facebook_post:{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}",
        url=post_url or None,
        title=title[:1000],
        display_title=title[:1000],
        display_title_generated=not bool(normalized.get("post_title")),
        raw_text=title,
        clean_text=title,
        published_at=None,
        published_at_confidence="unknown",
        published_at_source="unknown",
        collected_at=utc_now(),
        detected_language=None,
        country=None,
        city=None,
        content_hash=digest,
        engagement={},
        raw_payload={
            "_collection": {
                "channel": "social",
                "content_type": "social_post",
                "platform": "Facebook",
                "aggregator": "Apify",
                "source_provider": "apify",
                "created_from_comment_dataset": True,
            }
        },
        processing_status="new",
        display_in_marketing=False,
        validation_status="pending",
    )
    session.add(parent)
    session.flush()
    return parent


def _existing_comment(session: Session, source_id: int, comment_id: str) -> Mention | None:
    external_id = f"facebook_comment:{comment_id}"
    return session.scalar(
        select(Mention)
        .where(Mention.source_id == source_id, Mention.external_id == external_id)
        .limit(1)
    )


def _earliest_known_comment_time(session: Session, mention: Mention) -> datetime:
    """Restaure au mieux la première date système pour les anciens commentaires.

    Les anciennes versions remplaçaient ``collected_at`` à chaque resynchronisation.
    Une alerte ou une analyse créée plus tôt fournit alors une preuve que le
    commentaire était déjà connu avant la dernière collecte.
    """
    analysis_time = session.scalar(
        select(func.min(MentionAnalysis.analyzed_at))
        .join(MentionOrganization, MentionOrganization.id == MentionAnalysis.mention_organization_id)
        .where(MentionOrganization.mention_id == mention.id)
    )
    alert_time = session.scalar(
        select(func.min(Alert.created_at))
        .join(MentionOrganization, MentionOrganization.id == Alert.mention_organization_id)
        .where(MentionOrganization.mention_id == mention.id)
    )
    candidates = [value for value in (mention.collected_at, analysis_time, alert_time) if value is not None]
    return min(candidates) if candidates else utc_now()


def repair_legacy_comment_collection_dates() -> dict[str, int]:
    """Répare les dates des commentaires créés avec les anciennes versions.

    Avant V11, une resynchronisation Apify remplaçait ``collected_at``. Un vieux
    commentaire pouvait donc sembler avoir été collecté aujourd'hui. On restaure
    la plus ancienne preuve système disponible (analyse/alerte/collected_at).
    """
    session = SessionLocal()
    try:
        comments = list(
            session.scalars(
                select(Mention).where(Mention.content_type == "social_comment")
            )
        )
        changed = 0
        for comment in comments:
            earliest = _earliest_known_comment_time(session, comment)
            if comment.collected_at is None or earliest < comment.collected_at:
                comment.collected_at = earliest
                changed += 1
            payload = dict(comment.raw_payload or {})
            collection = dict(payload.get("_collection") or {})
            collection.setdefault("first_collected_at", comment.collected_at.isoformat())
            payload["_collection"] = collection
            comment.raw_payload = payload
        session.commit()
        return {"comments_checked": len(comments), "dates_repaired": changed}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _choose_organizations(
    session: Session,
    parent: Mention,
    text: str,
    organizations: dict[str, Organization],
) -> tuple[list[str], str | None, str]:
    from backend.services.facebook_comment_collection_service import choose_comment_organizations

    names, primary, method = choose_comment_organizations(session, parent, text)
    names = [name for name in names if name in organizations]
    if primary not in organizations:
        primary = names[0] if names else None
    return names, primary, method


def save_apify_comments(items: list[dict[str, Any]]) -> dict[str, Any]:
    session = SessionLocal()
    pipeline_id: int | None = None
    try:
        source = _facebook_source(session)
        pipeline = PipelineRun(
            run_type="apify_facebook_comment_collection",
            source_id=source.id,
            watch_query_id=None,
            status="running",
            started_at=utc_now(),
            statistics={"provider": "apify"},
        )
        session.add(pipeline)
        session.commit()
        session.refresh(pipeline)
        pipeline_id = pipeline.id

        parents_by_url, parents_by_id = _parent_maps(session, source.id)
        organizations = {
            row.name: row for row in session.scalars(select(Organization)).all()
        }
        counters = {
            "provider": "apify",
            "items_received": len(items),
            "comments_valid": 0,
            "comments_created": 0,
            "comments_updated": 0,
            "comments_ignored": 0,
            "parent_posts_created": 0,
            "existing_comments_repaired": 0,
            "posts_seen": set(),
            "comments_by_post": {},
        }

        for item in items:
            normalized = normalize_apify_item(item)
            if normalized is None:
                counters["comments_ignored"] += 1
                continue
            counters["comments_valid"] += 1
            post_url = normalized.get("post_url") or ""
            if post_url:
                counters["posts_seen"].add(post_url)
            parent = _find_parent(normalized, parents_by_url, parents_by_id)
            if parent is None:
                parent = _create_parent_post(session, source, pipeline, normalized)
                counters["parent_posts_created"] += 1
                if parent.url and is_facebook_publication_url(parent.url):
                    canonical_parent_url = canonicalize_facebook_url(parent.url)
                    parents_by_url[canonical_parent_url] = parent
                    for identifier in extract_facebook_post_identifiers(canonical_parent_url):
                        parents_by_id[identifier] = parent

            # Un lien ajouté manuellement à fb.txt peut ne pas encore posséder
            # de relations organisationnelles. Le titre du post fourni par
            # Apify permet alors de créer un rattachement minimal.
            parent_classification = classify_article(
                {"raw_text": normalized.get("post_title") or parent.raw_text or ""}
            )
            parent_names = [
                name for name in parent_classification["organizations"]
                if name in organizations
            ]
            if parent_names:
                ensure_organization_links(
                    session=session,
                    mention=parent,
                    detected_names=parent_names,
                    organizations=organizations,
                    primary_name=parent_names[0],
                    include_in_reputation=True,
                    detection_method="apify_post_title",
                    relevance_score=0.8,
                )

            mention = _existing_comment(session, source.id, normalized["comment_id"])
            created = mention is None
            observed_at = utc_now()
            raw_payload = dict(normalized["raw"])
            raw_payload["_collection"] = {
                "channel": "social",
                "content_type": "social_comment",
                "platform": "Facebook",
                "aggregator": "Apify",
                "source_provider": "apify",
                "platform_comment_id": normalized["comment_id"],
                "parent_mention_id": parent.id,
                "parent_post_url": post_url or parent.url,
                "include_in_reputation": True,
                "threading_depth": normalized["threading_depth"],
                "public_data": True,
                "last_seen_at": observed_at.isoformat(),
            }
            if created:
                raw_payload["_collection"]["first_collected_at"] = observed_at.isoformat()
                content_hash = hashlib.sha256(
                    f"facebook_comment:{normalized['comment_id']}".encode("utf-8")
                ).hexdigest()
                mention = Mention(
                    source_id=source.id,
                    content_type="social_comment",
                    parent_mention_id=parent.id,
                    pipeline_run_id=pipeline.id,
                    external_id=f"facebook_comment:{normalized['comment_id']}",
                    url=normalized["comment_url"],
                    title="Commentaire Facebook public",
                    display_title="Commentaire Facebook public",
                    raw_text=normalized["text"],
                    clean_text=None,
                    author_name=normalized["author_name"],
                    author_handle=normalized["author_id"],
                    published_at=normalized["published_at"],
                    published_at_confidence="extracted" if normalized["published_at"] else "unknown",
                    published_at_source="social_platform" if normalized["published_at"] else "unknown",
                    collected_at=observed_at,
                    detected_language=None,
                    country=None,
                    city=None,
                    content_hash=content_hash,
                    engagement={
                        "likes": normalized["likes"],
                        "replies": normalized["replies"],
                    },
                    raw_payload=raw_payload,
                    processing_status="new",
                    display_in_marketing=False,
                    validation_status="pending",
                )
                session.add(mention)
                session.flush()
                counters["comments_created"] += 1
                per_post = counters["comments_by_post"].setdefault(post_url or str(parent.url or parent.id), {"received": 0, "created": 0, "updated": 0})
                per_post["created"] += 1
            else:
                mention.parent_mention_id = parent.id
                mention.pipeline_run_id = pipeline.id
                mention.url = normalized["comment_url"] or mention.url
                mention.raw_text = normalized["text"]
                mention.author_name = normalized["author_name"] or mention.author_name
                mention.author_handle = normalized["author_id"] or mention.author_handle
                mention.published_at = normalized["published_at"] or mention.published_at
                # IMPORTANT : collected_at représente désormais la PREMIÈRE
                # collecte. Une resynchronisation d'un ancien commentaire ne le
                # fait donc plus réapparaître artificiellement dans la semaine courante.
                mention.collected_at = _earliest_known_comment_time(session, mention)
                raw_payload["_collection"]["first_collected_at"] = mention.collected_at.isoformat()
                mention.engagement = {
                    "likes": normalized["likes"],
                    "replies": normalized["replies"],
                }
                mention.raw_payload = raw_payload
                mention.processing_status = "new"
                counters["comments_updated"] += 1
                per_post = counters["comments_by_post"].setdefault(post_url or str(parent.url or parent.id), {"received": 0, "created": 0, "updated": 0})
                per_post["updated"] += 1

            post_key = post_url or str(parent.url or parent.id)
            per_post = counters["comments_by_post"].setdefault(post_key, {"received": 0, "created": 0, "updated": 0})
            per_post["received"] += 1

            names, primary, method = _choose_organizations(
                session, parent, normalized["text"], organizations
            )
            if names:
                ensure_organization_links(
                    session=session,
                    mention=mention,
                    detected_names=names,
                    organizations=organizations,
                    primary_name=primary or names[0],
                    include_in_reputation=True,
                    detection_method=method,
                    relevance_score=1.0 if method == "comment_text_matching" else 0.75,
                )

        counters["existing_comments_repaired"] = _repair_existing_comment_links(
            session,
            source=source,
            parents_by_url=parents_by_url,
            parents_by_id=parents_by_id,
            organizations=organizations,
        )
        session.commit()
        current = session.get(PipelineRun, pipeline_id)
        if current is None:
            raise RuntimeError("Pipeline Apify introuvable.")
        serializable_counters = dict(counters)
        serializable_counters["posts_seen"] = len(counters["posts_seen"])
        current.status = "completed"
        current.finished_at = utc_now()
        current.items_received = counters["comments_valid"]
        current.items_created = counters["comments_created"]
        current.items_duplicated = counters["comments_updated"]
        current.statistics = serializable_counters
        session.commit()
        return {"status": "completed", **serializable_counters}
    except Exception as error:
        session.rollback()
        if pipeline_id is not None:
            current = session.get(PipelineRun, pipeline_id)
            if current is not None:
                current.status = "failed"
                current.finished_at = utc_now()
                current.error_message = str(error)[:4000]
                session.commit()
        raise
    finally:
        session.close()


def collect_apify_facebook_comments() -> dict[str, Any]:
    state = apify_integration_status()
    if not state["available"]:
        return {**state, "synced": 0}

    urls = load_retained_facebook_urls()
    if not urls:
        return {
            **state,
            "status": "no_links",
            "message": "Aucun post Facebook retenu dans data/fb.txt.",
            "synced": 0,
        }

    items = run_apify_actor(urls)

    # Certains posts peuvent être oubliés dans un run multi-URL alors qu'ils sont
    # accessibles individuellement. On retente uniquement les URLs sans aucun
    # commentaire, avec une limite pour maîtriser le temps et le coût Apify.
    returned_urls: set[str] = set()
    seen_comment_ids: set[str] = set()
    deduplicated_items: list[dict[str, Any]] = []
    for item in items:
        normalized = normalize_apify_item(item)
        if normalized is None:
            continue
        comment_id = str(normalized["comment_id"])
        if comment_id in seen_comment_ids:
            continue
        seen_comment_ids.add(comment_id)
        deduplicated_items.append(item)
        if normalized.get("post_url"):
            returned_urls.add(str(normalized["post_url"]))

    empty_urls = [url for url in urls if url not in returned_urls]
    retry_enabled = (os.getenv("APIFY_RETRY_EMPTY_POSTS") or "true").strip().casefold() in {
        "1", "true", "yes", "oui", "on"
    }
    try:
        retry_limit = max(0, min(int(os.getenv("APIFY_EMPTY_POST_RETRY_LIMIT", "5")), 20))
    except ValueError:
        retry_limit = 5
    retried_urls: list[str] = []
    if retry_enabled:
        for url in empty_urls[:retry_limit]:
            retried_urls.append(url)
            try:
                retry_items = run_apify_actor([url])
            except RuntimeError as error:
                print(f"Apify : nouvelle tentative impossible pour {url} : {error}")
                continue
            for item in retry_items:
                normalized = normalize_apify_item(item)
                if normalized is None:
                    continue
                comment_id = str(normalized["comment_id"])
                if comment_id in seen_comment_ids:
                    continue
                seen_comment_ids.add(comment_id)
                deduplicated_items.append(item)
                if normalized.get("post_url"):
                    returned_urls.add(str(normalized["post_url"]))

    result = save_apify_comments(deduplicated_items)
    result.update(
        {
            "provider": "apify",
            "urls_submitted": len(urls),
            "empty_urls_before_retry": empty_urls,
            "retried_urls": retried_urls,
            "still_empty_urls": [url for url in urls if url not in returned_urls],
            "synced": result.get("comments_created", 0) + result.get("comments_updated", 0),
        }
    )
    print(
        "Apify Facebook comments : "
        f"{result.get('comments_created', 0)} créé(s), "
        f"{result.get('comments_updated', 0)} mis à jour, "
        f"{len(urls)} post(s)."
    )
    return result


__all__ = [
    "apify_integration_status",
    "build_actor_input",
    "collect_apify_facebook_comments",
    "load_retained_facebook_urls",
    "normalize_apify_item",
    "run_apify_actor",
    "sanitize_apify_raw_payload",
    "save_apify_comments",
]
