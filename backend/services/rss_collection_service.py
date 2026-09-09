from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.collectors.rss_client import RSSClient
from backend.database.connection import SessionLocal
from backend.database.models import (
    Mention,
    MentionOrganization,
    MentionTopic,
    Organization,
    PipelineRun,
    Source,
    Topic,
)
from backend.services.rss_relevance_service import (
    ORGANIZATION_KEYWORDS,
    SECTOR_TOPIC_KEYWORDS,
    classify_article,
    normalize_text,
)


MAX_RESULTS_PER_FEED = 50


def utc_now() -> datetime:
    """
    Retourne la date et l'heure actuelles en UTC.
    """

    return datetime.now(timezone.utc)


def clean_value(value: Any) -> str:
    """
    Nettoie un texte provenant d'un flux RSS.
    """

    if value is None:
        return ""

    text = html.unescape(str(value))

    # Supprimer les éventuelles balises HTML.
    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    # Supprimer les espaces répétés.
    return " ".join(text.split())


def canonicalize_url(value: Any) -> str:
    """
    Normalise une URL pour faciliter la détection
    des doublons.
    """

    url = clean_value(value)

    if not url:
        return ""

    try:
        parts = urlsplit(url)

        return urlunsplit(
            (
                parts.scheme.lower(),
                parts.netloc.lower(),
                parts.path.rstrip("/"),
                parts.query,
                "",
            )
        )

    except ValueError:
        return url


def create_external_id(
    article: dict[str, Any],
) -> str:
    """
    Crée un identifiant stable à partir de l'URL.
    """

    link = canonicalize_url(
        article.get("link")
        or article.get("url")
    )

    title = clean_value(
        article.get("title")
    )

    identifying_value = link or title

    return hashlib.sha256(
        identifying_value.encode("utf-8")
    ).hexdigest()


def create_content_hash(
    article: dict[str, Any],
) -> str:
    """
    Crée une empreinte du contenu pour détecter
    un même article dans plusieurs flux RSS.
    """

    title = normalize_text(
        article.get("title")
    )

    body = normalize_text(
        get_article_text(article)
    )

    hash_content = f"{title}\n{body}"

    return hashlib.sha256(
        hash_content.encode("utf-8")
    ).hexdigest()


def get_article_text(
    article: dict[str, Any],
) -> str:
    """
    Construit le texte enregistré dans la table mentions.
    """

    title = clean_value(
        article.get("title")
    )

    body = ""

    for field_name in (
        "snippet",
        "summary",
        "description",
        "content",
    ):
        field_value = clean_value(
            article.get(field_name)
        )

        if field_value:
            body = field_value
            break

    if title and body:
        if normalize_text(title) != normalize_text(body):
            return f"{title}\n\n{body}"

    return body or title


def parse_published_at(
    article: dict[str, Any],
) -> datetime | None:
    """
    Convertit la date RSS en objet datetime.
    """

    value = (
        article.get("published_at")
        or article.get("published")
        or article.get("date")
        or article.get("updated")
    )

    if value is None:
        return None

    if isinstance(value, datetime):
        parsed_date = value

    elif isinstance(value, str):
        date_text = value.strip()

        if not date_text:
            return None

        try:
            parsed_date = datetime.fromisoformat(
                date_text.replace(
                    "Z",
                    "+00:00",
                )
            )

        except ValueError:
            try:
                parsed_date = parsedate_to_datetime(
                    date_text
                )

            except (TypeError, ValueError):
                return None

    else:
        return None

    if parsed_date.tzinfo is None:
        parsed_date = parsed_date.replace(
            tzinfo=timezone.utc
        )

    return parsed_date


def make_json_safe(value: Any) -> Any:
    """
    Transforme les valeurs en données compatibles
    avec PostgreSQL JSONB.
    """

    if value is None:
        return None

    if isinstance(
        value,
        (str, int, float, bool),
    ):
        return value

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            str(key): make_json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [
            make_json_safe(item)
            for item in value
        ]

    return str(value)


def get_rss_sources(
    session: Session,
) -> list[Source]:
    """
    Récupère les sources RSS actives.
    """

    sources = session.scalars(
        select(Source)
        .where(Source.is_active.is_(True))
        .order_by(Source.id)
    ).all()

    return [
        source
        for source in sources
        if (
            source.configuration or {}
        ).get("collection_method") == "rss"
    ]


def get_target_organizations(
    session: Session,
) -> dict[str, Organization]:
    """
    Récupère ARMA et les concurrents dans PostgreSQL.
    """

    organization_names = list(
        ORGANIZATION_KEYWORDS.keys()
    )

    organizations = session.scalars(
        select(Organization).where(
            Organization.name.in_(
                organization_names
            ),
            Organization.is_active.is_(True),
        )
    ).all()

    organizations_by_name = {
        organization.name: organization
        for organization in organizations
    }

    missing_names = [
        name
        for name in organization_names
        if name not in organizations_by_name
    ]

    if missing_names:
        raise RuntimeError(
            "Organisations absentes de PostgreSQL : "
            + ", ".join(missing_names)
        )

    return organizations_by_name


def get_target_topics(
    session: Session,
) -> dict[str, Topic]:
    """
    Récupère les thèmes sectoriels utilisés par
    le classificateur RSS.
    """

    topic_slugs = list(
        SECTOR_TOPIC_KEYWORDS.keys()
    )

    topics = session.scalars(
        select(Topic).where(
            Topic.slug.in_(topic_slugs),
            Topic.is_active.is_(True),
        )
    ).all()

    topics_by_slug = {
        topic.slug: topic
        for topic in topics
    }

    missing_slugs = [
        slug
        for slug in topic_slugs
        if slug not in topics_by_slug
    ]

    if missing_slugs:
        raise RuntimeError(
            "Thèmes absents de PostgreSQL : "
            + ", ".join(missing_slugs)
        )

    return topics_by_slug


def mention_already_exists(
    session: Session,
    source_id: int,
    external_id: str,
    content_hash: str,
) -> bool:
    """
    Vérifie si un article est déjà enregistré.
    """

    mention_id = session.scalar(
        select(Mention.id)
        .where(
            or_(
                Mention.content_hash
                == content_hash,
                (
                    (Mention.source_id == source_id)
                    & (
                        Mention.external_id
                        == external_id
                    )
                ),
            )
        )
        .limit(1)
    )

    return mention_id is not None


def create_pipeline_run(
    session: Session,
    source: Source,
    feed_count: int,
) -> PipelineRun:
    """
    Crée une exécution du pipeline pour une source RSS.
    """

    pipeline_run = PipelineRun(
        run_type="rss_collection",
        source_id=source.id,
        watch_query_id=None,
        status="running",
        started_at=utc_now(),
        finished_at=None,
        items_received=0,
        items_created=0,
        items_duplicated=0,
        error_message=None,
        statistics={
            "source_name": source.name,
            "feed_count": feed_count,
            "max_results_per_feed": (
                MAX_RESULTS_PER_FEED
            ),
        },
    )

    session.add(pipeline_run)
    session.commit()
    session.refresh(pipeline_run)

    return pipeline_run


def mark_pipeline_failed(
    session: Session,
    pipeline_run_id: int,
    error: Exception,
) -> None:
    """
    Marque une collecte comme échouée.
    """

    session.rollback()

    pipeline_run = session.get(
        PipelineRun,
        pipeline_run_id,
    )

    if pipeline_run is None:
        return

    pipeline_run.status = "failed"
    pipeline_run.finished_at = utc_now()
    pipeline_run.error_message = str(error)

    session.commit()


def create_mention(
    article: dict[str, Any],
    source: Source,
    pipeline_run: PipelineRun,
    feed: dict[str, Any],
    classification: dict[str, Any],
) -> Mention | None:
    """
    Transforme un article RSS en Mention.
    """

    title = clean_value(
        article.get("title")
    )

    raw_text = get_article_text(article)

    if not raw_text:
        return None

    link = canonicalize_url(
        article.get("link")
        or article.get("url")
    )

    language = clean_value(
        feed.get("language")
    ) or None

    raw_payload = make_json_safe(
        {
            **article,
            "_collection": {
                "channel": "rss",
                "source_id": source.id,
                "source_name": source.name,
                "feed_name": feed.get("name"),
                "feed_url": feed.get("url"),
                "content_scope": classification.get(
                    "content_scope"
                ),
                "organizations": classification.get(
                    "organizations",
                    [],
                ),
                "sector_topics": classification.get(
                    "sector_topics",
                    [],
                ),
                "matched_sector_keywords": (
                    classification.get(
                        "matched_sector_keywords",
                        {},
                    )
                ),
            },
        }
    )

    return Mention(
        source_id=source.id,
        pipeline_run_id=pipeline_run.id,
        external_id=create_external_id(
            article
        ),
        url=link or None,
        title=title[:1000] if title else None,
        raw_text=raw_text,
        clean_text=None,
        author_name=(
            clean_value(article.get("author"))
            or source.name
        )[:300],
        author_handle=None,
        published_at=parse_published_at(
            article
        ),
        collected_at=utc_now(),
        detected_language=language,
        country="MA",
        city=None,
        content_hash=create_content_hash(
            article
        ),
        engagement={},
        raw_payload=raw_payload,
        processing_status="new",
    )


def collect_rss_mentions() -> None:
    """
    Collecte les flux RSS et enregistre :
    - les mentions directes d'ARMA ou des concurrents ;
    - les actualités utiles au secteur de la propreté.
    """

    session = SessionLocal()
    rss_client = RSSClient()

    global_received = 0
    global_created = 0
    global_duplicated = 0
    global_ignored = 0
    global_reputation = 0
    global_sector = 0
    global_both = 0
    global_errors = 0

    try:
        rss_sources = get_rss_sources(
            session
        )

        organizations_by_name = (
            get_target_organizations(session)
        )

        topics_by_slug = get_target_topics(
            session
        )

        print("DÉBUT DE LA COLLECTE RSS")
        print("=" * 70)
        print(
            f"Sources RSS trouvées : "
            f"{len(rss_sources)}"
        )

        for source in rss_sources:
            configuration = (
                source.configuration or {}
            )

            feeds = configuration.get(
                "feeds",
                [],
            )

            pipeline_run = create_pipeline_run(
                session=session,
                source=source,
                feed_count=len(feeds),
            )

            pipeline_run_id = pipeline_run.id

            items_received = 0
            items_created = 0
            items_duplicated = 0
            items_ignored = 0
            items_reputation = 0
            items_sector = 0
            items_both = 0
            feed_errors: list[str] = []

            print("\n" + "=" * 70)
            print(f"Source : {source.name}")
            print(
                f"Pipeline : {pipeline_run_id}"
            )

            try:
                for feed in feeds:
                    feed_name = clean_value(
                        feed.get("name")
                    ) or "Flux sans nom"

                    feed_url = clean_value(
                        feed.get("url")
                    )

                    print(
                        f"\nFlux : {feed_name}"
                    )

                    if not feed_url:
                        error_message = (
                            f"{feed_name} : URL absente"
                        )

                        feed_errors.append(
                            error_message
                        )

                        global_errors += 1
                        print(error_message)
                        continue

                    try:
                        articles = rss_client.fetch(
                            feed_url,
                            max_results=(
                                MAX_RESULTS_PER_FEED
                            ),
                        )

                    except Exception as error:
                        error_message = (
                            f"{feed_name} : "
                            f"{type(error).__name__}: "
                            f"{error}"
                        )

                        feed_errors.append(
                            error_message
                        )

                        global_errors += 1

                        print(
                            f"Erreur du flux : "
                            f"{error_message}"
                        )

                        continue

                    items_received += len(
                        articles
                    )

                    global_received += len(
                        articles
                    )

                    print(
                        f"Articles reçus : "
                        f"{len(articles)}"
                    )

                    for article in articles:
                        classification = (
                            classify_article(article)
                        )

                        content_scope = str(
                            classification.get(
                                "content_scope",
                                "irrelevant",
                            )
                        )

                        mentioned_names = list(
                            classification.get(
                                "organizations",
                                [],
                            )
                        )

                        sector_topic_slugs = list(
                            classification.get(
                                "sector_topics",
                                [],
                            )
                        )

                        if content_scope == "irrelevant":
                            items_ignored += 1
                            global_ignored += 1
                            continue

                        external_id = (
                            create_external_id(
                                article
                            )
                        )

                        content_hash = (
                            create_content_hash(
                                article
                            )
                        )

                        if mention_already_exists(
                            session=session,
                            source_id=source.id,
                            external_id=external_id,
                            content_hash=content_hash,
                        ):
                            items_duplicated += 1
                            global_duplicated += 1

                            print(
                                "Doublon ignoré : "
                                + clean_value(
                                    article.get(
                                        "title"
                                    )
                                )
                            )

                            continue

                        mention = create_mention(
                            article=article,
                            source=source,
                            pipeline_run=pipeline_run,
                            feed=feed,
                            classification=classification,
                        )

                        if mention is None:
                            items_ignored += 1
                            global_ignored += 1
                            continue

                        session.add(mention)
                        session.flush()

                        for index, name in enumerate(
                            mentioned_names
                        ):
                            organization = (
                                organizations_by_name[
                                    name
                                ]
                            )

                            organization_link = (
                                MentionOrganization(
                                    mention_id=mention.id,
                                    organization_id=(
                                        organization.id
                                    ),
                                    relevance_score=1.0,
                                    is_primary=index == 0,
                                    detection_method=(
                                        "alias_matching"
                                    ),
                                )
                            )

                            session.add(
                                organization_link
                            )

                        for index, slug in enumerate(
                            sector_topic_slugs
                        ):
                            topic = topics_by_slug[slug]

                            topic_link = MentionTopic(
                                mention_id=mention.id,
                                topic_id=topic.id,
                                confidence=1.0,
                                is_primary=index == 0,
                                detection_method=(
                                    "keyword_matching"
                                ),
                            )

                            session.add(topic_link)

                        session.flush()

                        items_created += 1
                        global_created += 1

                        if content_scope == "reputation":
                            items_reputation += 1
                            global_reputation += 1
                        elif content_scope == "sector":
                            items_sector += 1
                            global_sector += 1
                        elif content_scope == "both":
                            items_both += 1
                            global_both += 1

                        print(
                            "\nContenu RSS ajouté"
                        )
                        print(
                            f"Titre : "
                            f"{mention.title}"
                        )
                        print(
                            f"Catégorie : "
                            f"{content_scope}"
                        )
                        print(
                            "Organisation(s) : "
                            + (
                                ", ".join(
                                    mentioned_names
                                )
                                or "Aucune"
                            )
                        )
                        print(
                            "Thème(s) : "
                            + (
                                ", ".join(
                                    sector_topic_slugs
                                )
                                or "Aucun"
                            )
                        )

                current_pipeline = session.get(
                    PipelineRun,
                    pipeline_run_id,
                )

                if current_pipeline is None:
                    raise RuntimeError(
                        "Pipeline RSS introuvable."
                    )

                all_feeds_failed = (
                    bool(feeds)
                    and len(feed_errors)
                    == len(feeds)
                )

                current_pipeline.status = (
                    "failed"
                    if all_feeds_failed
                    else "completed"
                )

                current_pipeline.finished_at = (
                    utc_now()
                )

                current_pipeline.items_received = (
                    items_received
                )

                current_pipeline.items_created = (
                    items_created
                )

                current_pipeline.items_duplicated = (
                    items_duplicated
                )

                current_pipeline.error_message = (
                    "; ".join(feed_errors)
                    if all_feeds_failed
                    else None
                )

                current_pipeline.statistics = {
                    "source_name": source.name,
                    "feed_count": len(feeds),
                    "max_results_per_feed": (
                        MAX_RESULTS_PER_FEED
                    ),
                    "items_received": (
                        items_received
                    ),
                    "items_created": (
                        items_created
                    ),
                    "items_duplicated": (
                        items_duplicated
                    ),
                    "items_ignored": (
                        items_ignored
                    ),
                    "reputation_only": (
                        items_reputation
                    ),
                    "sector_only": items_sector,
                    "both": items_both,
                    "feed_errors": feed_errors,
                }

                session.commit()

                print(
                    f"\nFin de {source.name} : "
                    f"{items_created} contenu(s) "
                    "ajouté(s)."
                )
                print(
                    "  Réputation uniquement : "
                    f"{items_reputation}"
                )
                print(
                    "  Secteur uniquement     : "
                    f"{items_sector}"
                )
                print(
                    "  Entreprise + secteur   : "
                    f"{items_both}"
                )

            except Exception as error:
                mark_pipeline_failed(
                    session=session,
                    pipeline_run_id=(
                        pipeline_run_id
                    ),
                    error=error,
                )

                global_errors += 1

                print(
                    f"\nÉchec de {source.name} : "
                    f"{error}"
                )

        print("\n" + "=" * 70)
        print("RÉSUMÉ GLOBAL")
        print(
            f"Articles reçus      : "
            f"{global_received}"
        )
        print(
            f"Contenus ajoutés    : "
            f"{global_created}"
        )
        print(
            f"Réputation seule    : "
            f"{global_reputation}"
        )
        print(
            f"Secteur seul        : "
            f"{global_sector}"
        )
        print(
            f"Entreprise + secteur: "
            f"{global_both}"
        )
        print(
            f"Doublons ignorés    : "
            f"{global_duplicated}"
        )
        print(
            f"Articles non liés   : "
            f"{global_ignored}"
        )
        print(
            f"Erreurs             : "
            f"{global_errors}"
        )

    finally:
        session.close()


if __name__ == "__main__":
    collect_rss_mentions()