from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ResponseDecision:
    """Décision métier prise avant toute rédaction publique."""

    action: str
    action_label: str
    category: str
    reply_eligible: bool
    requires_human_validation: bool
    rationale: str
    ask_for_private_details: bool = False
    recommended_channel: str = "portail_interne"
    place_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Les règles restent volontairement explicites et auditables. Le LLM peut
# améliorer la rédaction, mais il ne doit pas décider seul qu'une réponse
# publique doit être envoyée.
ARTICLE_SOURCE_TYPES = {"online_press", "rss", "news", "search_api"}

INSTITUTIONAL_KEYWORDS = (
    "autorité", "autorités", "wali", "préfecture", "commune", "tribunal",
    "justice", "marché public", "appel d'offres", "contrat", "mise en demeure",
    "avertissement", "ultimatum", "manquement", "enquête", "redressement",
    "grève", "plainte officielle", "وزارة", "السلطات", "الوالي", "الجماعة",
    "المحكمة", "صفقة", "إنذار", "تحذير", "إضراب", "اختلالات", "تقصير",
)

OPERATIONAL_COMPLAINT_KEYWORDS = (
    "poubelle", "poubelles", "ordures", "déchets", "ramass", "collecte",
    "nettoyage", "sale", "saleté", "odeur", "retard", "quartier", "rue",
    "service", "النفايات", "الأزبال", "القمامة", "النظافة", "جمع", "تأخر",
    "حي", "شارع", "زنقة", "روائح", "خدمة",
)

DIRECT_REQUEST_MARKERS = (
    "pouvez-vous", "merci de", "je demande", "nous demandons", "chez moi",
    "dans mon", "devant ma", "@arma", "svp", "؟", "هل يمكن", "نطلب",
    "أرجو", "المرجو", "عندي", "لدينا", "في حينا", "أمام منزلي",
)

GENERAL_CRITICISM_MARKERS = (
    "grogne", "mécontentement", "colère", "indignation", "inquiétude",
    "risque", "dans le viseur", "chaotique", "crise", "g غضب", "غضب",
    "استياء", "سخط", "قلق", "جدل", "انتقادات", "فشل",
)


HR_OR_LEGAL_SENSITIVE_MARKERS = (
    "salaire", "salaires", "paie", "payement", "paiement", "retard de paiement",
    "grève", "greve", "employé", "employés", "personnel", "licenciement",
    "accident", "fraude", "corruption", "tribunal", "justice", "plainte pénale",
    "الأجور", "الرواتب", "الإضراب", "الموظفين", "المحكمة", "فساد",
)

SPAM_OR_NOISE_FLAGS = {
    "noise_or_hr_content", "wrong_platform_domain", "homonym_risk",
    "social_object_profile", "social_object_job", "social_object_navigation",
    "off_topic",
}

KNOWN_PLACES = (
    "casablanca", "rabat", "el jadida", "nouakchott", "tanger", "kénitra",
    "kenitra", "marrakech", "fès", "fes", "meknès", "meknes", "agadir",
    "tetouan", "tétouan", " الجديدة", "الدار البيضاء", "الرباط", "نواكشوط",
    "طنجة", "القنيطرة", "مراكش", "فاس", "مكناس", "أكادير", "تطوان",
)


def _normalize(value: str | None) -> str:
    text = (value or "").lower().strip()
    return re.sub(r"\s+", " ", text)


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _extract_place(text: str, explicit_city: str | None) -> str | None:
    if explicit_city and explicit_city.strip():
        return explicit_city.strip()

    for place in KNOWN_PLACES:
        if place.strip() and place in text:
            return place.strip().title() if place.isascii() else place.strip()

    # Indices génériques : ils prouvent qu'un lieu est déjà fourni même si
    # nous ne savons pas extraire son nom propre avec certitude.
    generic_patterns = (
        r"\b(?:quartier|rue|avenue|boulevard|ville de|commune de)\s+[^,.!?]{2,45}",
        r"(?:مدينة|حي|شارع|زنقة|جماعة)\s+[^،.!؟]{2,40}",
    )
    for pattern in generic_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()

    return None


def decide_response_action(context: dict[str, Any]) -> ResponseDecision:
    """
    Classe une alerte avant rédaction.

    La sortie distingue une réclamation directement actionnable, une critique
    générale, un article institutionnel et un contenu à ignorer. Cette étape
    évite la règle dangereuse « sentiment négatif = même réponse générique ».
    """

    text = _normalize(
        " ".join(
            str(value or "")
            for value in (
                context.get("title"),
                context.get("mention_text"),
                context.get("alert_reason"),
                context.get("parent_title"),
            )
        )
    )
    content_type = _normalize(context.get("content_type"))
    source_type = _normalize(context.get("source_type"))
    source_name = _normalize(context.get("source_name"))
    quality_flags = set(context.get("quality_flags") or [])
    place_hint = _extract_place(text, context.get("city"))

    if quality_flags.intersection(SPAM_OR_NOISE_FLAGS):
        return ResponseDecision(
            action="no_reply",
            action_label="Aucune réponse publique",
            category="noise_or_off_topic",
            reply_eligible=False,
            requires_human_validation=False,
            rationale="Le contenu est marqué comme bruit, profil, recrutement ou hors sujet.",
            recommended_channel="aucun",
            place_hint=place_hint,
        )

    is_comment = content_type == "social_comment"
    is_social_post = content_type == "social_post"
    is_article = (
        content_type == "news_article"
        or (source_type in ARTICLE_SOURCE_TYPES and not is_social_post and not is_comment)
        or any(token in source_name for token in ("serper", "rss", "hespress", "le360", "médias24", "medias24"))
        and not is_social_post
    )

    has_operational_issue = _contains_any(text, OPERATIONAL_COMPLAINT_KEYWORDS)
    is_direct_request = _contains_any(text, DIRECT_REQUEST_MARKERS)
    is_institutional = _contains_any(text, INSTITUTIONAL_KEYWORDS)
    is_general_criticism = _contains_any(text, GENERAL_CRITICISM_MARKERS)
    is_sensitive = _contains_any(text, HR_OR_LEGAL_SENSITIVE_MARKERS)
    severity = _normalize(context.get("severity"))
    triage = context.get("comment_triage")
    triage = triage if isinstance(triage, dict) else None

    # Les sujets RH, juridiques ou institutionnels à forte sévérité ne
    # doivent jamais être traités comme une simple réponse de community manager.
    if severity == "high" and (is_sensitive or is_institutional) and not is_article:
        return ResponseDecision(
            action="internal_escalation",
            action_label="Escalade interne prioritaire",
            category="sensitive_high_risk_signal",
            reply_eligible=False,
            requires_human_validation=True,
            rationale=(
                "Le contenu à forte sévérité touche un sujet RH, juridique ou institutionnel. "
                "La direction compétente doit vérifier les faits avant toute communication."
            ),
            recommended_channel="direction_rh_juridique_communication",
            place_hint=place_hint,
        )

    # Pour les commentaires, le tri Claude/règles est calculé avant le sentiment.
    # Il évite de proposer une réponse à « l », un emoji, un tag ou un hors-sujet.
    if is_comment and triage:
        if not bool(triage.get("relevant", False)):
            return ResponseDecision(
                action="no_reply",
                action_label="Commentaire ignoré",
                category=str(triage.get("category") or "comment_noise"),
                reply_eligible=False,
                requires_human_validation=False,
                rationale=str(triage.get("reason") or "Commentaire sans information exploitable."),
                recommended_channel="aucun",
                place_hint=place_hint,
            )

        if bool(triage.get("reply_recommended", False)):
            return ResponseDecision(
                action="public_reply",
                action_label="Réponse publique recommandée",
                category=str(triage.get("category") or "operational_complaint"),
                reply_eligible=True,
                requires_human_validation=True,
                rationale=str(
                    triage.get("reason")
                    or "Le commentaire contient un retour concret auquel ARMA peut répondre."
                ),
                ask_for_private_details=bool(triage.get("needs_more_details", place_hint is None)),
                recommended_channel="reply_to_comment",
                place_hint=place_hint,
            )

        return ResponseDecision(
            action="monitor",
            action_label="Commentaire utile à surveiller",
            category=str(triage.get("category") or "feedback_to_review"),
            reply_eligible=False,
            requires_human_validation=True,
            rationale=str(
                triage.get("reason")
                or "Le commentaire est pertinent pour l'e-réputation mais ne nécessite pas une réponse publique."
            ),
            recommended_channel="social_listening",
            place_hint=place_hint,
        )

    if is_article:
        if is_institutional:
            return ResponseDecision(
                action="internal_escalation",
                action_label="Escalade communication / direction",
                category="institutional_press_alert",
                reply_eligible=False,
                requires_human_validation=True,
                rationale=(
                    "Il s'agit d'un article ou signal institutionnel. Une réponse de community manager "
                    "serait inadaptée ; il faut vérifier les faits et préparer, si nécessaire, un communiqué validé."
                ),
                recommended_channel="direction_communication",
                place_hint=place_hint,
            )

        return ResponseDecision(
            action="official_statement",
            action_label="Projet de communiqué à valider",
            category="press_article",
            reply_eligible=False,
            requires_human_validation=True,
            rationale=(
                "Le contenu est un article de presse. Le portail doit proposer un message de réserve ou un communiqué, "
                "pas une réponse directe demandant un lieu et une date."
            ),
            recommended_channel="communication_corporate",
            place_hint=place_hint,
        )

    if is_comment and has_operational_issue:
        return ResponseDecision(
            action="public_reply",
            action_label="Réponse publique recommandée",
            category="operational_complaint",
            reply_eligible=True,
            requires_human_validation=True,
            rationale="Le commentaire décrit un problème opérationnel auquel ARMA peut répondre directement.",
            ask_for_private_details=place_hint is None,
            recommended_channel="reply_to_comment",
            place_hint=place_hint,
        )

    if is_social_post and has_operational_issue and is_direct_request:
        return ResponseDecision(
            action="public_reply",
            action_label="Réponse publique recommandée",
            category="direct_social_complaint",
            reply_eligible=True,
            requires_human_validation=True,
            rationale="La publication interpelle directement ARMA au sujet d'un problème opérationnel.",
            ask_for_private_details=place_hint is None,
            recommended_channel="reply_to_post",
            place_hint=place_hint,
        )

    if is_social_post and (is_general_criticism or has_operational_issue):
        return ResponseDecision(
            action="monitor",
            action_label="Surveillance et vérification",
            category="general_social_criticism",
            reply_eligible=False,
            requires_human_validation=True,
            rationale=(
                "La publication relaie une critique générale ou un mécontentement collectif sans demande individuelle précise. "
                "Une réponse publique n'est pas automatique ; il faut d'abord vérifier le contexte."
            ),
            recommended_channel="social_listening",
            place_hint=place_hint,
        )

    return ResponseDecision(
        action="monitor",
        action_label="Surveillance",
        category="negative_mention_to_review",
        reply_eligible=False,
        requires_human_validation=True,
        rationale="La mention est négative mais ne contient pas assez d'éléments pour recommander une réponse publique.",
        recommended_channel="social_listening",
        place_hint=place_hint,
    )
