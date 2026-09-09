from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.collectors.serper_client import SerperClient
from backend.database.connection import SessionLocal
from backend.database.models import (
    Mention,
    PipelineRun,
    Source,
    WatchQuery,
)

from urllib.parse import urlsplit, urlunsplit

# Pour ce premier test, nous lançons une seule requête.
# Cela évite de consommer trop de crédits Serper.
QUERY_TO_COLLECT = "ARMA Environnement Maroc"

# Nombre maximal de résultats enregistrés.
MAX_RESULTS = 5


def utc_now() -> datetime:
    """
    Retourne la date et l'heure actuelles en UTC.
    """

    return datetime.now(timezone.utc)


def clean_text(value: Any) -> str:
    """
    Nettoie un texte reçu depuis Serper.

    Cette fonction :
    - transforme la valeur en texte ;
    - supprime les espaces inutiles ;
    - remplace plusieurs espaces par un seul.
    """

    if value is None:
        return ""

    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)

    return text

def normalize_for_hash(value: Any) -> str:
    """
    Normalise un texte pour détecter les doublons.

    Les majuscules, la ponctuation et les espaces
    multiples ne sont pas pris en compte.
    """

    text = clean_text(value).casefold()

    # Remplacer la ponctuation par des espaces.
    text = re.sub(
        r"[^\w\s]",
        " ",
        text,
        flags=re.UNICODE,
    )

    # Remplacer plusieurs espaces par un seul.
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def canonicalize_url(value: Any) -> str:
    """
    Normalise une URL.

    Exemple :
    https://www.site.com/article/?utm_source=google

    devient :
    https://site.com/article
    """

    url = clean_text(value)

    if not url:
        return ""

    try:
        parts = urlsplit(url)

        hostname = parts.netloc.casefold()

        if hostname.startswith("www."):
            hostname = hostname[4:]

        path = re.sub(r"/+", "/", parts.path)
        path = path.rstrip("/")

        return urlunsplit(
            (
                "https",
                hostname,
                path,
                "",
                "",
            )
        )

    except ValueError:
        return url

def create_external_id(
    result: dict[str, Any],
) -> str:
    """
    Crée un identifiant stable à partir de l'URL.

    Les paramètres publicitaires ou de suivi présents
    dans l'URL sont ignorés.
    """

    canonical_url = canonicalize_url(
        result.get("link")
    )

    normalized_title = normalize_for_hash(
        result.get("title")
    )

    normalized_snippet = normalize_for_hash(
        result.get("snippet")
    )

    value_to_hash = (
        canonical_url
        or normalized_title
        or normalized_snippet
    )

    return hashlib.sha256(
        value_to_hash.encode("utf-8")
    ).hexdigest()


def create_content_hash(
    result: dict[str, Any],
) -> str:
    """
    Crée une empreinte à partir du titre normalisé.

    Le résumé Serper peut changer entre deux recherches.
    Il ne doit donc pas être utilisé pour identifier
    l'article lorsqu'un titre est disponible.
    """

    normalized_title = normalize_for_hash(
        result.get("title")
    )

    normalized_snippet = normalize_for_hash(
        result.get("snippet")
    )

    content = (
        normalized_title
        or normalized_snippet
    )

    return hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()


def get_serper_source(session: Session) -> Source:
    """
    Récupère la source Serper dans PostgreSQL.
    """

    source = session.scalar(
        select(Source).where(
            Source.name == "Serper",
            Source.is_active.is_(True),
        )
    )

    if source is None:
        raise RuntimeError(
            "La source Serper est absente de la table sources. "
            "Relance d'abord le fichier seed.py."
        )

    return source


def get_watch_query(session: Session) -> WatchQuery:
    """
    Récupère la requête de veille utilisée pour ce test.
    """

    watch_query = session.scalar(
        select(WatchQuery).where(
            WatchQuery.query_text == QUERY_TO_COLLECT,
            WatchQuery.is_active.is_(True),
        )
    )

    if watch_query is None:
        raise RuntimeError(
            "La requête de veille est absente de la base : "
            f"{QUERY_TO_COLLECT}"
        )

    return watch_query


def mention_already_exists(
    session: Session,
    source_id: int,
    external_id: str,
    content_hash: str,
) -> bool:
    """
    Vérifie si l'article existe déjà.

    Deux vérifications sont utilisées :
    - même identifiant externe pour la même source ;
    - même empreinte de contenu.
    """

    existing_mention_id = session.scalar(
        select(Mention.id)
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

    return existing_mention_id is not None


def create_mention(
    result: dict[str, Any],
    source: Source,
    pipeline_run: PipelineRun,
    language: str,
    country: str,
) -> Mention | None:
    """
    Transforme un résultat Serper en objet Mention.
    """

    title = clean_text(result.get("title"))
    snippet = clean_text(result.get("snippet"))
    link = clean_text(result.get("link"))
    publisher = clean_text(result.get("source"))

    # raw_text est obligatoire dans la table mentions.
    raw_text = snippet or title

    # Un résultat sans titre et sans résumé ne sera pas enregistré.
    if not raw_text:
        return None

    external_id = create_external_id(result)
    content_hash = create_content_hash(result)

    mention = Mention(
        source_id=source.id,
        pipeline_run_id=pipeline_run.id,
        external_id=external_id,
        url=link or None,
        title=title[:1000] if title else None,
        raw_text=raw_text,
        clean_text=None,
        author_name=publisher[:300] if publisher else None,
        author_handle=None,

        # Pour le moment, la date Serper reste dans raw_payload.
        # Nous la convertirons plus tard avec le module de traitement.
        published_at=None,

        collected_at=utc_now(),
        detected_language=language,
        country=country.upper(),
        city=None,
        content_hash=content_hash,
        engagement={},
        raw_payload=result,
        processing_status="new",
    )

    return mention


def create_pipeline_run(
    session: Session,
    source: Source,
    watch_query: WatchQuery,
    run_type: str = "serper_news_collection",
    requested_results: int = MAX_RESULTS,
) -> PipelineRun:
    """
    Crée une nouvelle exécution du pipeline.

    run_type permet de distinguer :
    - la collecte News ;
    - la collecte Web ;
    - les futurs collecteurs.
    """

    pipeline_run = PipelineRun(
        run_type=run_type,
        source_id=source.id,
        watch_query_id=watch_query.id,
        status="running",
        started_at=utc_now(),
        finished_at=None,
        items_received=0,
        items_created=0,
        items_duplicated=0,
        error_message=None,
        statistics={
            "query": watch_query.query_text,
            "requested_results": requested_results,
            "run_type": run_type,
        },
    )

    session.add(pipeline_run)
    session.commit()
    session.refresh(pipeline_run)

    return pipeline_run


def mark_pipeline_as_failed(
    session: Session,
    pipeline_run_id: int,
    error: Exception,
) -> None:
    """
    Enregistre l'échec d'une exécution du pipeline.
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


def collect_serper_news() -> None:
    """
    Lance une collecte Serper et enregistre
    les résultats dans PostgreSQL.
    """

    session = SessionLocal()
    pipeline_run_id: int | None = None

    try:
        print("Début de la collecte Serper...")

        # 1. Récupérer la source Serper.
        source = get_serper_source(session)

        # 2. Récupérer la requête de veille.
        watch_query = get_watch_query(session)

        query_text = watch_query.query_text
        language = watch_query.language or "fr"

        filters = watch_query.filters or {}
        country = str(filters.get("country", "ma")).lower()

        print(f"Requête : {query_text}")
        print(f"Langue : {language}")
        print(f"Pays : {country}")

        # 3. Créer l'exécution du pipeline.
        pipeline_run = create_pipeline_run(
            session=session,
            source=source,
            watch_query=watch_query,
        )

        pipeline_run_id = pipeline_run.id

        print(
            f"Pipeline créé avec l'identifiant "
            f"{pipeline_run_id}."
        )

        # 4. Appeler Serper.
        client = SerperClient()

        results = client.search_news(
            query=query_text,
            language=language,
            country=country,
            num=MAX_RESULTS,
        )

        # Même si Serper retourne plus de résultats,
        # nous conservons seulement les cinq premiers.
        results = results[:MAX_RESULTS]

        items_received = len(results)
        items_created = 0
        items_duplicated = 0
        items_ignored = 0

        print(
            f"Nombre de résultats reçus : "
            f"{items_received}"
        )

        # 5. Parcourir les résultats.
        for result in results:
            external_id = create_external_id(result)
            content_hash = create_content_hash(result)

            already_exists = mention_already_exists(
                session=session,
                source_id=source.id,
                external_id=external_id,
                content_hash=content_hash,
            )

            if already_exists:
                items_duplicated += 1

                print(
                    "Doublon ignoré : "
                    f"{clean_text(result.get('title'))}"
                )

                continue

            mention = create_mention(
                result=result,
                source=source,
                pipeline_run=pipeline_run,
                language=language,
                country=country,
            )

            if mention is None:
                items_ignored += 1
                print("Résultat vide ignoré.")
                continue

            session.add(mention)

            # Le flush envoie immédiatement l'insertion
            # dans la transaction sans faire le commit final.
            session.flush()

            items_created += 1

            print(
                "Mention ajoutée : "
                f"{mention.title or 'Sans titre'}"
            )

        # 6. Mettre à jour le pipeline.
        current_pipeline_run = session.get(
            PipelineRun,
            pipeline_run_id,
        )

        if current_pipeline_run is None:
            raise RuntimeError(
                "Impossible de retrouver le pipeline créé."
            )

        current_pipeline_run.status = "completed"
        current_pipeline_run.finished_at = utc_now()
        current_pipeline_run.items_received = items_received
        current_pipeline_run.items_created = items_created
        current_pipeline_run.items_duplicated = items_duplicated
        current_pipeline_run.error_message = None
        current_pipeline_run.statistics = {
            "query": query_text,
            "language": language,
            "country": country,
            "requested_results": MAX_RESULTS,
            "received_results": items_received,
            "created_results": items_created,
            "duplicated_results": items_duplicated,
            "ignored_results": items_ignored,
        }

        # 7. Valider les mentions et le pipeline.
        session.commit()

        print("\nCollecte terminée avec succès.")
        print(f"- Résultats reçus : {items_received}")
        print(f"- Mentions créées : {items_created}")
        print(f"- Doublons ignorés : {items_duplicated}")
        print(f"- Résultats vides ignorés : {items_ignored}")

    except Exception as error:
        if pipeline_run_id is not None:
            mark_pipeline_as_failed(
                session=session,
                pipeline_run_id=pipeline_run_id,
                error=error,
            )
        else:
            session.rollback()

        print(
            "\nErreur pendant la collecte : "
            f"{error}"
        )

        raise

    finally:
        session.close()


if __name__ == "__main__":
    collect_serper_news()