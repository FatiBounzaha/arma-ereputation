from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.connection import SessionLocal
from backend.database.models import (
    Alert,
    Mention,
    MentionAnalysis,
    MentionOrganization,
    Organization,
)

ALERT_TYPE_NEGATIVE_MENTION = "negative_mention"
OWN_ORGANIZATION_NAME = "ARMA"
MAX_REASON_TEXT_CHARACTERS = 240

RISK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "payroll_hr": (
        "salaire", "salaires", "paie", "paiement", "payement", "retard de paiement",
        "retard de versement", "employé", "employés", "ouvrier", "ouvriers",
        "personnel", "conditions de travail", "licenciement", "الأجور", "أجور", "الرواتب", "رواتب",
        "تأخير صرف", "العمال", "عمال", "ظروف العمل", "المستخدمين",
    ),
    "legal_institutional": (
        "autorité", "autorités", "procureur", "tribunal", "justice", "enquête",
        "mise en demeure", "avertissement officiel", "ultimatum", "plainte pénale",
        "corruption", "fraude", "السلطات", "النيابة", "المحكمة", "إنذار",
        "تحذير", "فساد", "تحقيق",
    ),
    "public_contract": (
        "marché public", "appel d'offres", "appel d offres", "attribution du marché",
        "adjudication", "contrat public", "صفقة", "طلب عروض", "تدبير مفوض",
    ),
    "social_conflict": (
        "grève", "greve", "colère des travailleurs", "grogne sociale", "احتقان",
        "غضب", "إضراب", "توتر اجتماعي",
    ),
    "operational_complaint": (
        "déchets", "ordures", "poubelle", "collecte", "nettoyage", "sale", "saleté",
        "odeur", "quartier", "rue", "النفايات", "الأزبال", "القمامة", "النظافة",
        "الروائح", "حي", "شارع",
    ),
}

PLACE_MARKERS = (
    "casablanca", "rabat", "tanger", "taza", "el jadida", "kénitra", "kenitra",
    "marrakech", "fès", "fes", "agadir", "nouakchott", "الدار البيضاء", "الرباط",
    "طنجة", "تازة", "الجديدة", "القنيطرة", "مراكش", "فاس", "نواكشوط",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text.casefold()).strip()


def mention_text(mention: Mention) -> str:
    return normalize_text(
        " ".join(
            value or ""
            for value in (mention.title, mention.clean_text, mention.raw_text)
        )
    )


def comment_triage(mention: Mention) -> dict:
    payload = mention.raw_payload or {}
    triage = payload.get("_comment_triage") if isinstance(payload, dict) else None
    return triage if isinstance(triage, dict) else {}


def alert_is_displayable(content_type: str, raw_payload: dict | None) -> bool:
    """Règle unique d'affichage d'une alerte dans le portail.

    Un commentaire social n'est montré que s'il est pertinent ET négatif ou
    actionnable. Les autres contenus (presse, publication, web) sont toujours
    affichés. Cette fonction est partagée par la liste des alertes et par les
    compteurs du sélecteur de période, afin que le même chiffre soit annoncé
    partout dans l'interface.
    """

    if content_type != "social_comment":
        return True
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    triage = payload.get("_comment_triage")
    if not isinstance(triage, dict) or not triage.get("relevant"):
        return False
    return bool(
        triage.get("sentiment") == "negative"
        or triage.get("reply_recommended")
    )


def is_alertable_analysis(mention: Mention, analysis: MentionAnalysis) -> bool:
    if mention.content_type != "social_comment":
        return analysis.sentiment_label == "negative"
    triage = comment_triage(mention)
    if not triage.get("relevant"):
        return False
    return bool(
        triage.get("sentiment") == "negative"
        or triage.get("reply_recommended")
    )


def classify_risk(mention: Mention) -> list[str]:
    text = mention_text(mention)
    categories = [
        category
        for category, keywords in RISK_KEYWORDS.items()
        if any(normalize_text(keyword) in text for keyword in keywords)
    ]
    if any(normalize_text(place) in text for place in PLACE_MARKERS):
        categories.append("place_identified")
    if mention.content_type == "news_article":
        categories.append("press_content")
    return list(dict.fromkeys(categories))


def engagement_score(mention: Mention) -> int:
    engagement = mention.engagement or {}
    return (
        int(engagement.get("likes") or engagement.get("reactions") or 0)
        + 2 * int(engagement.get("comments") or engagement.get("replies") or 0)
        + 3
        * int(
            engagement.get("shares")
            or engagement.get("reposts")
            or engagement.get("retweets")
            or 0
        )
        + 3 * int(engagement.get("quotes") or 0)
    )


def determine_severity(confidence: float | None, mention: Mention) -> str:
    """Combine confiance, diffusion et risque métier explicite."""

    categories = set(classify_risk(mention))
    high_risk = {
        "payroll_hr",
        "legal_institutional",
        "public_contract",
        "social_conflict",
    }
    if categories.intersection(high_risk):
        return "high"

    confidence_value = confidence or 0.0
    reach_signal = engagement_score(mention)
    if "press_content" in categories and confidence_value >= 0.55:
        return "high"
    if confidence_value >= 0.75 or reach_signal >= 25:
        return "high"
    if (
        confidence_value >= 0.5
        or reach_signal >= 5
        or {"operational_complaint", "place_identified"}.issubset(categories)
    ):
        return "medium"
    return "low"


def build_alert_reason(
    organization_name: str,
    mention: Mention,
    analysis: MentionAnalysis,
) -> str:
    excerpt = (mention.clean_text or mention.raw_text or "").strip()
    excerpt = excerpt[:MAX_REASON_TEXT_CHARACTERS]
    risk_categories = classify_risk(mention)
    risk_text = f" Risque métier : {', '.join(risk_categories)}." if risk_categories else ""
    triage = comment_triage(mention)
    actionable = mention.content_type == "social_comment" and bool(triage.get("reply_recommended"))
    negative = (triage.get("sentiment") if triage else analysis.sentiment_label) == "negative"
    signal_label = (
        "Commentaire négatif à traiter"
        if negative
        else "Commentaire nécessitant une réponse"
        if actionable
        else "Mention négative détectée"
    )
    explanation = analysis.explanation or triage.get("reason")
    if explanation:
        return (
            f"{signal_label} pour {organization_name} "
            f"(confiance {analysis.confidence or 0:.0%}) : "
            f"{explanation}.{risk_text}"
        )
    return (
        f"{signal_label} pour {organization_name} "
        f"(confiance {analysis.confidence or 0:.0%}) : \"{excerpt}\".{risk_text}"
    )


def get_alertable_analyses(
    session: Session,
    limit: int | None = None,
) -> list[tuple[MentionAnalysis, MentionOrganization, Mention, Organization]]:
    already_alerted = select(Alert.mention_organization_id).where(
        Alert.status.in_(["open", "acknowledged", "resolved"])
    )
    statement = (
        select(MentionAnalysis, MentionOrganization, Mention, Organization)
        .join(
            MentionOrganization,
            MentionOrganization.id == MentionAnalysis.mention_organization_id,
        )
        .join(Mention, Mention.id == MentionOrganization.mention_id)
        .join(Organization, Organization.id == MentionOrganization.organization_id)
        .where(
            MentionAnalysis.is_current.is_(True),
            MentionOrganization.include_in_reputation.is_(True),
            Organization.name == OWN_ORGANIZATION_NAME,
            MentionOrganization.id.notin_(already_alerted),
        )
        .order_by(MentionAnalysis.id)
    )
    rows = [
        row for row in session.execute(statement).all()
        if is_alertable_analysis(row[2], row[0])
    ]
    if limit is not None:
        rows = rows[:limit]
    return rows


def reclassify_open_alerts(session: Session) -> int:
    """Met à jour les anciennes alertes avec les règles de risque V9."""

    rows = session.execute(
        select(Alert, Mention, MentionAnalysis)
        .join(
            MentionOrganization,
            MentionOrganization.id == Alert.mention_organization_id,
        )
        .join(Mention, Mention.id == MentionOrganization.mention_id)
        .outerjoin(
            MentionAnalysis,
            (MentionAnalysis.mention_organization_id == MentionOrganization.id)
            & (MentionAnalysis.is_current.is_(True)),
        )
        .where(Alert.status == "open")
    ).all()

    updated = 0
    for alert, mention, analysis in rows:
        confidence = analysis.confidence if analysis is not None else (
            (alert.extra_data or {}).get("sentiment_confidence")
        )
        new_severity = determine_severity(confidence, mention)
        categories = classify_risk(mention)
        old_payload = dict(alert.extra_data or {})
        if alert.severity != new_severity or old_payload.get("risk_categories") != categories:
            alert.severity = new_severity
            alert.extra_data = {
                **old_payload,
                "risk_categories": categories,
                "severity_rule_version": "v9",
                "engagement_score": engagement_score(mention),
            }
            updated += 1
    session.flush()
    return updated


def generate_alerts_for_negative_mentions(limit: int | None = None) -> dict[str, int]:
    session = SessionLocal()
    try:
        updated_existing = reclassify_open_alerts(session)
        candidates = get_alertable_analyses(session=session, limit=limit)
        if not candidates:
            session.commit()
            print("Aucune nouvelle mention négative à alerter.")
            print(f"- Alertes ouvertes reclassées : {updated_existing}")
            return {"candidates": 0, "created": 0, "failed": 0, "reclassified": updated_existing}

        print(f"Mentions négatives à alerter : {len(candidates)}")
        items_created = 0
        items_failed = 0

        for analysis, mention_organization, mention, organization in candidates:
            try:
                risk_categories = classify_risk(mention)
                triage = comment_triage(mention)
                is_actionable_comment = (
                    mention.content_type == "social_comment"
                    and bool(triage.get("reply_recommended"))
                )
                severity = determine_severity(analysis.confidence, mention)
                if (
                    is_actionable_comment
                    and triage.get("sentiment") != "negative"
                    and severity == "high"
                ):
                    severity = "medium"
                alert = Alert(
                    mention_organization_id=mention_organization.id,
                    alert_type=("actionable_comment" if is_actionable_comment else ALERT_TYPE_NEGATIVE_MENTION),
                    severity=severity,
                    reason=build_alert_reason(organization.name, mention, analysis),
                    status="open",
                    created_at=utc_now(),
                    extra_data={
                        "mention_analysis_id": analysis.id,
                        "sentiment_confidence": analysis.confidence,
                        "engagement_score": engagement_score(mention),
                        "content_type": mention.content_type,
                        "risk_categories": risk_categories,
                        "severity_rule_version": "v10-actionable-comments",
                        "triage_sentiment": triage.get("sentiment"),
                        "reply_recommended": bool(triage.get("reply_recommended")),
                    },
                )
                session.add(alert)
                session.commit()
                items_created += 1
                print(
                    f"Alerte créée : mention_organization={mention_organization.id} "
                    f"-> sévérité {alert.severity} ({', '.join(risk_categories) or 'standard'})"
                )
            except Exception as item_error:
                session.rollback()
                items_failed += 1
                print(
                    "Alerte ignorée (erreur) : mention_organization="
                    f"{mention_organization.id} -> {item_error}"
                )

        print("\nGénération des alertes terminée.")
        print(f"- Alertes ouvertes reclassées : {updated_existing}")
        print(f"- Alertes créées : {items_created}")
        print(f"- Échouées : {items_failed}")
        if items_failed:
            raise RuntimeError(
                f"Génération des alertes incomplète : {items_failed} échec(s)."
            )
        return {
            "candidates": len(candidates),
            "created": items_created,
            "failed": items_failed,
            "reclassified": updated_existing,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    generate_alerts_for_negative_mentions()
