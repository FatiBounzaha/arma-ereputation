from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

from sqlalchemy import or_, select

from backend.collectors.instagram_graph_client import InstagramGraphClient
from backend.database.connection import SessionLocal
from backend.database.models import Mention, Organization, PipelineRun, Source
from backend.services.social_collection_service_v2 import detect_basic_language, ensure_organization_links

IG_ACCOUNT_ID = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")
IG_OFFICIAL_USERNAME = (os.getenv("INSTAGRAM_OFFICIAL_USERNAME") or "arma.environnement").casefold().lstrip("@")
IG_MEDIA_LIMIT = int(os.getenv("INSTAGRAM_MEDIA_LIMIT", "25"))
IG_COMMENT_PAGE_SIZE = int(os.getenv("INSTAGRAM_COMMENT_PAGE_SIZE", "100"))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _find(session, source_id: int, external_id: str) -> Mention | None:
    content_hash = hashlib.sha256(external_id.encode()).hexdigest()
    return session.scalar(
        select(Mention).where(
            or_(Mention.content_hash == content_hash, (Mention.source_id == source_id) & (Mention.external_id == external_id))
        )
    )


def collect_instagram_comments() -> None:
    """Collecte les posts ARMA Instagram et leurs commentaires via Meta Graph."""

    if not (os.getenv("META_ACCESS_TOKEN") and os.getenv("META_GRAPH_VERSION") and IG_ACCOUNT_ID):
        print("Collecte Instagram Graph ignorée : configure META_ACCESS_TOKEN, META_GRAPH_VERSION et INSTAGRAM_BUSINESS_ACCOUNT_ID.")
        return

    session = SessionLocal()
    try:
        source = session.scalar(select(Source).where(Source.name == "Instagram"))
        arma = session.scalar(select(Organization).where(Organization.name == "ARMA"))
        if source is None or arma is None:
            raise RuntimeError("Source Instagram ou organisation ARMA absente. Lancez backend.database.seed.")

        pipeline = PipelineRun(
            run_type="instagram_graph_comments",
            source_id=source.id,
            watch_query_id=None,
            status="running",
            started_at=utc_now(),
            statistics={},
        )
        session.add(pipeline)
        session.commit()
        session.refresh(pipeline)

        client = InstagramGraphClient()
        media_items = client.get_media(IG_ACCOUNT_ID, IG_MEDIA_LIMIT)
        organizations = {"ARMA": arma}
        posts_created = 0
        comments_created = 0

        for media in media_items:
            media_id = str(media.get("id") or "").strip()
            if not media_id:
                continue
            caption = str(media.get("caption") or "").strip()
            post_external_id = f"instagram_media:{media_id}"
            post = _find(session, source.id, post_external_id)
            if post is None:
                content_hash = hashlib.sha256(post_external_id.encode()).hexdigest()
                post = Mention(
                    source_id=source.id,
                    content_type="social_post",
                    business_category=None,
                    business_relevance_score=0.0,
                    business_summary=None,
                    display_in_marketing=False,
                    quality_flags=["owned_content"],
                    parent_mention_id=None,
                    pipeline_run_id=pipeline.id,
                    external_id=post_external_id,
                    url=str(media.get("permalink") or "") or None,
                    title=(caption[:300] or "Publication Instagram ARMA"),
                    raw_text=caption or "Publication Instagram ARMA",
                    clean_text=None,
                    author_name=str(media.get("username") or IG_OFFICIAL_USERNAME),
                    author_handle=f"@{str(media.get('username') or IG_OFFICIAL_USERNAME).lstrip('@')}",
                    published_at=parse_dt(media.get("timestamp")),
                    collected_at=utc_now(),
                    detected_language=detect_basic_language(caption),
                    country="MA",
                    city=None,
                    content_hash=content_hash,
                    engagement={
                        "likes": int(media.get("like_count") or 0),
                        "comments": int(media.get("comments_count") or 0),
                    },
                    raw_payload={**media, "_collection": {"aggregator": "Instagram Graph API", "include_in_reputation": False}},
                    processing_status="new",
                )
                session.add(post)
                session.flush()
                ensure_organization_links(
                    session, post, ["ARMA"], organizations, "ARMA", False,
                    detection_method="owned_instagram_account", relevance_score=1.0,
                )
                posts_created += 1

            for comment in client.get_comments(media_id, IG_COMMENT_PAGE_SIZE):
                comment_id = str(comment.get("id") or "").strip()
                text = str(comment.get("text") or "").strip()
                if not comment_id or not text:
                    continue
                external_id = f"instagram_comment:{comment_id}"
                if _find(session, source.id, external_id) is not None:
                    continue
                username = str(comment.get("username") or "").casefold().lstrip("@")
                include = username != IG_OFFICIAL_USERNAME
                content_hash = hashlib.sha256(external_id.encode()).hexdigest()
                mention = Mention(
                    source_id=source.id,
                    content_type="social_comment",
                    business_category=None,
                    business_relevance_score=0.0,
                    business_summary=None,
                    display_in_marketing=False,
                    quality_flags=[],
                    parent_mention_id=post.id,
                    pipeline_run_id=pipeline.id,
                    external_id=external_id,
                    url=None,
                    title="Commentaire Instagram",
                    raw_text=text,
                    clean_text=None,
                    author_name=str(comment.get("username") or "") or None,
                    author_handle=f"@{comment.get('username')}" if comment.get("username") else None,
                    published_at=parse_dt(comment.get("timestamp")),
                    collected_at=utc_now(),
                    detected_language=detect_basic_language(text),
                    country=None,
                    city=None,
                    content_hash=content_hash,
                    engagement={"likes": int(comment.get("like_count") or 0)},
                    raw_payload={**comment, "_collection": {"aggregator": "Instagram Graph API", "include_in_reputation": include}},
                    processing_status="new",
                )
                session.add(mention)
                session.flush()
                ensure_organization_links(
                    session, mention, ["ARMA"], organizations, "ARMA", include,
                    detection_method="parent_instagram_post", relevance_score=0.8,
                )
                comments_created += 1

        pipeline.status = "completed"
        pipeline.finished_at = utc_now()
        pipeline.items_received = len(media_items)
        pipeline.items_created = posts_created + comments_created
        pipeline.statistics = {"posts_created": posts_created, "comments_created": comments_created}
        session.commit()
        print(f"Instagram Graph : {posts_created} post(s), {comments_created} commentaire(s) créés.")
    finally:
        session.close()


if __name__ == "__main__":
    collect_instagram_comments()
