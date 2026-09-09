from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.collectors.serper_client import SerperClient
from backend.database.connection import SessionLocal
from backend.database.models import (
    PipelineRun,
    WatchQuery,
)
from backend.services.collection_service import (
    MAX_RESULTS,
    clean_text,
    create_content_hash,
    create_external_id,
    create_mention,
    create_pipeline_run,
    get_serper_source,
    mark_pipeline_as_failed,
    mention_already_exists,
    utc_now,
)


# Première requête utilisée pour tester le canal Web.
WEB_QUERY_TO_COLLECT = "ARMA Environnement Maroc"


def get_web_watch_query(
    session: Session,
) -> WatchQuery:
    """
    Récupère dans PostgreSQL la requête utilisée
    pour le premier test de collecte Web.
    """

    watch_query = session.scalar(
        select(WatchQuery).where(
            WatchQuery.query_text == WEB_QUERY_TO_COLLECT,
            WatchQuery.is_active.is_(True),
        )
    )

    if watch_query is None:
        raise RuntimeError(
            "La requête Web est absente de la base : "
            f"{WEB_QUERY_TO_COLLECT}"
        )

    return watch_query


def collect_serper_web() -> None:
    """
    Effectue une recherche Web avec Serper.

    Les résultats sont :
    - normalisés ;
    - comparés aux mentions existantes ;
    - enregistrés dans PostgreSQL ;
    - associés à une exécution du pipeline.
    """

    session = SessionLocal()
    pipeline_run_id: int | None = None

    try:
        print("Début de la collecte Web Serper...")

        # 1. Récupérer la source Serper.
        source = get_serper_source(session)

        # 2. Récupérer la requête de veille.
        watch_query = get_web_watch_query(session)

        query_text = watch_query.query_text
        language = watch_query.language or "fr"

        filters = watch_query.filters or {}

        country = str(
            filters.get("country", "ma")
        ).lower()

        print(f"Requête : {query_text}")
        print(f"Langue : {language}")
        print(f"Pays : {country}")
        print("Canal : Web")

        # 3. Créer le pipeline Web.
        pipeline_run = create_pipeline_run(
            session=session,
            source=source,
            watch_query=watch_query,
            run_type="serper_web_collection",
            requested_results=MAX_RESULTS,
        )

        pipeline_run_id = pipeline_run.id

        print(
            "Pipeline Web créé avec l'identifiant "
            f"{pipeline_run_id}."
        )

        # 4. Appeler l'endpoint Web de Serper.
        client = SerperClient()

        results = client.search_web(
            query=query_text,
            language=language,
            country=country,
            num=MAX_RESULTS,
        )

        # Par sécurité, conserver seulement
        # le nombre maximal demandé.
        results = results[:MAX_RESULTS]

        items_received = len(results)
        items_created = 0
        items_duplicated = 0
        items_ignored = 0

        print(
            f"Nombre de résultats Web reçus : "
            f"{items_received}"
        )

        # 5. Parcourir les résultats.
        for result in results:
            if not isinstance(result, dict):
                items_ignored += 1
                print("Résultat Web invalide ignoré.")
                continue

            title = (
                clean_text(result.get("title"))
                or "Sans titre"
            )

            external_id = create_external_id(result)
            content_hash = create_content_hash(result)

            # Vérifier si la page existe déjà,
            # y compris si elle avait été trouvée par News.
            already_exists = mention_already_exists(
                session=session,
                source_id=source.id,
                external_id=external_id,
                content_hash=content_hash,
            )

            if already_exists:
                items_duplicated += 1

                print(
                    f"Doublon Web ignoré : {title}"
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

                print(
                    f"Résultat Web vide ignoré : {title}"
                )

                continue

            session.add(mention)
            session.flush()

            items_created += 1

            print(
                f"Mention Web ajoutée : {title}"
            )

        # 6. Mettre à jour les informations du pipeline.
        current_pipeline = session.get(
            PipelineRun,
            pipeline_run_id,
        )

        if current_pipeline is None:
            raise RuntimeError(
                "Impossible de retrouver le pipeline Web."
            )

        current_pipeline.status = "completed"
        current_pipeline.finished_at = utc_now()
        current_pipeline.items_received = items_received
        current_pipeline.items_created = items_created
        current_pipeline.items_duplicated = items_duplicated
        current_pipeline.error_message = None

        current_pipeline.statistics = {
            "query": query_text,
            "language": language,
            "country": country,
            "channel": "web",
            "requested_results": MAX_RESULTS,
            "received_results": items_received,
            "created_results": items_created,
            "duplicated_results": items_duplicated,
            "ignored_results": items_ignored,
        }

        # 7. Valider les nouvelles mentions.
        session.commit()

        print("\nCollecte Web terminée avec succès.")
        print(f"- Résultats reçus : {items_received}")
        print(f"- Mentions créées : {items_created}")
        print(f"- Doublons ignorés : {items_duplicated}")
        print(f"- Résultats ignorés : {items_ignored}")

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
            "\nErreur pendant la collecte Web : "
            f"{error}"
        )

        raise

    finally:
        session.close()


if __name__ == "__main__":
    collect_serper_web()