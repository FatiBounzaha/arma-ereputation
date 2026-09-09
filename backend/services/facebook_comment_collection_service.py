from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.collectors.meta_graph_client import MetaGraphClient
from backend.database.connection import SessionLocal
from backend.database.models import (
    Mention,
    MentionOrganization,
    Organization,
    PipelineRun,
    Source,
)
from backend.services.rss_relevance_service import classify_article
from backend.services.social_collection_service_v2 import (
    detect_basic_language,
    ensure_organization_links,
    extract_facebook_post_id,
)


COMMENT_LOOKBACK_DAYS = int(os.getenv("META_COMMENT_LOOKBACK_DAYS", "30"))
COMMENT_POST_LIMIT = int(os.getenv("META_COMMENT_POST_LIMIT", "50"))
COMMENT_PAGE_SIZE = int(os.getenv("META_COMMENT_PAGE_SIZE", "100"))
COMMENT_MAX_PAGES = int(os.getenv("META_COMMENT_MAX_PAGES", "3"))
COMMENT_MAX_REPLY_DEPTH = int(os.getenv("META_COMMENT_MAX_REPLY_DEPTH", "1"))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def load_page_id_mapping() -> dict[str, str]:
    """Charge META_FACEBOOK_PAGE_IDS, un objet JSON slug -> identifiant."""

    raw = (os.getenv("META_FACEBOOK_PAGE_IDS") or "{}").strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "META_FACEBOOK_PAGE_IDS doit être un objet JSON valide."
        ) from error

    if not isinstance(payload, dict):
        raise RuntimeError("META_FACEBOOK_PAGE_IDS doit être un objet JSON.")

    return {
        str(slug).casefold().lstrip("@"): str(page_id)
        for slug, page_id in payload.items()
        if str(slug).strip() and str(page_id).strip()
    }


def extract_facebook_page_slug(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None

    segments = [
        unquote(segment).strip()
        for segment in parsed.path.split("/")
        if segment.strip()
    ]
    if not segments:
        return None
    if segments[0].casefold() in {"story.php", "permalink.php"}:
        return None
    return segments[0].casefold().lstrip("@")


def build_graph_object_candidates(
    mention: Mention,
    page_ids: dict[str, str],
) -> list[str]:
    """Construit les identifiants que Meta peut accepter pour le post."""

    candidates: list[str] = []
    payload = mention.raw_payload or {}
    collection = payload.get("_collection") or {}

    explicit = collection.get("facebook_graph_object_id")
    if explicit:
        candidates.append(str(explicit))

    url = mention.url or ""
    try:
        parsed = urlsplit(url)
        query_values = parse_qs(parsed.query)
    except ValueError:
        query_values = {}

    post_id = extract_facebook_post_id(url)
    page_id_values = query_values.get("id", [])
    if post_id and page_id_values:
        candidates.append(f"{page_id_values[0]}_{post_id}")

    page_slug = extract_facebook_page_slug(url)
    mapped_page_id = page_ids.get(page_slug or "")
    if post_id and mapped_page_id:
        candidates.append(f"{mapped_page_id}_{post_id}")

    # Certains objets sont acceptés avec story_fbid seul selon le type du post.
    if post_id:
        candidates.append(post_id)

    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def find_existing_comment(
    session: Session,
    source_id: int,
    external_id: str,
    content_hash: str,
) -> Mention | None:
    return session.scalar(
        select(Mention)
        .where(
            or_(
                Mention.content_hash == content_hash,
                (
                    (Mention.source_id == source_id)
                    & (Mention.external_id == external_id)
                ),
            )
        )
        .limit(1)
    )


def choose_comment_organizations(
    session: Session,
    parent_mention: Mention,
    text: str,
) -> tuple[list[str], str, str]:
    """Privilégie les entreprises citées, sinon hérite de la principale du post."""

    classification = classify_article({"raw_text": text})
    explicit_names = list(classification["organizations"])
    if explicit_names:
        return explicit_names, explicit_names[0], "comment_text_matching"

    rows = session.execute(
        select(MentionOrganization, Organization)
        .join(
            Organization,
            Organization.id == MentionOrganization.organization_id,
        )
        .where(MentionOrganization.mention_id == parent_mention.id)
        .order_by(MentionOrganization.is_primary.desc(), MentionOrganization.id)
    ).all()

    if not rows:
        return [], "", "parent_social_post"

    # Pour un commentaire qui ne cite aucun nom, on hérite d'abord
    # de l'organisation ayant déclenché la découverte Serper du post.
    collection = (parent_mention.raw_payload or {}).get("_collection") or {}
    queried_name = str(collection.get("queried_organization_name") or "")
    available_names = {organization.name for _, organization in rows}
    if queried_name in available_names:
        return [queried_name], queried_name, "parent_social_post"

    primary = next(
        (organization.name for relation, organization in rows if relation.is_primary),
        rows[0][1].name,
    )
    return [primary], primary, "parent_social_post"


def create_or_update_comment(
    session: Session,
    source: Source,
    pipeline: PipelineRun,
    parent_mention: Mention,
    comment: dict[str, Any],
    organizations: dict[str, Organization],
    official_page_ids: set[str],
    graph_parent_id: str,
) -> tuple[Mention | None, bool]:
    comment_id = str(comment.get("id") or "").strip()
    message = str(comment.get("message") or "").strip()
    if not comment_id or not message:
        return None, False

    external_id = f"facebook_comment:{comment_id}"
    content_hash = hashlib.sha256(external_id.encode("utf-8")).hexdigest()
    existing = find_existing_comment(
        session=session,
        source_id=source.id,
        external_id=external_id,
        content_hash=content_hash,
    )

    author = comment.get("from") if isinstance(comment.get("from"), dict) else {}
    author_id = str(author.get("id") or "")
    include_in_reputation = author_id not in official_page_ids

    names, primary_name, detection_method = choose_comment_organizations(
        session=session,
        parent_mention=parent_mention,
        text=message,
    )

    if existing is None:
        payload = dict(comment)
        payload["_collection"] = {
            "channel": "social",
            "content_type": "social_comment",
            "platform": "Facebook",
            "aggregator": "Meta Graph API",
            "parent_mention_id": parent_mention.id,
            "parent_graph_object_id": graph_parent_id,
            "include_in_reputation": include_in_reputation,
            "detected_organizations": names,
        }

        existing = Mention(
            source_id=source.id,
            content_type="social_comment",
            parent_mention_id=parent_mention.id,
            pipeline_run_id=pipeline.id,
            external_id=external_id,
            url=str(comment.get("permalink_url") or "") or None,
            title="Commentaire Facebook",
            raw_text=message,
            clean_text=None,
            author_name=str(author.get("name") or "") or None,
            author_handle=None,
            published_at=parse_datetime(comment.get("created_time")),
            collected_at=utc_now(),
            detected_language=detect_basic_language(message),
            country="MA",
            city=None,
            content_hash=content_hash,
            engagement={
                "likes": int(comment.get("like_count") or 0),
                "replies": int(comment.get("comment_count") or 0),
            },
            raw_payload=payload,
            processing_status="new",
        )
        session.add(existing)
        session.flush()
        created = True
    else:
        existing.raw_text = message
        existing.engagement = {
            "likes": int(comment.get("like_count") or 0),
            "replies": int(comment.get("comment_count") or 0),
        }
        created = False

    if names:
        ensure_organization_links(
            session=session,
            mention=existing,
            detected_names=names,
            organizations=organizations,
            primary_name=primary_name,
            include_in_reputation=include_in_reputation,
            detection_method=detection_method,
            relevance_score=1.0 if detection_method == "comment_text_matching" else 0.75,
        )

    return existing, created


def fetch_comments_with_fallback(
    client: MetaGraphClient,
    candidates: list[str],
) -> tuple[str, list[dict[str, Any]]]:
    errors: list[str] = []
    for candidate in candidates:
        try:
            return candidate, client.get_comments(
                object_id=candidate,
                page_size=COMMENT_PAGE_SIZE,
                max_pages=COMMENT_MAX_PAGES,
            )
        except RuntimeError as error:
            errors.append(f"{candidate}: {error}")

    raise RuntimeError(" | ".join(errors) or "Aucun identifiant Meta disponible.")


def collect_facebook_comments_meta() -> dict[str, Any]:
    """Collecte via Meta Graph API les commentaires des posts accessibles."""

    if not os.getenv("META_ACCESS_TOKEN") or not os.getenv("META_GRAPH_VERSION"):
        message = (
            "Collecte Meta ignorée : configure META_ACCESS_TOKEN et "
            "META_GRAPH_VERSION dans .env."
        )
        print(message)
        return {"provider": "meta", "status": "permission_required", "message": message, "synced": 0}

    session = SessionLocal()
    pipeline_id: int | None = None

    try:
        client = MetaGraphClient()
        page_ids = load_page_id_mapping()
        official_page_ids = set(page_ids.values())

        facebook_source = session.scalar(
            select(Source).where(Source.name == "Facebook")
        )
        if facebook_source is None:
            raise RuntimeError("La source Facebook est absente de PostgreSQL.")

        pipeline = PipelineRun(
            run_type="facebook_comment_collection",
            source_id=facebook_source.id,
            watch_query_id=None,
            status="running",
            started_at=utc_now(),
            statistics={},
        )
        session.add(pipeline)
        session.commit()
        session.refresh(pipeline)
        pipeline_id = pipeline.id

        cutoff = utc_now() - timedelta(days=COMMENT_LOOKBACK_DAYS)
        posts = list(
            session.scalars(
                select(Mention)
                .where(
                    Mention.source_id == facebook_source.id,
                    Mention.content_type == "social_post",
                    Mention.collected_at >= cutoff,
                )
                .order_by(Mention.collected_at.desc())
                .limit(COMMENT_POST_LIMIT)
            )
        )
        organizations = {
            organization.name: organization
            for organization in session.scalars(select(Organization)).all()
        }

        counters = {
            "posts_examined": len(posts),
            "posts_accessible": 0,
            "posts_failed": 0,
            "comments_received": 0,
            "comments_created": 0,
            "comments_updated": 0,
        }

        for post in posts:
            candidates = build_graph_object_candidates(post, page_ids)
            if not candidates:
                counters["posts_failed"] += 1
                print(f"Commentaires ignorés, ID Meta absent : {post.url}")
                continue

            try:
                graph_object_id, comments = fetch_comments_with_fallback(
                    client=client,
                    candidates=candidates,
                )
                counters["posts_accessible"] += 1
                counters["comments_received"] += len(comments)
            except RuntimeError as error:
                counters["posts_failed"] += 1
                print(f"Commentaires inaccessibles pour {post.url} : {error}")
                continue

            queue: list[tuple[dict[str, Any], Mention, int]] = [
                (comment, post, 0) for comment in comments
            ]

            while queue:
                comment, parent, depth = queue.pop(0)
                comment_mention, created = create_or_update_comment(
                    session=session,
                    source=facebook_source,
                    pipeline=pipeline,
                    parent_mention=parent,
                    comment=comment,
                    organizations=organizations,
                    official_page_ids=official_page_ids,
                    graph_parent_id=graph_object_id,
                )
                if comment_mention is None:
                    continue

                if created:
                    counters["comments_created"] += 1
                else:
                    counters["comments_updated"] += 1

                reply_count = int(comment.get("comment_count") or 0)
                comment_id = str(comment.get("id") or "")
                if (
                    reply_count > 0
                    and comment_id
                    and depth < COMMENT_MAX_REPLY_DEPTH
                ):
                    try:
                        replies = client.get_comments(
                            object_id=comment_id,
                            page_size=COMMENT_PAGE_SIZE,
                            max_pages=COMMENT_MAX_PAGES,
                        )
                    except RuntimeError as error:
                        print(f"Réponses inaccessibles pour {comment_id} : {error}")
                    else:
                        counters["comments_received"] += len(replies)
                        queue.extend(
                            (reply, comment_mention, depth + 1)
                            for reply in replies
                        )

            session.commit()

        current = session.get(PipelineRun, pipeline_id)
        if current is None:
            raise RuntimeError("Pipeline commentaires introuvable.")
        current.status = "completed"
        current.finished_at = utc_now()
        current.items_received = counters["comments_received"]
        current.items_created = counters["comments_created"]
        current.items_duplicated = counters["comments_updated"]
        current.statistics = counters
        session.commit()

        print("\nCollecte des commentaires Facebook via Meta terminée.")
        for key, value in counters.items():
            print(f"- {key}: {value}")
        return {
            "provider": "meta",
            "status": "completed",
            "synced": counters["comments_created"] + counters["comments_updated"],
            **counters,
        }

    except Exception as error:
        session.rollback()
        if pipeline_id is not None:
            current = session.get(PipelineRun, pipeline_id)
            if current is not None:
                current.status = "failed"
                current.finished_at = utc_now()
                current.error_message = str(error)
                session.commit()
        raise
    finally:
        session.close()


def comments_collection_status() -> dict[str, Any]:
    """État de la collecte, distinct de l'envoi de réponses via Meta."""

    from backend.services.apify_facebook_comments_service import apify_integration_status
    from backend.services.meta_facebook_comments_service import integration_status as meta_status

    requested = (os.getenv("FACEBOOK_COMMENTS_PROVIDER") or "auto").strip().lower()
    if requested not in {"auto", "apify", "meta", "disabled"}:
        requested = "auto"
    apify = apify_integration_status()
    meta = meta_status()
    if requested == "auto":
        selected = "apify" if apify["available"] else ("meta" if meta["available"] else "none")
    elif requested == "disabled":
        selected = "none"
    else:
        selected = requested
    collection_available = (selected == "apify" and apify["available"]) or (
        selected == "meta" and meta["available"]
    )
    return {
        "provider": selected,
        "requested_provider": requested,
        "collection_available": collection_available,
        "status": "available" if collection_available else ("disabled" if selected == "none" else "configuration_required"),
        "message": (
            f"Collecte Facebook configurée via {selected}."
            if collection_available
            else "Aucun collecteur Facebook n'est configuré."
        ),
        "apify": apify,
        "meta": meta,
    }


def collect_facebook_comments(*, strict: bool = False) -> dict[str, Any]:
    """Sélectionne Apify ou Meta et retourne un diagnostic exploitable.

    ``strict=True`` est utilisé par l'orchestrateur n8n : une erreur réelle de
    collecte est alors remontée afin que le nœud ne soit plus marqué comme
    réussi alors qu'aucun commentaire n'a été importé.
    """

    state = comments_collection_status()
    provider = state["provider"]

    if strict and provider in {"apify", "meta"} and not state["collection_available"]:
        raise RuntimeError(state.get("message") or "Collecteur Facebook non configuré.")

    try:
        if provider == "apify":
            from backend.services.apify_facebook_comments_service import collect_apify_facebook_comments

            result = collect_apify_facebook_comments()
        elif provider == "meta":
            result = collect_facebook_comments_meta()
        else:
            result = {**state, "synced": 0}
    except Exception as error:
        message = f"Collecte Facebook via {provider} indisponible : {error}"
        print(message)
        if strict:
            raise RuntimeError(message) from error
        return {
            **state,
            "status": "unavailable",
            "message": message,
            "synced": 0,
        }

    if strict and result.get("status") in {"unavailable", "configuration_required"}:
        raise RuntimeError(str(result.get("message") or "Collecte Facebook indisponible."))
    return result


if __name__ == "__main__":
    collect_facebook_comments()
