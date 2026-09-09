from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select

from backend.collectors.x_api_client import XApiClient
from backend.database.connection import SessionLocal
from backend.database.models import Mention, Organization, PipelineRun, Source
from backend.processing.business_relevance import evaluate_business_relevance
from backend.services.rss_relevance_service import classify_article
from backend.services.social_collection_service_v2 import detect_basic_language, ensure_organization_links

X_MAX_RESULTS = int(os.getenv("X_MAX_RESULTS", "25"))
X_QUERY = os.getenv(
    "X_RECENT_QUERY",
    '("ARMA Environnement" OR "ARMA Maroc" OR @ARMA_MA OR "شركة أرما") '
    '(déchets OR propreté OR collecte OR nettoyage OR النفايات OR النظافة) '
    '-is:retweet',
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def collect_x_api_posts() -> None:
    """Complément optionnel à Serper : recherche récente X via l'API officielle."""

    if not os.getenv("X_BEARER_TOKEN"):
        print("Collecte X API ignorée : configure X_BEARER_TOKEN dans .env.")
        return

    session = SessionLocal()
    try:
        source = session.scalar(select(Source).where(Source.name == "X / Twitter"))
        if source is None:
            raise RuntimeError("Source X / Twitter absente. Lancez backend.database.seed.")

        pipeline = PipelineRun(
            run_type="x_api_recent_search",
            source_id=source.id,
            watch_query_id=None,
            status="running",
            started_at=utc_now(),
            statistics={"query": X_QUERY},
        )
        session.add(pipeline)
        session.commit()
        session.refresh(pipeline)

        payload = XApiClient().search_recent(X_QUERY, X_MAX_RESULTS)
        users = {
            str(item.get("id")): item
            for item in (payload.get("includes") or {}).get("users", [])
            if isinstance(item, dict)
        }
        organizations = {
            item.name: item for item in session.scalars(select(Organization).where(Organization.is_active.is_(True)))
        }

        created = 0
        ignored = 0
        for post in payload.get("data") or []:
            if not isinstance(post, dict) or not post.get("id") or not post.get("text"):
                ignored += 1
                continue
            post_id = str(post["id"])
            text = str(post["text"])
            author = users.get(str(post.get("author_id")), {})
            username = str(author.get("username") or "")
            url = f"https://x.com/{username}/status/{post_id}" if username else f"https://x.com/i/web/status/{post_id}"

            classification = classify_article({"raw_text": text})
            if "ARMA" not in classification["organizations"] or not classification["sector_topics"]:
                ignored += 1
                continue

            decision = evaluate_business_relevance(
                {"title": text[:120], "snippet": text, "date": post.get("created_at")},
                organizations=classification["organizations"],
                sector_topics=classification["sector_topics"],
                content_origin="earned",
                content_purpose="general",
                source_name="X / Twitter",
                query_category="competitor",
            )
            external_id = f"x_post:{post_id}"
            content_hash = hashlib.sha256(external_id.encode()).hexdigest()
            existing = session.scalar(
                select(Mention).where(
                    or_(Mention.content_hash == content_hash, (Mention.source_id == source.id) & (Mention.external_id == external_id))
                )
            )
            if existing is not None:
                continue

            metrics = post.get("public_metrics") if isinstance(post.get("public_metrics"), dict) else {}
            mention = Mention(
                source_id=source.id,
                content_type="social_post",
                business_category=decision.category,
                business_relevance_score=decision.score,
                business_summary=decision.summary,
                display_in_marketing=decision.display_in_marketing,
                quality_flags=decision.quality_flags,
                parent_mention_id=None,
                pipeline_run_id=pipeline.id,
                external_id=external_id,
                url=url,
                title=text[:300],
                raw_text=text,
                clean_text=None,
                author_name=str(author.get("name") or "") or None,
                author_handle=f"@{username}" if username else None,
                published_at=parse_dt(post.get("created_at")),
                collected_at=utc_now(),
                detected_language=str(post.get("lang") or detect_basic_language(text)),
                country=None,
                city=None,
                content_hash=content_hash,
                engagement={
                    "likes": int(metrics.get("like_count") or 0),
                    "replies": int(metrics.get("reply_count") or 0),
                    "reposts": int(metrics.get("retweet_count") or 0),
                    "quotes": int(metrics.get("quote_count") or 0),
                },
                raw_payload={**post, "author": author, "_collection": {"aggregator": "X API", "include_in_reputation": True}},
                processing_status="new",
            )
            session.add(mention)
            session.flush()
            ensure_organization_links(
                session=session,
                mention=mention,
                detected_names=classification["organizations"],
                organizations=organizations,
                primary_name="ARMA",
                include_in_reputation=True,
                detection_method="x_api_text_matching",
                relevance_score=max(0.75, decision.score),
            )
            created += 1

        pipeline.status = "completed"
        pipeline.finished_at = utc_now()
        pipeline.items_received = len(payload.get("data") or [])
        pipeline.items_created = created
        pipeline.statistics = {"query": X_QUERY, "created": created, "ignored": ignored}
        session.commit()
        print(f"Collecte X API terminée : {created} post(s) créé(s), {ignored} ignoré(s).")
    finally:
        session.close()


if __name__ == "__main__":
    collect_x_api_posts()
