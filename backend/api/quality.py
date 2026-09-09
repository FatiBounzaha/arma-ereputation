from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.deps import get_db_session
from backend.database.models import (
    Alert,
    FacebookReplyAudit,
    GeneratedPost,
    Mention,
    PipelineRun,
    ReputationSnapshot,
)
from backend.scoring.formulas import FORMULA_VERSION
from backend.services.facebook_screenshot_service import read_latest_capture_summary
from backend.services.facebook_comment_collection_service import comments_collection_status

router = APIRouter(prefix="/api/quality", tags=["quality"])


def _configured(name: str) -> bool:
    value = (os.getenv(name) or "").strip()
    return bool(value and not value.lower().startswith("your_") and value not in {"vXX.X", "..."})


@router.get("/status")
def read_quality_status(session: Session = Depends(get_db_session)) -> dict:
    """État de santé technique et métier, sans révéler les secrets."""

    now = datetime.now(timezone.utc)
    latest_mention = session.scalar(select(func.max(Mention.collected_at)))
    latest_run = session.scalar(
        select(PipelineRun)
        .where(PipelineRun.run_type == "n8n_daily_pipeline")
        .order_by(PipelineRun.started_at.desc())
        .limit(1)
    )

    latest_post_run_id = session.scalar(
        select(GeneratedPost.pipeline_run_id)
        .order_by(GeneratedPost.generated_at.desc())
        .limit(1)
    )
    latest_posts: list[GeneratedPost] = []
    if latest_post_run_id is not None:
        latest_posts = list(
            session.scalars(
                select(GeneratedPost)
                .where(GeneratedPost.pipeline_run_id == latest_post_run_id)
                .order_by(GeneratedPost.display_order)
            )
        )

    mention_counts = {
        content_type or "unknown": int(count)
        for content_type, count in session.execute(
            select(Mention.content_type, func.count(Mention.id)).group_by(Mention.content_type)
        ).all()
    }
    open_alerts = int(
        session.scalar(select(func.count(Alert.id)).where(Alert.status == "open")) or 0
    )
    high_open_alerts = int(
        session.scalar(
            select(func.count(Alert.id)).where(
                Alert.status == "open", Alert.severity == "high"
            )
        )
        or 0
    )
    pending_mentions = int(
        session.scalar(
            select(func.count(Mention.id)).where(
                Mention.processing_status.notin_(["processed", "completed"])
            )
        )
        or 0
    )
    latest_score = session.scalar(
        select(ReputationSnapshot)
        .where(ReputationSnapshot.formula_version == FORMULA_VERSION)
        .order_by(ReputationSnapshot.period_end.desc())
        .limit(1)
    )

    try:
        target_post_count = max(1, min(int(os.getenv("POST_TARGET_COUNT", "8")), 20))
    except ValueError:
        target_post_count = 8

    posts_quality_checked = sum(
        bool((post.extra_data or {}).get("quality_checked")) for post in latest_posts
    )
    fallback_posts = sum(
        bool((post.extra_data or {}).get("fallback_used") or (post.extra_data or {}).get("fallback"))
        for post in latest_posts
    )

    warnings: list[str] = []
    critical: list[str] = []
    if latest_mention is None:
        critical.append("Aucune mention collectée.")
    elif latest_mention < now - timedelta(days=2):
        warnings.append("La dernière collecte date de plus de 48 heures.")

    if latest_run is None:
        critical.append("Aucune exécution n8n quotidienne tracée.")
    else:
        if latest_run.status != "completed":
            warnings.append(f"Le dernier workflow n8n a le statut '{latest_run.status}'.")
        if latest_run.started_at and latest_run.started_at < now - timedelta(days=2):
            warnings.append("Le dernier workflow n8n date de plus de 48 heures.")
        failed_steps = [
            item.get("name")
            for item in (latest_run.statistics or {}).get("steps", [])
            if item.get("status") == "failed"
        ]
        if failed_steps:
            warnings.append("Étapes n8n en échec : " + ", ".join(str(item) for item in failed_steps))

    if len(latest_posts) < target_post_count:
        warnings.append(f"Le dernier run contient {len(latest_posts)}/{target_post_count} posts.")
    if latest_posts and posts_quality_checked < len(latest_posts):
        warnings.append(
            f"{len(latest_posts) - posts_quality_checked} post(s) sans marque de contrôle qualité V10.3."
        )
    if fallback_posts:
        warnings.append(f"{fallback_posts} post(s) ont utilisé le gabarit de secours.")
    if latest_score is None:
        warnings.append(f"Aucun score calculé avec la formule {FORMULA_VERSION}.")
    comments_connector = comments_collection_status()
    if not comments_connector.get("collection_available"):
        warnings.append(
            "Commentaires Facebook non connectés : configurez Apify ou les autorisations Meta."
        )

    total_mentions = int(session.scalar(select(func.count(Mention.id))) or 0)
    missing_publication_dates = int(session.scalar(select(func.count(Mention.id)).where(Mention.published_at.is_(None), Mention.manual_published_at.is_(None))) or 0)
    historical_cutoff = now - timedelta(days=90)
    historical_mentions = int(session.scalar(select(func.count(Mention.id)).where(func.coalesce(Mention.manual_published_at, Mention.published_at) < historical_cutoff)) or 0)
    excluded_marketing = int(session.scalar(select(func.count(Mention.id)).where(Mention.display_in_marketing.is_(False))) or 0)
    sensitive_routed = int(session.scalar(select(func.count(Mention.id)).where(Mention.business_category.in_(["procedure_judiciaire", "veille_concurrentielle_sensible", "risque_reputationnel"]))) or 0)
    replies_sent = int(session.scalar(select(func.count(FacebookReplyAudit.id)).where(FacebookReplyAudit.status == "sent")) or 0)
    demo_comments = int(session.scalar(select(func.count(Mention.id)).where(Mention.content_type == "social_comment", Mention.raw_payload["is_demo"].astext == "true")) or 0)
    real_comments = max(0, mention_counts.get("social_comment", 0) - demo_comments)
    blocked_posts = sum((post.extra_data or {}).get("claim_status") in {"unsupported", "blocked"} for post in latest_posts)
    facebook_screenshots = read_latest_capture_summary()
    if facebook_screenshots.get("status") in {"unavailable", "partial", "invalid_summary"}:
        warnings.append("Captures Facebook : " + str(facebook_screenshots.get("status")))
    overall_status = "fail" if critical else ("warning" if warnings else "pass")
    return {
        "status": overall_status,
        "checked_at": now,
        "latest_mention_at": latest_mention,
        "latest_pipeline_run": {
            "id": latest_run.id,
            "type": latest_run.run_type,
            "status": latest_run.status,
            "started_at": latest_run.started_at,
            "finished_at": latest_run.finished_at,
            "statistics": latest_run.statistics,
        }
        if latest_run
        else None,
        "mention_counts": mention_counts,
        "mentions_collected": total_mentions,
        "duplicates": int((latest_run.statistics or {}).get("duplicates", latest_run.items_duplicated or 0)) if latest_run else 0,
        "mentions_without_published_at": missing_publication_dates,
        "historical_contents": historical_mentions,
        "excluded_from_marketing": excluded_marketing,
        "sensitive_routed_to_reputation": sensitive_routed,
        "pending_mentions": pending_mentions,
        "alerts": {"open": open_alerts, "high_open": high_open_alerts},
        "posts": {
            "latest_count": len(latest_posts),
            "target_count": target_post_count,
            "quality_checked": posts_quality_checked,
            "fallback_count": fallback_posts,
            "blocked_by_claims": blocked_posts,
        },
        "reputation": {
            "formula_version": FORMULA_VERSION,
            "latest_period_start": latest_score.period_start if latest_score else None,
            "latest_period_end": latest_score.period_end if latest_score else None,
        },
        "connectors": {
            "serper": _configured("SERPER_API_KEY"),
            "claude": _configured("ANTHROPIC_API_KEY"),
            "meta": _configured("META_ACCESS_TOKEN") and _configured("META_GRAPH_VERSION"),
            "apify": _configured("APIFY_API_TOKEN"),
            "facebook_comments_provider": comments_connector.get("provider"),
            "x_api": _configured("X_BEARER_TOKEN"),
        },
        "facebook": {
            "real_comments": real_comments,
            "demo_comments": demo_comments,
            "collection_provider": comments_connector.get("provider"),
            "collection_available": comments_connector.get("collection_available", False),
            "replies_sent": replies_sent,
            "screenshot_status": facebook_screenshots.get("status"),
            "retained_posts": facebook_screenshots.get("count", 0),
            "screenshots_created": facebook_screenshots.get("captures", 0),
            "screenshot_run": facebook_screenshots.get("run"),
        },
        "critical": critical,
        "warnings": warnings,
    }
