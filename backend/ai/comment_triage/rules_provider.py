from __future__ import annotations

import re
import unicodedata

from backend.ai.comment_triage.base import CommentTriageResult


# Les mots positifs (merci, bravo, top, mzyan...) ne sont plus classés comme
# bruit : ils participent au score lorsqu'ils sont publiés sous un post ARMA.
NOISE_WORDS = {
    "l", "ok", "okay", "lol", "mdr", "yes", "non", "oui", "up", "vu", "تم",
}

COMPETITOR_MARKERS = (
    "ozone", "averda", "veolia", "suez", "derichebourg", "mecomar",
    "sos ndd", "pizzorno", "tecmed",
)

ARMA_MARKERS = (
    "arma", "شركة أرما", "ارما", "أرما",
)

# Marqueurs réellement liés au métier ARMA. On évite volontairement les termes
# trop génériques (ville, service, société, agent...) : ils rendaient pertinent
# presque n'importe quel commentaire publié sous un post rattaché à ARMA.
OPERATIONAL_MARKERS = (
    "catastroph", "sale", "saleté", "dechet", "déchet", "ordure", "poubelle",
    "collecte", "ramassage", "netto", "odeur", "retard de collecte", "camion benne",
    "balayage", "assainissement", "propreté", "benne", "conteneur", "bac à ordures",
    "décharge", "decharge", "encombrant", "voirie",
    "النفايات", "الأزبال", "القمامة", "النظافة", "جمع النفايات", "كنس",
    "حاوية", "حاويات", "الزبل", "زبل", "كارث", "وسخ",
)

# Sujets explicitement hors périmètre de la propreté urbaine. Ils sont utiles
# surtout lorsque Claude est indisponible et que le moteur de règles prend le relais.
OFF_TOPIC_DOMAIN_MARKERS = (
    "logement social", "السكن الاجتماعي", "السكن", "emploi", "recrutement",
    "وظيفة", "أبحث عن عمل", "طلب عمل", "البحث عن عمل", "visa", "تأشيرة", "قرض", "crédit bancaire", "credit bancaire",
    "aide sociale", "مساعدة اجتماعية", "القوات المساعدة", "طلب استعطاف",
)

NEGATIVE_MARKERS = (
    "catastroph", "mauvais", "problème", "probleme", "honte", "nul", "jamais",
    "pas propre", "sale", "retard", "dégrad", "degrad", "pire", "manque",
    "aucun", "ne fait pas", "ne ramasse pas", "pas ramass", "plainte", "scandale",
    "déçu", "decu", "insatisf", "inacceptable", "lamentable", "horrible",
    "préoccup", "preoccup", "laisse à désirer", "laisse a désirer", "laisse a desirer",
    "reste sur la voie", "restent sur la voie", "sans lumière", "sans lumiere",
    "aucune propreté", "aucune proprete", "pas de propreté", "pas de proprete",
    "كارث", "سيئ", "مشكلة", "وسخ", "تقصير", "فشل", "لا تقوم", "لم يتم",
    "ضعيف", "غير مقبول", "ما كاينش", "مكيجمعوش",
)

POSITIVE_MARKERS = (
    # Signaux positifs explicites. Éviter « propre » seul : il est contenu dans
    # « propreté » et transformait des plaintes comme « aucune propreté » en positif.
    "bravo", "merci", "top", "excellent", "excellente", "bon travail", "bonne initiative",
    "très bien", "tres bien", "bien propre", "très propre", "tres propre",
    "satisfait", "satisfaite", "félicit", "felicit", "continuez", "efficace",
    "شكرا", "مزيان", "برافو", "عمل جيد", "خدمة جيدة", "نظيف", "ممتاز",
)

QUESTION_MARKERS = ("?", "؟", "pourquoi", "comment", "quand", "où", "هل", "علاش", "فاش", "فين")

SUGGESTION_MARKERS = (
    "il faut", "vous devez", "vous devriez", "merci de", "pensez à", "pensez a",
    "il faudrait", "veuillez", "نطلب", "يجب", "خاص", "خصكم", "من الأفضل",
)

EXPLICIT_DEFENCE_MARKERS = (
    "arma n'y peut rien", "arma ny peut rien", "ce n'est pas la faute d'arma",
    "ce nest pas la faute darma", "ماشي مشكل أرما", "ليست مشكلة أرما",
)

SHARED_RESPONSIBILITY_MARKERS = (
    "la faute des habitants", "population", "habitants", "citoyens",
    "jettent leurs ordures", "jeter leurs ordures", "les gens sont sales",
    "responsabilité partagée", "responsabilite partagee", "civisme",
    "السكان", "المواطنين",
)

SPAM_MARKERS = (
    "whatsapp", "promo", "promotion", "livraison gratuite", "cliquez ici",
    "contactez-nous", "gagnez", "bitcoin", "crypto", "forex", "telegram",
)

INSULT_ONLY_MARKERS = (
    "idiot", "imbécile", "imbecile", "voleur", "escroc", "لعنة", "حمير", "كلاب",
)


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "").casefold().strip()
    return re.sub(r"\s+", " ", value)


def alphanumeric_count(text: str) -> int:
    return sum(character.isalnum() for character in text)


def is_price_only_or_gibberish(text: str) -> bool:
    value = normalize(text)
    if re.fullmatch(r"[\s\d.,]+(?:dh|dhs|mad|€|\$|usd)?[!?]*", value):
        return True
    if re.fullmatch(r"(?:dh|dhs|mad|€|\$|usd)?[\s\d.,]+[!?]*", value):
        return True
    return False


def is_obvious_noise(text: str) -> bool:
    normalized = normalize(text)
    if not normalized or alphanumeric_count(normalized) < 2:
        return True
    if normalized in NOISE_WORDS or is_price_only_or_gibberish(normalized):
        return True
    if any(marker in normalized for marker in SPAM_MARKERS):
        return True
    tokens = re.findall(r"[\w\u0600-\u06ff]+", normalized, flags=re.UNICODE)
    if len(tokens) == 1 and len(tokens[0]) <= 2:
        return True
    return False


def mentions_only_competitor(text: str) -> bool:
    normalized = normalize(text)
    return (
        any(marker in normalized for marker in COMPETITOR_MARKERS)
        and not any(marker in normalized for marker in ARMA_MARKERS)
    )


def _result(
    *,
    relevant: bool,
    reply: bool,
    category: str,
    sentiment: str,
    confidence: float,
    reason: str,
    details: bool = False,
    extra_flags: list[str] | None = None,
) -> CommentTriageResult:
    flags = ["comment_relevant" if relevant else "comment_noise"]
    flags.append("comment_actionable" if reply else "comment_not_actionable")
    flags.extend(extra_flags or [])
    return CommentTriageResult(
        relevant=relevant,
        reply_recommended=reply,
        category=category,
        sentiment=sentiment,
        confidence=confidence,
        reason=reason,
        needs_more_details=details,
        quality_flags=list(dict.fromkeys(flags)),
        model_provider="rules",
        model_name="comment-rules-final-v2",
    )


class RulesCommentTriageProvider:
    """Classe tous les commentaires utiles pour le score, pas seulement les plaintes."""

    model_name = "comment-rules-final-v2"

    def classify(
        self,
        *,
        comment_text: str,
        parent_title: str | None = None,
        parent_text: str | None = None,
        organization_name: str = "ARMA",
        language_hint: str | None = None,
    ) -> CommentTriageResult:
        text = normalize(comment_text)
        parent_context = normalize(" ".join([parent_title or "", parent_text or ""]))

        if is_obvious_noise(text):
            return _result(
                relevant=False,
                reply=False,
                category="noise",
                sentiment="neutral",
                confidence=0.99,
                reason="Commentaire vide, publicitaire, composé uniquement d'un prix ou sans information exploitable.",
            )

        if mentions_only_competitor(text):
            return _result(
                relevant=False,
                reply=False,
                category="competitor_only",
                sentiment="neutral",
                confidence=0.97,
                reason="Le commentaire concerne uniquement un concurrent et non ARMA.",
                extra_flags=["competitor_only"],
            )

        operational = any(marker in text for marker in OPERATIONAL_MARKERS)
        negative = any(marker in text for marker in NEGATIVE_MARKERS)
        positive = any(marker in text for marker in POSITIVE_MARKERS)
        question = any(marker in text for marker in QUESTION_MARKERS)
        suggestion = any(marker in text for marker in SUGGESTION_MARKERS)
        explicit_defence = any(marker in text for marker in EXPLICIT_DEFENCE_MARKERS)
        shared_responsibility = any(marker in text for marker in SHARED_RESPONSIBILITY_MARKERS)
        explicit_arma = any(marker in text for marker in ARMA_MARKERS)
        parent_is_arma = any(marker in parent_context for marker in ARMA_MARKERS)
        off_topic_domain = any(marker in text for marker in OFF_TOPIC_DOMAIN_MARKERS)
        service_responsibility = any(
            marker in text
            for marker in (
                "société", "societe", "entreprise", "service de propreté",
                "agents de propreté", "camion", "collecte", "nettoyage",
                "شركة النظافة", "خدمة النظافة", "عمال النظافة",
            )
        )
        # Une publication parente rattachée à ARMA n'est plus suffisante, à elle
        # seule, pour déclarer une longue demande sans rapport comme pertinente.
        # On accepte sous le post parent les réactions polarisées courtes
        # ("bravo", "c'est pire"...), mais une question/suggestion doit parler
        # explicitement d'ARMA ou du métier de propreté.
        parent_reaction = parent_is_arma and (positive or negative)
        concerns_arma = explicit_arma or operational or service_responsibility or parent_reaction
        tokens = re.findall(r"[\w\u0600-\u06ff]+", text, flags=re.UNICODE)

        if off_topic_domain and not explicit_arma and not operational:
            return _result(
                relevant=False,
                reply=False,
                category="off_topic",
                sentiment="neutral",
                confidence=0.96,
                reason="Le commentaire traite d'un sujet extérieur à la propreté urbaine/ARMA (ex. logement, emploi ou demande administrative).",
                extra_flags=["off_topic_domain"],
            )

        # Une défense explicite d'ARMA ou une attribution du problème aux citoyens
        # n'est PAS automatiquement un avis positif sur la qualité du service.
        # Par défaut, c'est un signal neutre de responsabilité partagée.
        if (explicit_defence or shared_responsibility) and concerns_arma and not (explicit_arma and negative):
            return _result(
                relevant=True,
                reply=bool(question or suggestion),
                category="general_feedback" if not suggestion else "suggestion",
                sentiment="neutral",
                confidence=0.9 if explicit_defence else 0.82,
                reason="Le commentaire défend ARMA ou attribue la responsabilité à des tiers/citoyens; il reste neutre sauf éloge explicite du service.",
                details=bool(question or suggestion),
                extra_flags=["reputation_signal", "sentiment_guardrail_neutral"],
            )

        # Une plainte explicite garde la priorité sur « merci », « bravo » ou une
        # formulation constructive. Ex.: « Merci de faire le nécessaire, c'est très sale ».
        if negative and concerns_arma:
            insult_only = any(marker in text for marker in INSULT_ONLY_MARKERS) and not operational
            return _result(
                relevant=True,
                reply=not insult_only,
                category="operational_complaint" if operational else "general_criticism",
                sentiment="negative",
                confidence=0.92 if explicit_arma else 0.86,
                reason=(
                    "Plainte négative concernant ARMA ou son service; une formulation polie ou constructive ne transforme pas la critique en avis positif."
                    if not insult_only
                    else "Critique négative liée à ARMA, conservée pour le score et l'alerte mais sans réponse publique automatique."
                ),
                details=operational,
                extra_flags=["reputation_signal", "negative_alert_candidate", "strong_sentiment_guardrail"],
            )

        # Un avis est positif seulement s'il contient un signal positif explicite
        # ET ne contient ni plainte ni suggestion corrective.
        if positive and concerns_arma and not suggestion:
            return _result(
                relevant=True,
                reply=False,
                category="positive_feedback",
                sentiment="positive",
                confidence=0.9 if explicit_arma else 0.8,
                reason="Éloge ou satisfaction explicite envers ARMA ou la qualité du service.",
                extra_flags=["reputation_signal", "strong_sentiment_guardrail"],
            )


        if suggestion and (explicit_arma or operational or service_responsibility):
            return _result(
                relevant=True,
                reply=True,
                category="suggestion",
                sentiment="neutral",
                confidence=0.8,
                reason="Suggestion concrète liée au service ARMA; elle contribue au score neutre et mérite une réponse ou un accusé de prise en compte.",
                details=operational,
                extra_flags=["reputation_signal"],
            )

        if question and (explicit_arma or operational or service_responsibility):
            return _result(
                relevant=True,
                reply=True,
                category="service_question",
                sentiment="neutral",
                confidence=0.78,
                reason="Question liée au service ARMA; elle contribue au score neutre et peut recevoir une réponse.",
                extra_flags=["reputation_signal"],
            )

        if operational and concerns_arma:
            return _result(
                relevant=True,
                reply=False,
                category="service_feedback",
                sentiment="neutral",
                confidence=0.72,
                reason="Retour opérationnel compréhensible sur le service, classé neutre en l'absence de polarité claire.",
                extra_flags=["reputation_signal"],
            )

        if (explicit_arma or operational or service_responsibility) and len(tokens) >= 1:
            return _result(
                relevant=True,
                reply=False,
                category="general_feedback",
                sentiment="neutral",
                confidence=0.68,
                reason="Commentaire explicitement lié à ARMA ou au métier de propreté, conservé comme signal neutre pour le score.",
                extra_flags=["reputation_signal"],
            )

        return _result(
            relevant=False,
            reply=False,
            category="off_topic",
            sentiment="neutral",
            confidence=0.78,
            reason="Le commentaire n'est pas relié à ARMA, à son service ou au sujet de la publication.",
        )
