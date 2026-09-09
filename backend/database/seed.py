import re
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.database.connection import SessionLocal
from backend.database.models import (
    Organization,
    OrganizationAlias,
    Source,
    Topic,
    WatchQuery,
)


def normalize_text(value: str) -> str:
    """
    Normalise un texte afin de comparer les alias.

    Exemples :
    "ARMA Environnement" -> "arma environnement"
    "SUEZ"               -> "suez"
    "Suez"               -> "suez"
    """

    value = unicodedata.normalize("NFKC", value)
    value = value.casefold().strip()

    # Conserve les lettres, les chiffres, les espaces,
    # le caractère "_" et le caractère "@".
    value = re.sub(r"[^\w\s@]", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def get_or_create_organization(
    session: Session,
    name: str,
    organization_type: str,
    website: str | None = None,
    description: str | None = None,
) -> Organization:
    """
    Récupère une organisation existante ou la crée.
    """

    organization = session.scalar(
        select(Organization).where(
            Organization.name == name
        )
    )

    if organization is not None:
        print(f"Organisation déjà présente : {name}")
        return organization

    organization = Organization(
        name=name,
        organization_type=organization_type,
        website=website,
        description=description,
        is_active=True,
    )

    session.add(organization)

    # Nécessaire pour récupérer organization.id.
    session.flush()

    print(f"Organisation ajoutée : {name}")

    return organization


def create_alias_if_missing(
    session: Session,
    organization: Organization,
    alias: str,
    language: str | None,
) -> None:
    """
    Ajoute un alias uniquement si sa forme normalisée
    n'existe pas déjà pour la même organisation.
    """

    normalized_alias = normalize_text(alias)

    existing_alias = session.scalar(
        select(OrganizationAlias).where(
            OrganizationAlias.organization_id == organization.id,
            OrganizationAlias.normalized_alias == normalized_alias,
        )
    )

    if existing_alias is not None:
        print(
            f"Alias déjà présent : "
            f"{organization.name} -> {alias}"
        )
        return

    new_alias = OrganizationAlias(
        organization_id=organization.id,
        alias=alias,
        normalized_alias=normalized_alias,
        language=language,
    )

    session.add(new_alias)

    # Rend immédiatement l'alias visible dans la transaction.
    # Un autre alias équivalent sera donc détecté.
    session.flush()

    print(f"Alias ajouté : {organization.name} -> {alias}")


def get_or_create_source(
    session: Session,
    name: str,
    source_type: str,
    base_url: str | None = None,
    reliability_weight: float = 1.0,
    configuration: dict | None = None,
) -> Source:
    """
    Récupère une source existante ou la crée.
    """

    source = session.scalar(
        select(Source).where(
            Source.name == name
        )
    )

    if source is not None:
        print(f"Source déjà présente : {name}")
        return source

    source = Source(
        name=name,
        source_type=source_type,
        base_url=base_url,
        reliability_weight=reliability_weight,
        configuration=configuration or {},
        is_active=True,
    )

    session.add(source)
    session.flush()

    print(f"Source ajoutée : {name}")

    return source


def create_topic_if_missing(
    session: Session,
    name: str,
    slug: str,
    description: str,
) -> Topic:
    """
    Récupère un thème existant ou le crée.
    """

    topic = session.scalar(
        select(Topic).where(
            Topic.slug == slug
        )
    )

    if topic is not None:
        print(f"Thème déjà présent : {name}")
        return topic

    topic = Topic(
        name=name,
        slug=slug,
        description=description,
        is_active=True,
    )

    session.add(topic)
    session.flush()

    print(f"Thème ajouté : {name}")

    return topic


def create_watch_query_if_missing(
    session: Session,
    query_text: str,
    category: str,
    organization: Organization | None = None,
    language: str = "fr",
    frequency: str = "daily",
    filters: dict | None = None,
) -> None:
    """
    Ajoute une requête de veille si elle n'existe pas déjà.
    """

    organization_id = (
        organization.id
        if organization is not None
        else None
    )

    existing_query = session.scalar(
        select(WatchQuery).where(
            WatchQuery.query_text == query_text,
            WatchQuery.organization_id == organization_id,
        )
    )

    if existing_query is not None:
        print(
            f"Requête déjà présente : {query_text}"
        )
        return

    new_query = WatchQuery(
        organization_id=organization_id,
        query_text=query_text,
        language=language,
        category=category,
        frequency=frequency,
        filters=filters or {},
        is_active=True,
    )

    session.add(new_query)
    session.flush()

    print(f"Requête de veille ajoutée : {query_text}")


def print_database_summary(session: Session) -> None:
    """
    Affiche le nombre total de données de référence.
    """

    organizations_count = session.scalar(
        select(func.count(Organization.id))
    )

    aliases_count = session.scalar(
        select(func.count(OrganizationAlias.id))
    )

    sources_count = session.scalar(
        select(func.count(Source.id))
    )

    topics_count = session.scalar(
        select(func.count(Topic.id))
    )

    queries_count = session.scalar(
        select(func.count(WatchQuery.id))
    )

    print("\nRésumé de la base :")
    print(f"- Organisations : {organizations_count}")
    print(f"- Alias : {aliases_count}")
    print(f"- Sources : {sources_count}")
    print(f"- Thèmes : {topics_count}")
    print(f"- Requêtes de veille : {queries_count}")


def seed_database() -> None:
    """
    Insère les données de référence du projet ARMA.

    La transaction est validée uniquement lorsque
    toutes les insertions réussissent.
    """

    session = SessionLocal()

    try:
        # =====================================================
        # 1. Organisations
        # =====================================================

        arma = get_or_create_organization(
            session=session,
            name="ARMA",
            organization_type="company",
            description=(
                "Entreprise principale surveillée "
                "par la plateforme."
            ),
        )

        ozone = get_or_create_organization(
            session=session,
            name="OZONE",
            organization_type="competitor",
            description=(
                "Concurrent d'ARMA dans la gestion "
                "environnementale."
            ),
        )

        averda = get_or_create_organization(
            session=session,
            name="Averda",
            organization_type="competitor",
            description=(
                "Concurrent international du secteur "
                "environnemental."
            ),
        )

        suez = get_or_create_organization(
            session=session,
            name="Suez Maroc",
            organization_type="competitor",
            description=(
                "Acteur du traitement de l'eau "
                "et de l'environnement."
            ),
        )

        sos = get_or_create_organization(
            session=session,
            name="SOS",
            organization_type="competitor",
            description=(
                "Concurrent surveillé dans le benchmark."
            ),
        )

        # =====================================================
        # 2. Alias des organisations
        # =====================================================

        aliases = [
            # ARMA
            (arma, "ARMA", "fr"),
            (arma, "ARMA Environnement", "fr"),
            (arma, "Arma Maroc", "fr"),
            (arma, "شركة أرما", "ar"),
            (arma, "@ARMA_MA", None),

            # OZONE
            (ozone, "OZONE", "fr"),
            (ozone, "OZONE Environnement", "fr"),
            (ozone, "Ozone Maroc", "fr"),

            # Averda
            (averda, "Averda", "fr"),
            (averda, "Averda Maroc", "fr"),

            # Suez
            # On garde seulement une variante de "Suez",
            # car SUEZ et Suez deviennent toutes les deux "suez".
            (suez, "Suez Maroc", "fr"),
            (suez, "SUEZ", "fr"),

            # SOS
            (sos, "SOS", "fr"),
        ]

        for organization, alias, language in aliases:
            create_alias_if_missing(
                session=session,
                organization=organization,
                alias=alias,
                language=language,
            )

        # =====================================================
        # 3. Sources
        # =====================================================

        get_or_create_source(
            session=session,
            name="Serper",
            source_type="search_api",
            base_url="https://google.serper.dev",
            reliability_weight=1.0,
            configuration={
                "country": "ma",
                "default_language": "fr",
                "max_results": 20,
            },
        )

        get_or_create_source(
            session=session,
            name="Hespress",
            source_type="online_press",
            base_url="https://www.hespress.com",
            reliability_weight=1.0,
        )

        get_or_create_source(
            session=session,
            name="Facebook",
            source_type="social_network",
            base_url="https://www.facebook.com",
            reliability_weight=1.0,
        )

        get_or_create_source(
            session=session,
            name="Instagram",
            source_type="social_network",
            base_url="https://www.instagram.com",
            reliability_weight=1.0,
        )

        get_or_create_source(
            session=session,
            name="LinkedIn",
            source_type="social_network",
            base_url="https://www.linkedin.com",
            reliability_weight=1.0,
        )

        get_or_create_source(
            session=session,
            name="X / Twitter",
            source_type="social_network",
            base_url="https://x.com",
            reliability_weight=1.0,
        )

        # =====================================================
        # 4. Thèmes NLP
        # =====================================================

        topics = [
            (
                "Retard de collecte",
                "retard-collecte",
                "Retard ou absence de collecte des déchets.",
            ),
            (
                "Propreté urbaine",
                "proprete-urbaine",
                "Actions et résultats liés à la propreté des villes.",
            ),
            (
                "Réclamation citoyenne",
                "reclamation-citoyenne",
                "Plainte ou retour formulé par un citoyen.",
            ),
            (
                "Performance opérationnelle",
                "performance-operationnelle",
                "Résultats, indicateurs et efficacité des opérations.",
            ),
            (
                "Réglementation",
                "reglementation",
                "Lois, normes et obligations environnementales.",
            ),
            (
                "Appel d'offres",
                "appel-offres",
                "Marchés publics, contrats et opportunités commerciales.",
            ),
            (
                "Développement durable",
                "developpement-durable",
                "Environnement, recyclage et transition écologique.",
            ),
            (
                "Communication",
                "communication",
                "Communication institutionnelle et transparence.",
            ),
            (
                "Traitement de l'eau",
                "traitement-eau",
                "Actualités relatives au traitement de l'eau.",
            ),
            (
                "Situation juridique",
                "situation-juridique",
                "Procédures judiciaires ou difficultés juridiques.",
            ),
        ]

        for name, slug, description in topics:
            create_topic_if_missing(
                session=session,
                name=name,
                slug=slug,
                description=description,
            )

        # =====================================================
        # 5. Requêtes liées aux organisations
        # =====================================================

        organization_queries = [
            (arma, "ARMA Environnement Maroc"),
            (arma, "ARMA propreté Casablanca"),
            (arma, "ARMA gestion des déchets Maroc"),

            (ozone, "OZONE Environnement Maroc"),
            (ozone, "OZONE gestion des déchets Maroc"),

            (averda, "Averda Maroc"),
            (averda, "Averda Casablanca"),

            (suez, "Suez Maroc environnement"),
            (suez, "Suez Maroc traitement de l'eau"),

            (sos, "SOS environnement Maroc"),
        ]

        for organization, query_text in organization_queries:
            create_watch_query_if_missing(
                session=session,
                organization=organization,
                query_text=query_text,
                category="organization",
                language="fr",
                frequency="daily",
            )

        # =====================================================
        # 6. Requêtes sectorielles générales
        # =====================================================

        sector_queries = [
            (
                "appel d'offres propreté urbaine Maroc",
                "opportunity",
            ),
            (
                "marché public gestion des déchets Maroc",
                "opportunity",
            ),
            (
                "réglementation déchets Maroc",
                "regulation",
            ),
            (
                "développement durable Casablanca",
                "sector",
            ),
            (
                "actualité environnement Maroc",
                "sector",
            ),
        ]

        for query_text, category in sector_queries:
            create_watch_query_if_missing(
                session=session,
                organization=None,
                query_text=query_text,
                category=category,
                language="fr",
                frequency="daily",
                filters={
                    "country": "ma",
                },
            )

        # Toutes les opérations sont validées ensemble.
        session.commit()

        print("\nInitialisation terminée avec succès.")

        print_database_summary(session)

    except Exception as error:
        # Annule toutes les modifications de cette exécution.
        session.rollback()

        print(
            "\nErreur pendant l'initialisation : "
            f"{error}"
        )

        raise

    finally:
        session.close()


if __name__ == "__main__":
    seed_database()