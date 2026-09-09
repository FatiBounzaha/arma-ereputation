from __future__ import annotations

import os
from typing import Any

import requests
from dotenv import load_dotenv


# Charge les variables présentes dans le fichier .env
load_dotenv()


class SerperClient:
    """
    Client chargé de communiquer avec l'API Serper.

    Pour le moment, il permet :
    - de rechercher des actualités ;
    - de rechercher des résultats Web classiques.
    """

    BASE_URL = "https://google.serper.dev"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: int = 30,
    ) -> None:
        """
        Initialise le client Serper.

        La clé peut être fournie directement ou récupérée
        depuis SERPER_API_KEY dans le fichier .env.
        """

        self.api_key = api_key or os.getenv("SERPER_API_KEY")
        self.timeout = timeout

        if not self.api_key:
            raise RuntimeError(
                "La variable SERPER_API_KEY est absente du fichier .env."
            )

    def _request(
        self,
        endpoint: str,
        query: str,
        language: str = "fr",
        country: str = "ma",
        num: int = 10,
    ) -> dict[str, Any]:
        """
        Envoie une requête à l'API Serper.
        """

        query = query.strip()

        if not query:
            raise ValueError(
                "La requête de recherche ne peut pas être vide."
            )

        if num < 1:
            raise ValueError(
                "Le nombre de résultats doit être supérieur à zéro."
            )

        url = f"{self.BASE_URL}/{endpoint}"

        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

        payload = {
            "q": query,
            "hl": language,
            "gl": country,
            "num": num,
        }

        try:
            response = requests.post(
                url=url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )

            response.raise_for_status()

        except requests.Timeout as error:
            raise RuntimeError(
                "L'API Serper a mis trop de temps à répondre."
            ) from error

        except requests.HTTPError as error:
            status_code = response.status_code

            try:
                error_details = response.json()
            except ValueError:
                error_details = response.text

            raise RuntimeError(
                "Erreur retournée par Serper. "
                f"Code HTTP : {status_code}. "
                f"Détails : {error_details}"
            ) from error

        except requests.RequestException as error:
            raise RuntimeError(
                "Impossible de communiquer avec l'API Serper. "
                "Vérifie ta connexion Internet."
            ) from error

        try:
            return response.json()

        except ValueError as error:
            raise RuntimeError(
                "La réponse de Serper n'est pas un JSON valide."
            ) from error

    def search_news(
        self,
        query: str,
        language: str = "fr",
        country: str = "ma",
        num: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Recherche des articles d'actualité.
        """

        data = self._request(
            endpoint="news",
            query=query,
            language=language,
            country=country,
            num=num,
        )

        news_results = data.get("news", [])

        if not isinstance(news_results, list):
            return []

        return news_results

    def search_web(
        self,
        query: str,
        language: str = "fr",
        country: str = "ma",
        num: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Recherche des résultats Web classiques.
        """

        data = self._request(
            endpoint="search",
            query=query,
            language=language,
            country=country,
            num=num,
        )

        organic_results = data.get("organic", [])

        if not isinstance(organic_results, list):
            return []

        return organic_results


def display_results(results: list[dict[str, Any]]) -> None:
    """
    Affiche simplement les résultats dans le terminal.
    """

    if not results:
        print("Aucun résultat trouvé.")
        return

    print(f"\nNombre de résultats reçus : {len(results)}")

    for index, result in enumerate(results, start=1):
        title = result.get("title", "Titre indisponible")
        source = result.get("source", "Source inconnue")
        date = result.get("date", "Date inconnue")
        link = result.get("link", "Lien indisponible")
        snippet = result.get("snippet", "Résumé indisponible")

        print("\n" + "=" * 70)
        print(f"Résultat numéro {index}")
        print(f"Titre  : {title}")
        print(f"Source : {source}")
        print(f"Date   : {date}")
        print(f"Lien   : {link}")
        print(f"Résumé : {snippet}")


def main() -> None:
    """
    Premier test du client Serper.
    """

    print("Test de connexion à Serper...")

    client = SerperClient()

    results = client.search_news(
        query="ARMA Environnement Maroc",
        language="fr",
        country="ma",
        num=5,
    )

    display_results(results)


if __name__ == "__main__":
    main()