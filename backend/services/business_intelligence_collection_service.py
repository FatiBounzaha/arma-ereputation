from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.collectors.serper_client import SerperClient
from backend.database.connection import SessionLocal
from backend.database.models import (
    Mention,
    Organization,
    PipelineRun,
    Source,
    WatchQuery,
)
from backend.processing.business_relevance import evaluate_business_relevance
from backend.services.collection_service import (
    clean_text,
    create_content_hash,
    create_external_id,
    create_pipeline_run,
    get_serper_source,
    mark_pipeline_as_failed,
    utc_now,
)
from backend.services.rss_relevance_service import classify_article
from backend.services.social_collection_service_v2 import (
    detect_basic_language,
    ensure_organization_links,
    parse_serper_date,
)


MAX_RESULTS_PER_QUERY = int(os.getenv("BI_MAX_RESULTS_PER_QUERY", "10"))
MIN_STORE_SCORE = float(os.getenv("BI_MIN_STORE_SCORE", "0.40"))


@dataclass(frozen=True)
class IntelligenceQuery:
    category: str
    query: str
    language: str = "fr"


# Requêtes conçues pour le POC Marketing : signaux concurrents,
# opportunités, réglementation et innovation sectorielle. Elles excluent
# volontairement les recherches générales de profils et de recrutement.
INTELLIGENCE_QUERIES: tuple[IntelligenceQuery, ...] = (
    IntelligenceQuery(
        "competitor",
        '("OZONE Environnement" OR "Averda Maroc" OR "Suez Maroc" OR "SOS NDD") '
        '(contrat OR marché OR appel d\'offres OR investissement OR résultats OR grève OR litige) '
        '(déchets OR propreté OR assainissement)',
    ),
    IntelligenceQuery(
        "opportunity",
        '("appel d\'offres" OR "marché public" OR "gestion déléguée" OR concession) '
        '("propreté urbaine" OR "collecte des déchets" OR assainissement) Maroc',
    ),
    IntelligenceQuery(
        "regulation",
        '(loi OR décret OR réglementation OR "tri à la source" OR "étude d\'impact") '
        '(déchets OR environnement OR assainissement) Maroc',
    ),
    IntelligenceQuery(
        "innovation",
        '(innovation OR digitalisation OR "smart city" OR "économie circulaire" OR recyclage '
        'OR "véhicules électriques") (déchets OR propreté OR assainissement) Maroc',
    ),
    IntelligenceQuery(
        "sector",
        '("propreté urbaine" OR "gestion des déchets" OR "traitement de l\'eau") '
        '(Casablanca OR Rabat OR Maroc)',
    ),
    IntelligenceQuery(
        "competitor",
        '("أوزون" OR "أفيردا" OR "سويز" OR "شركة SOS") '
        '(صفقة OR عقد OR إضراب OR استثمار OR نزاع) '
        '(النظافة OR النفايات OR التطهير)',
        language="ar",
    ),
    IntelligenceQuery(
        "opportunity",
        '("طلب عروض" OR "صفقة عمومية" OR "تدبير مفوض") '
        '(النظافة OR جمع النفايات OR التطهير السائل) المغرب',
        language="ar",
    ),
)


def get_or_create_query(session: Session, item: IntelligenceQuery) -> WatchQuery:
    query = session.scalar(
        select(WatchQuery).where(
            WatchQuery.organization_id.is_(None),
            WatchQuery.query_text == item.query,
        )
    )
    if query is not None:
        return query

    query = WatchQuery(
        organization_id=None,
        query_text=item.query,
        language=item.language,
        category=item.category,
        frequency="daily",
        filters={"country": "ma", "channel": "news", "business_intelligence": True},
        is_active=True,
    )
    session.add(query)
    session.flush()
    return query


def find_existing(session: Session, source_id: int, external_id: str, content_hash: str) -> Mention | None:
    return session.scalar(
        select(Mention)
        .where(
            or_(
                Mention.content_hash == content_hash,
                (Mention.source_id == source_id) & (Mention.external_id == external_id),
            )
        )
        .limit(1)
    )


def collect_one_intelligence_query(item: IntelligenceQuery, client: SerperClient) -> dict[str, Any]:
    session = SessionLocal()
    pipeline_run_id: int | None = None

    try:
        serper_source = get_serper_source(session)
        watch_query = get_or_create_query(session, item)
        pipeline = create_pipeline_run(
            session=session,
            source=serper_source,
            watch_query=watch_query,
            run_type="serper_business_intelligence",
            requested_results=MAX_RESULTS_PER_QUERY,
        )
        pipeline_run_id = pipeline.id

        print("\n" + "=" * 78)
        print(f"Catégorie : {item.category}")
        print(f"Requête   : {item.query}")

        results = client.search_news(
            query=item.query,
            language=item.language,
            country="ma",
            num=MAX_RESULTS_PER_QUERY,
        )[:MAX_RESULTS_PER_QUERY]

        organizations = {
            organization.name: organization
            for organization in session.scalars(
                select(Organization).where(Organization.is_active.is_(True))
            ).all()
        }

        counters = {"received": len(results), "created": 0, "updated": 0, "ignored": 0}
        ignored_reasons: dict[str, int] = {}

        for raw_result in results:
            if not isinstance(raw_result, dict):
                counters["ignored"] += 1
                continue

            result = dict(raw_result)
            classification = classify_article(result)
            decision = evaluate_business_relevance(
                result,
                organizations=classification["organizations"],
                sector_topics=classification["sector_topics"],
                source_name=str(result.get("source") or "Serper News"),
                query_category=item.category,
            )

            title = clean_text(result.get("title")) or "Sans titre"
            if decision.score < MIN_STORE_SCORE or not decision.category:
                counters["ignored"] += 1
                reason = decision.quality_flags[0] if decision.quality_flags else "low_business_relevance"
                ignored_reasons[reason] = ignored_reasons.get(reason, 0) + 1
                print(f"IGNORÉ [{decision.score:.2f}] : {title}")
                continue

            external_id = create_external_id(result)
            content_hash = create_content_hash(result)
            existing = find_existing(session, serper_source.id, external_id, content_hash)

            payload = dict(result)
            payload["_collection"] = {
                "channel": "news",
                "content_type": "news_article",
                "aggregator": "Serper",
                "query_category": item.category,
                "detected_organizations": classification["organizations"],
                "sector_topics": classification["sector_topics"],
                "business_relevance": decision.to_dict(),
            }

            if existing is None:
                raw_text = clean_text(result.get("snippet")) or title
                existing = Mention(
                    source_id=serper_source.id,
                    content_type="news_article",
                    business_category=decision.category,
                    business_relevance_score=decision.score,
                    business_summary=decision.summary or None,
                    display_in_marketing=decision.display_in_marketing,
                    quality_flags=decision.quality_flags,
                    parent_mention_id=None,
                    pipeline_run_id=pipeline.id,
                    external_id=external_id,
                    url=clean_text(result.get("link")) or None,
                    title=title[:1000],
                    raw_text=raw_text,
                    clean_text=None,
                    author_name=clean_text(result.get("source"))[:300] or None,
                    author_handle=None,
                    published_at=parse_serper_date(result.get("date")),
                    collected_at=utc_now(),
                    detected_language=detect_basic_language(raw_text),
                    country="MA",
                    city=None,
                    content_hash=content_hash,
                    engagement={},
                    raw_payload=payload,
                    processing_status="new",
                )
                session.add(existing)
                session.flush()
                counters["created"] += 1
                print(f"AJOUTÉ [{decision.category} {decision.score:.2f}] : {title}")
            else:
                # Une requête plus précise peut améliorer une ligne déjà trouvée.
                if (existing.business_relevance_score or 0.0) <= decision.score:
                    existing.business_category = decision.category
                    existing.business_relevance_score = decision.score
                    existing.business_summary = decision.summary or existing.business_summary
                    existing.display_in_marketing = decision.display_in_marketing
                    existing.quality_flags = decision.quality_flags
                    existing.raw_payload = payload
                counters["updated"] += 1
                print(f"DOUBLON QUALIFIÉ [{decision.score:.2f}] : {title}")

            if classification["organizations"]:
                ensure_organization_links(
                    session=session,
                    mention=existing,
                    detected_names=classification["organizations"],
                    organizations=organizations,
                    primary_name=classification["organizations"][0],
                    include_in_reputation=True,
                    detection_method="business_intelligence_matching",
                    relevance_score=decision.score,
                )

        current = session.get(PipelineRun, pipeline.id)
        current.status = "completed"
        current.finished_at = utc_now()
        current.items_received = counters["received"]
        current.items_created = counters["created"]
        current.items_duplicated = counters["updated"]
        current.statistics = {
            "category": item.category,
            "query": item.query,
            **counters,
            "ignored_reasons": ignored_reasons,
        }
        session.commit()
        return {"status": "completed", **counters}

    except Exception as error:
        if pipeline_run_id is not None:
            mark_pipeline_as_failed(session, pipeline_run_id, error)
        else:
            session.rollback()
        print(f"Erreur veille stratégique : {error}")
        return {"status": "failed", "error": str(error)}
    finally:
        session.close()


def collect_business_intelligence() -> None:
    """Collecte la veille utile à la vue Marketing Contenu."""

    print("DÉBUT DE LA VEILLE STRATÉGIQUE QUALIFIÉE")
    print("=" * 78)
    client = SerperClient()
    summaries = [collect_one_intelligence_query(item, client) for item in INTELLIGENCE_QUERIES]
    completed = [item for item in summaries if item.get("status") == "completed"]
    print("\nRÉSUMÉ VEILLE STRATÉGIQUE")
    print(f"Requêtes terminées : {len(completed)}/{len(summaries)}")
    print(f"Contenus ajoutés   : {sum(int(item.get('created', 0)) for item in completed)}")
    print(f"Contenus qualifiés : {sum(int(item.get('updated', 0)) for item in completed)}")
    print(f"Contenus ignorés   : {sum(int(item.get('ignored', 0)) for item in completed)}")


if __name__ == "__main__":
    collect_business_intelligence()
