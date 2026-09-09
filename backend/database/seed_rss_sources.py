from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.connection import SessionLocal
from backend.database.models import Source


RSS_SOURCES: list[dict[str, Any]] = [
    {
        "name": "Hespress",
        "source_type": "online_press",
        "base_url": "https://www.hespress.com",
        "configuration": {
            "collection_method": "rss",
            "country": "MA",
            "languages": [
                "ar",
            ],
            "feeds": [
                {
                    "name": "آخر الأخبار",
                    "url": "https://www.hespress.com/feed",
                    "language": "ar",
                    "category": "general",
                },
            ],
        },
        "is_active": True,
    },
        {
        "name": "Al Yaoum24",
        "source_type": "online_press",
        "base_url": "https://alyaoum24.com",
        "configuration": {
            "collection_method": "rss",
            "country": "MA",
            "languages": [
                "ar",
            ],
            "feeds": [
                {
                    "name": "آخر الأخبار",
                    "url": "https://alyaoum24.com/feed/",
                    "language": "ar",
                    "category": "general",
                },
            ],
        },
        "is_active": True,
    },
        {
        "name": "Akhbarona",
        "source_type": "online_press",
        "base_url": "https://www.akhbarona.com",
        "configuration": {
            "collection_method": "rss",
            "country": "MA",
            "languages": [
                "ar",
            ],
            "feeds": [
                {
                    "name": "آخر الأخبار",
                    "url": (
                        "https://www.akhbarona.com/"
                        "feed/index.rss"
                    ),
                    "language": "ar",
                    "category": "general",
                },
            ],
        },
        "is_active": True,
    },
    {
        "name": "Le Matin",
        "source_type": "online_press",
        "base_url": "https://lematin.ma",
        "configuration": {
            "collection_method": "rss",
            "country": "MA",
            "languages": [
                "fr",
            ],
            "feeds": [
                {
                    "name": "Derniers articles",
                    "url": "https://lematin.ma/rssFeed/0",
                    "language": "fr",
                    "category": "general",
                },
                {
                    "name": "Économie",
                    "url": "https://lematin.ma/rssFeed/4",
                    "language": "fr",
                    "category": "economy",
                },
                {
                    "name": "Société",
                    "url": "https://lematin.ma/rssFeed/9",
                    "language": "fr",
                    "category": "society",
                },
            ],
        },
        "is_active": True,
    },
    {
        "name": "Télégraphe Maroc",
        "source_type": "online_press",
        "base_url": "https://www.telegraphe.ma",
        "configuration": {
            "collection_method": "rss",
            "country": "MA",
            "languages": [
                "ar",
            ],
            "feeds": [
                {
                    "name": "آخر الأخبار",
                    "url": (
                        "https://www.telegraphe.ma/"
                        "rss/latest-posts"
                    ),
                    "language": "ar",
                    "category": "general",
                },
                {
                    "name": "مجتمع",
                    "url": (
                        "https://www.telegraphe.ma/"
                        "rss/category/public"
                    ),
                    "language": "ar",
                    "category": "society",
                },
                {
                    "name": "اقتصاد",
                    "url": (
                        "https://www.telegraphe.ma/"
                        "rss/category/economie"
                    ),
                    "language": "ar",
                    "category": "economy",
                },
            ],
        },
        "is_active": True,
    },
    {
        "name": "Baba Sabta",
        "source_type": "online_press",
        "base_url": "https://babsabta.ma",
        "configuration": {
            "collection_method": "rss",
            "country": "MA",
            "languages": [
                "ar",
            ],
            "feeds": [
                {
                    "name": "الرئيسية",
                    "url": "https://babsabta.ma/feed/gn",
                    "language": "ar",
                    "category": "general",
                },
                {
                    "name": "اقتصاد",
                    "url": (
                        "https://babsabta.ma/"
                        "economy/feed/gn"
                    ),
                    "language": "ar",
                    "category": "economy",
                },
                {
                    "name": "الطقس والبيئة",
                    "url": (
                        "https://babsabta.ma/"
                        "weather-env/feed/gn"
                    ),
                    "language": "ar",
                    "category": "environment",
                },
            ],
        },
        "is_active": True,
    },
        {
        "name": "Médias24",
        "source_type": "online_press",
        "base_url": "https://medias24.com",
        "configuration": {
            "collection_method": "rss",
            "country": "MA",
            "languages": [
                "fr",
            ],
            "feeds": [
                {
                    "name": "Derniers articles",
                    "url": "https://medias24.com/feed/",
                    "language": "fr",
                    "category": "general",
                },
            ],
        },
        "is_active": True,
    },
]


def create_or_update_source(
    session: Session,
    source_data: dict[str, Any],
) -> None:
    """
    Crée une source si elle n'existe pas.

    Si la source existe déjà, sa configuration
    est mise à jour sans créer de doublon.
    """

    source_name = source_data["name"]

    source = session.scalar(
        select(Source).where(
            Source.name == source_name
        )
    )

    if source is None:
        source = Source(
            name=source_data["name"],
            source_type=source_data["source_type"],
            base_url=source_data["base_url"],
            configuration=source_data["configuration"],
            is_active=source_data["is_active"],
        )

        session.add(source)

        print(
            f"Source ajoutée : {source_name}"
        )

        return

    source.source_type = source_data["source_type"]
    source.base_url = source_data["base_url"]
    source.configuration = source_data["configuration"]
    source.is_active = source_data["is_active"]

    print(
        f"Source mise à jour : {source_name}"
    )


def seed_rss_sources() -> None:
    """
    Ajoute ou met à jour les sources RSS
    de la presse marocaine.
    """

    session = SessionLocal()

    try:
        for source_data in RSS_SOURCES:
            create_or_update_source(
                session=session,
                source_data=source_data,
            )

        session.commit()

        print("\nInitialisation terminée.")
        print(
            f"Nombre de sources RSS configurées : "
            f"{len(RSS_SOURCES)}"
        )

    except Exception as error:
        session.rollback()

        print(
            "\nErreur pendant l'initialisation "
            f"des sources RSS : {error}"
        )

        raise

    finally:
        session.close()


if __name__ == "__main__":
    seed_rss_sources()