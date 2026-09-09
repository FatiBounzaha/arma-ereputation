from __future__ import annotations

from typing import Any

from sqlalchemy import select

from backend.database.connection import SessionLocal
from backend.database.models import Mention
from backend.services.collection_service import (
    create_content_hash,
    create_external_id,
)


def build_serper_result(
    mention: Mention,
) -> dict[str, Any]:
    """
    Reconstruit un résultat compatible avec les fonctions
    de calcul des empreintes.

    Les données sont d'abord récupérées dans raw_payload.
    Les colonnes de la mention servent de valeurs de secours.
    """

    if isinstance(mention.raw_payload, dict):
        raw_payload = mention.raw_payload
    else:
        raw_payload = {}

    return {
        "title": (
            raw_payload.get("title")
            or mention.title
            or ""
        ),
        "snippet": (
            raw_payload.get("snippet")
            or mention.raw_text
            or ""
        ),
        "link": (
            raw_payload.get("link")
            or mention.url
            or ""
        ),
    }


def detect_future_conflicts(
    calculated_values: list[dict[str, Any]],
) -> list[str]:
    """
    Vérifie les nouvelles empreintes avant de modifier la base.

    Cette vérification empêche deux mentions de recevoir :
    - le même content_hash ;
    - le même external_id pour une même source.
    """

    content_hashes: dict[str, int] = {}
    external_ids: dict[tuple[int, str], int] = {}
    conflicts: list[str] = []

    for item in calculated_values:
        mention_id = item["mention"].id
        source_id = item["mention"].source_id
        content_hash = item["content_hash"]
        external_id = item["external_id"]

        previous_content_id = content_hashes.get(
            content_hash
        )

        if previous_content_id is not None:
            conflicts.append(
                "Même content_hash pour les mentions "
                f"{previous_content_id} et {mention_id}."
            )
        else:
            content_hashes[content_hash] = mention_id

        external_key = (
            source_id,
            external_id,
        )

        previous_external_id = external_ids.get(
            external_key
        )

        if previous_external_id is not None:
            conflicts.append(
                "Même external_id pour les mentions "
                f"{previous_external_id} et {mention_id}."
            )
        else:
            external_ids[external_key] = mention_id

    return conflicts


def rehash_mentions() -> None:
    """
    Recalcule external_id et content_hash pour toutes
    les mentions déjà enregistrées.
    """

    session = SessionLocal()

    try:
        mentions = list(
            session.scalars(
                select(Mention).order_by(Mention.id)
            ).all()
        )

        if not mentions:
            print("Aucune mention à mettre à jour.")
            return

        print(
            f"Nombre de mentions à analyser : "
            f"{len(mentions)}"
        )

        calculated_values: list[dict[str, Any]] = []

        # Première passe :
        # calculer les nouvelles valeurs sans modifier la base.
        for mention in mentions:
            result = build_serper_result(mention)

            new_external_id = create_external_id(
                result
            )

            new_content_hash = create_content_hash(
                result
            )

            calculated_values.append(
                {
                    "mention": mention,
                    "external_id": new_external_id,
                    "content_hash": new_content_hash,
                }
            )

        # Vérifier les conflits avant toute modification.
        conflicts = detect_future_conflicts(
            calculated_values
        )

        if conflicts:
            print(
                "\nDes doublons sont encore présents."
            )
            print(
                "Aucune modification n'a été enregistrée."
            )

            for conflict in conflicts:
                print(f"- {conflict}")

            session.rollback()
            return

        updated_count = 0
        unchanged_count = 0

        # Deuxième passe :
        # appliquer les nouvelles valeurs.
        for item in calculated_values:
            mention: Mention = item["mention"]

            new_external_id = item["external_id"]
            new_content_hash = item["content_hash"]

            has_changed = (
                mention.external_id != new_external_id
                or mention.content_hash != new_content_hash
            )

            if not has_changed:
                unchanged_count += 1

                print(
                    f"Mention inchangée : "
                    f"{mention.id}"
                )

                continue

            mention.external_id = new_external_id
            mention.content_hash = new_content_hash

            updated_count += 1

            print(
                f"Empreintes recalculées : "
                f"{mention.id} - "
                f"{mention.title or 'Sans titre'}"
            )

        session.commit()

        print(
            "\nRecalcul terminé avec succès."
        )
        print(
            f"- Mentions mises à jour : "
            f"{updated_count}"
        )
        print(
            f"- Mentions inchangées : "
            f"{unchanged_count}"
        )

    except Exception as error:
        session.rollback()

        print(
            "\nErreur pendant le recalcul : "
            f"{error}"
        )

        raise

    finally:
        session.close()


if __name__ == "__main__":
    rehash_mentions()