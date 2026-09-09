from __future__ import annotations

import html
import re
import unicodedata

from bs4 import BeautifulSoup
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.database.connection import SessionLocal
from backend.database.models import Mention


def normalize_unicode(text: str) -> str:
    """
    Normalise les caractères Unicode.

    Cette opération permet de conserver correctement :
    - le français ;
    - l'arabe ;
    - la darija écrite en arabe ;
    - les chiffres ;
    - les emojis.
    """

    return unicodedata.normalize("NFKC", text)


def remove_html(text: str) -> str:
    """
    Supprime les balises HTML.

    Exemple :
    "<p>Bonjour ARMA</p>" devient "Bonjour ARMA".
    """

    soup = BeautifulSoup(text, "html.parser")

    return soup.get_text(separator=" ")


def remove_urls(text: str) -> str:
    """
    Supprime les liens présents dans le texte.

    Exemple :
    "Voir https://example.com" devient "Voir".
    """

    url_pattern = r"https?://\S+|www\.\S+"

    return re.sub(
        url_pattern,
        " ",
        text,
        flags=re.IGNORECASE,
    )


def remove_email_addresses(text: str) -> str:
    """
    Supprime les adresses e-mail du texte.
    """

    email_pattern = r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"

    return re.sub(
        email_pattern,
        " ",
        text,
    )


def remove_invisible_characters(text: str) -> str:
    """
    Supprime certains caractères invisibles pouvant
    perturber le traitement NLP.
    """

    invisible_characters = [
        "\u200b",  # espace sans largeur
        "\u200c",
        "\u200d",
        "\ufeff",
        "\u2060",
    ]

    for character in invisible_characters:
        text = text.replace(character, "")

    return text


def normalize_spaces(text: str) -> str:
    """
    Remplace plusieurs espaces ou retours à la ligne
    par un seul espace.
    """

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def clean_text(text: str | None) -> str:
    """
    Applique toutes les étapes de nettoyage.

    Les accents, caractères arabes et emojis
    sont volontairement conservés.
    """

    if text is None:
        return ""

    cleaned_text = str(text).strip()

    if not cleaned_text:
        return ""

    # Convertir les éléments HTML comme &amp; en caractères normaux.
    cleaned_text = html.unescape(cleaned_text)

    cleaned_text = normalize_unicode(cleaned_text)
    cleaned_text = remove_html(cleaned_text)
    cleaned_text = remove_urls(cleaned_text)
    cleaned_text = remove_email_addresses(cleaned_text)
    cleaned_text = remove_invisible_characters(cleaned_text)
    cleaned_text = normalize_spaces(cleaned_text)

    return cleaned_text


def get_mentions_to_clean(
    session: Session,
) -> list[Mention]:
    """
    Récupère les mentions qui n'ont pas encore
    été nettoyées.
    """

    statement = (
        select(Mention)
        .where(
            or_(
                Mention.processing_status == "new",
                Mention.clean_text.is_(None),
            )
        )
        .order_by(Mention.id)
    )

    return list(
        session.scalars(statement).all()
    )


def clean_mentions() -> None:
    """
    Nettoie les mentions présentes dans PostgreSQL
    et remplit la colonne clean_text.
    """

    session = SessionLocal()

    try:
        mentions = get_mentions_to_clean(session)

        if not mentions:
            print(
                "Aucune nouvelle mention à nettoyer."
            )
            return

        print(
            f"Nombre de mentions à nettoyer : "
            f"{len(mentions)}"
        )

        cleaned_count = 0
        ignored_count = 0

        for mention in mentions:
            cleaned_value = clean_text(
                mention.raw_text
            )

            if not cleaned_value:
                mention.processing_status = "empty"
                ignored_count += 1

                print(
                    f"Mention vide ignorée : "
                    f"identifiant {mention.id}"
                )

                continue

            mention.clean_text = cleaned_value
            mention.processing_status = "cleaned"

            cleaned_count += 1

            print(
                f"Mention nettoyée : "
                f"{mention.id} - "
                f"{mention.title or 'Sans titre'}"
            )

        session.commit()

        print(
            "\nNettoyage terminé avec succès."
        )
        print(
            f"- Mentions nettoyées : "
            f"{cleaned_count}"
        )
        print(
            f"- Mentions vides : "
            f"{ignored_count}"
        )

    except Exception as error:
        session.rollback()

        print(
            "\nErreur pendant le nettoyage : "
            f"{error}"
        )

        raise

    finally:
        session.close()


def test_cleaner() -> None:
    """
    Petit test local du nettoyage.
    """

    examples = [
        "  ARMA   Environnement\nMaroc  ",
        "<p>Collecte des <strong>déchets</strong></p>",
        "Voir l'article : https://example.com/article",
        "شركة أرما تقدم خدمات النظافة",
        "Service amélioré 😊 dans la ville.",
    ]

    print("Test du nettoyage :")

    for example in examples:
        print("\nTexte original :")
        print(example)

        print("Texte nettoyé :")
        print(clean_text(example))


if __name__ == "__main__":
    clean_mentions()