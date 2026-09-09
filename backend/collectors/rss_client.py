from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import feedparser
import requests
from bs4 import BeautifulSoup


class RSSClient:
    """
    Client générique permettant de télécharger
    et de normaliser un flux RSS ou Atom.
    """

    def __init__(
        self,
        timeout: int = 20,
    ) -> None:
        self.timeout = timeout

        self.session = requests.Session()

        self.session.headers.update(
            {
                "User-Agent": (
                    "ARMA-Marketing-Watch/1.0 "
                    "(academic monitoring project)"
                ),
                "Accept": (
                    "application/rss+xml, "
                    "application/atom+xml, "
                    "application/xml, "
                    "text/xml"
                ),
            }
        )

    @staticmethod
    def clean_value(
        value: Any,
    ) -> str | None:
        """
        Nettoie une valeur texte simple.
        """

        if value is None:
            return None

        text = str(value).strip()

        return text or None

    @staticmethod
    def remove_html(
        value: Any,
    ) -> str | None:
        """
        Supprime les balises HTML présentes
        dans les résumés RSS.
        """

        if value is None:
            return None

        soup = BeautifulSoup(
            str(value),
            "html.parser",
        )

        text = soup.get_text(
            separator=" ",
            strip=True,
        )

        text = " ".join(text.split())

        return text or None

    @staticmethod
    def parsed_date_to_iso(
        parsed_date: Any,
    ) -> str | None:
        """
        Convertit une date RSS structurée
        en date ISO 8601.

        Exemple :
        2026-07-22T08:30:00+00:00
        """

        if parsed_date is None:
            return None

        try:
            date_value = datetime(
                parsed_date.tm_year,
                parsed_date.tm_mon,
                parsed_date.tm_mday,
                parsed_date.tm_hour,
                parsed_date.tm_min,
                parsed_date.tm_sec,
                tzinfo=timezone.utc,
            )

            return date_value.isoformat()

        except (
            AttributeError,
            TypeError,
            ValueError,
        ):
            return None

    def fetch(
        self,
        feed_url: str,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Télécharge un flux RSS et retourne
        une liste normalisée d'articles.
        """

        if max_results <= 0:
            raise ValueError(
                "max_results doit être supérieur à zéro."
            )

        response = self.session.get(
            feed_url,
            timeout=self.timeout,
        )

        response.raise_for_status()

        parsed_feed = feedparser.parse(
            response.content
        )

        # Certains flux peuvent contenir une petite
        # erreur XML tout en restant exploitables.
        # On bloque seulement lorsqu'aucune entrée
        # n'a pu être extraite.
        if parsed_feed.bozo and not parsed_feed.entries:
            parsing_error = getattr(
                parsed_feed,
                "bozo_exception",
                "Erreur RSS inconnue",
            )

            raise RuntimeError(
                "Le flux RSS n'a pas pu être analysé : "
                f"{parsing_error}"
            )

        feed_title = self.clean_value(
            parsed_feed.feed.get("title")
        )

        results: list[dict[str, Any]] = []

        for entry in parsed_feed.entries[:max_results]:
            title = self.clean_value(
                entry.get("title")
            )

            link = self.clean_value(
                entry.get("link")
            )

            snippet = self.remove_html(
                entry.get("summary")
                or entry.get("description")
            )

            rss_id = self.clean_value(
                entry.get("id")
                or entry.get("guid")
                or link
            )

            published_at = self.parsed_date_to_iso(
                entry.get("published_parsed")
                or entry.get("updated_parsed")
            )

            original_date = self.clean_value(
                entry.get("published")
                or entry.get("updated")
            )

            author_name = self.clean_value(
                entry.get("author")
            )

            category = None

            tags = entry.get("tags") or []

            if tags:
                first_tag = tags[0]

                if isinstance(first_tag, dict):
                    category = self.clean_value(
                        first_tag.get("term")
                    )

            # Ignorer une entrée complètement vide.
            if not title and not snippet and not link:
                continue

            normalized_result = {
                "title": title or "Sans titre",
                "link": link,
                "snippet": snippet,
                "date": published_at or original_date,
                "source": feed_title,
                "author": author_name,
                "category": category,
                "rss_id": rss_id,
                "_rss": {
                    "feed_url": feed_url,
                    "feed_title": feed_title,
                    "published_at": published_at,
                    "original_date": original_date,
                },
            }

            results.append(
                normalized_result
            )

        return results


def test_le_matin_feed() -> None:
    """
    Test simple du flux général de Le Matin.

    Ce test affiche cinq articles sans les
    enregistrer dans PostgreSQL.
    """

    feed_url = "https://lematin.ma/rssFeed/0"

    client = RSSClient()

    articles = client.fetch(
        feed_url=feed_url,
        max_results=5,
    )

    print(
        f"Nombre d'articles reçus : "
        f"{len(articles)}"
    )

    for index, article in enumerate(
        articles,
        start=1,
    ):
        print("\n" + "=" * 70)
        print(f"Article {index}")
        print(f"Titre : {article['title']}")
        print(f"Source : {article['source']}")
        print(f"Date : {article['date']}")
        print(f"Lien : {article['link']}")

        snippet = article.get("snippet")

        if snippet:
            print(
                f"Résumé : "
                f"{snippet[:200]}"
            )


if __name__ == "__main__":
    test_le_matin_feed()