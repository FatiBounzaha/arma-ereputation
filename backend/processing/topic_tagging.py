from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.connection import SessionLocal
from backend.database.models import Mention, MentionTopic, Topic
from backend.services.rss_relevance_service import find_sector_topics

# Le classement d'origine dans rss_relevance_service.py sert à
# filtrer les articles pendant la collecte. On le réutilise ici
# tel quel pour attacher des thèmes persistants (mention_topics)
# aux mentions déjà en base, sans dupliquer les mots-clés.
DETECTION_METHOD = "keyword_matching"


def get_untagged_mentions(
    session: Session,
    limit: int | None = None,
) -> list[Mention]:
    """Retourne les mentions qui n'ont encore aucun thème associé."""

    already_tagged = select(MentionTopic.mention_id)

    statement = (
        select(Mention)
        .where(Mention.id.notin_(already_tagged))
        .order_by(Mention.id)
    )

    if limit is not None:
        statement = statement.limit(limit)

    return list(session.scalars(statement))


def get_topics_by_slug(session: Session) -> dict[str, Topic]:
    """Charge le référentiel de thèmes une seule fois par run."""

    topics = session.scalars(select(Topic)).all()

    return {topic.slug: topic for topic in topics}


def tag_mention(
    session: Session,
    mention: Mention,
    topics_by_slug: dict[str, Topic],
) -> int:
    """
    Détecte les thèmes sectoriels d'une mention et crée les
    lignes mention_topics correspondantes.

    Retourne le nombre de thèmes attachés.
    """

    article = {
        "title": mention.title,
        "raw_text": mention.clean_text or mention.raw_text,
    }

    detected_topics = find_sector_topics(article)

    if not detected_topics:
        return 0

    # Le thème avec le plus de mots-clés reconnus est marqué
    # comme principal (is_primary), pour alimenter par exemple
    # ReputationSnapshot.dominant_topic_id.
    ranked_slugs = sorted(
        detected_topics,
        key=lambda slug: len(detected_topics[slug]),
        reverse=True,
    )

    attached_count = 0

    for rank, topic_slug in enumerate(ranked_slugs):
        topic = topics_by_slug.get(topic_slug)

        if topic is None:
            # Le référentiel topics doit être seedé au préalable
            # (backend/database/seed.py). Un thème détecté mais
            # absent du référentiel est simplement ignoré.
            continue

        matched_keywords = detected_topics[topic_slug]

        mention_topic = MentionTopic(
            mention_id=mention.id,
            topic_id=topic.id,
            confidence=min(1.0, 0.2 * len(matched_keywords)),
            is_primary=(rank == 0),
            detection_method=DETECTION_METHOD,
        )

        session.add(mention_topic)
        attached_count += 1

    return attached_count


def tag_mentions_with_topics(limit: int | None = None) -> None:
    """
    Attache des thèmes sectoriels aux mentions qui n'en ont pas
    encore, à partir des mots-clés déjà utilisés pour le filtrage
    de pertinence à la collecte.
    """

    session = SessionLocal()

    try:
        topics_by_slug = get_topics_by_slug(session)

        if not topics_by_slug:
            print(
                "Aucun thème dans le référentiel topics. "
                "Lancez d'abord backend/database/seed.py."
            )
            return

        mentions = get_untagged_mentions(session, limit=limit)

        if not mentions:
            print("Aucune nouvelle mention à classer par thème.")
            return

        print(f"Mentions à classer : {len(mentions)}")

        tagged_count = 0
        untagged_count = 0

        for mention in mentions:
            attached_count = tag_mention(
                session=session,
                mention=mention,
                topics_by_slug=topics_by_slug,
            )

            if attached_count == 0:
                untagged_count += 1
                continue

            tagged_count += 1
            session.commit()

            print(
                f"Mention {mention.id} : {attached_count} thème(s) attaché(s)."
            )

        print("\nClassement par thème terminé.")
        print(f"- Mentions classées : {tagged_count}")
        print(f"- Mentions sans thème sectoriel : {untagged_count}")

    except Exception as error:
        session.rollback()

        print(f"\nErreur pendant le classement par thème : {error}")

        raise

    finally:
        session.close()


if __name__ == "__main__":
    tag_mentions_with_topics()
