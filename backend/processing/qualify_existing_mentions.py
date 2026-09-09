from __future__ import annotations

from sqlalchemy import select

from backend.database.connection import SessionLocal
from backend.database.models import Mention, MentionOrganization, Organization, Source
from backend.processing.business_relevance import evaluate_business_relevance
from backend.services.rss_relevance_service import classify_article
from backend.services.social_collection_service_v2 import ensure_organization_links


def qualify_mentions(limit: int | None = None) -> None:
    """Qualifie les mentions déjà collectées et corrige les faux positifs.

    Cette étape permet notamment de retirer de la vue Marketing les profils,
    recrutements et annonces sans valeur métier, et d'exclure ces contenus du
    score de réputation lorsqu'ils ne parlent pas réellement du service.
    """

    session = SessionLocal()
    try:
        statement = select(Mention, Source).join(Source, Source.id == Mention.source_id).order_by(Mention.id)
        if limit is not None:
            statement = statement.limit(limit)
        rows = session.execute(statement).all()
        organizations = {
            organization.name: organization
            for organization in session.scalars(
                select(Organization).where(Organization.is_active.is_(True))
            ).all()
        }

        qualified = 0
        hidden = 0
        reputation_excluded = 0

        for mention, source in rows:
            if mention.content_type == "social_comment":
                mention.display_in_marketing = False
                mention.business_relevance_score = mention.business_relevance_score or 0.0
                continue

            relation_rows = session.execute(
                select(MentionOrganization, Organization)
                .join(Organization, Organization.id == MentionOrganization.organization_id)
                .where(MentionOrganization.mention_id == mention.id)
            ).all()
            organization_names = [organization.name for _, organization in relation_rows]

            result = {
                "title": mention.title,
                "snippet": mention.business_summary or mention.clean_text or mention.raw_text,
                "raw_text": mention.raw_text,
                "date": (mention.published_at or mention.collected_at).isoformat() if (mention.published_at or mention.collected_at) else None,
            }
            classification = classify_article(result)
            detected_names = organization_names or classification["organizations"]
            payload = mention.raw_payload or {}
            collection = payload.get("_collection") if isinstance(payload, dict) else {}
            collection = collection if isinstance(collection, dict) else {}

            decision = evaluate_business_relevance(
                result,
                organizations=detected_names,
                sector_topics=classification["sector_topics"],
                content_origin=str(collection.get("content_origin") or "") or None,
                content_purpose=str(collection.get("content_purpose") or "") or None,
                source_name=source.name,
                query_category=str(collection.get("query_category") or "") or None,
            )

            if detected_names and not organization_names:
                eligible = (
                    "noise_or_hr_content" not in decision.quality_flags
                    and "employment" not in decision.quality_flags
                    and (bool(classification["sector_topics"]) or decision.score >= 0.55)
                )
                ensure_organization_links(
                    session=session,
                    mention=mention,
                    detected_names=detected_names,
                    organizations=organizations,
                    primary_name=detected_names[0],
                    include_in_reputation=eligible,
                    detection_method="qualification_backfill",
                    relevance_score=max(0.5, decision.score),
                )
                relation_rows = session.execute(
                    select(MentionOrganization, Organization)
                    .join(Organization, Organization.id == MentionOrganization.organization_id)
                    .where(MentionOrganization.mention_id == mention.id)
                ).all()

            mention.business_category = decision.category
            mention.business_relevance_score = decision.score
            mention.business_summary = decision.summary or mention.business_summary
            mention.display_in_marketing = decision.display_in_marketing
            mention.quality_flags = decision.quality_flags
            qualified += 1
            if not decision.display_in_marketing:
                hidden += 1

            # Le score d'e-réputation doit porter sur la qualité du service,
            # pas sur un recrutement, un profil ou une nomination d'employé.
            if mention.content_type == "social_post" and (
                "noise_or_hr_content" in decision.quality_flags
                or "employment" in decision.quality_flags
                or (not classification["sector_topics"] and decision.score < 0.55)
            ):
                for relation, _ in relation_rows:
                    if relation.include_in_reputation:
                        relation.include_in_reputation = False
                        reputation_excluded += 1

        session.commit()
        print("Qualification métier terminée.")
        print(f"- Mentions qualifiées : {qualified}")
        print(f"- Masquées de la vue Marketing : {hidden}")
        print(f"- Relations exclues de la réputation : {reputation_excluded}")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    qualify_mentions()
