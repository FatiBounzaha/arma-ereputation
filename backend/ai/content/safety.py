from __future__ import annotations

import re
import unicodedata
from copy import deepcopy
from typing import Any

PLATFORM_BODY_LIMITS = {
    "x": 240,
    "linkedin": 2200,
    "instagram": 1800,
    "facebook": 1800,
}

# Les formulations absolues suivantes présentent un risque si elles ne sont pas
# soutenues mot pour mot par les preuves transmises au LLM.
UNSUPPORTED_ABSOLUTE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bgarant(?:it|issons|ie|ir)\b", "promesse absolue de garantie"),
    (r"\bsans interruption\b", "continuité absolue non prouvée"),
    (r"\bdepuis des années\b", "ancienneté non prouvée"),
    (r"\bnous font confiance\b", "relation client non prouvée"),
    (r"\bfiabilit[ée] reconnue\b", "reconnaissance externe non prouvée"),
    (r"\bpartenaire(?:s)? de confiance\b", "statut de partenaire non prouvé"),
    (r"\bleader\b|\bnum[ée]ro\s*1\b|\bn°\s*1\b", "position de marché non prouvée"),
    (r"\btoujours\b|\bjamais\b", "généralisation absolue"),
    (r"\bqualité garantie\b", "qualité garantie sans preuve"),
    (r"\bتضمن\b|\bبدون انقطاع\b|\bمنذ سنوات\b", "affirmation arabe absolue non prouvée"),
)

TECHNOLOGY_CLAIMS = (
    "capteur", "iot", "intelligence artificielle", "véhicule électrique",
    "flotte électrique", "plateforme numérique", "valorisation intelligente",
    "optimisation des flux", "réduction de l'empreinte carbone",
    "خفض البصمة الكربونية", "مركبات كهربائية", "أجهزة استشعار",
)

KNOWN_CITIES = (
    "casablanca", "rabat", "tanger", "kénitra", "kenitra", "marrakech",
    "agadir", "fès", "fes", "meknès", "meknes", "tétouan", "tetouan",
    "el jadida", "nouakchott", "الدار البيضاء", "الرباط", "طنجة",
    "القنيطرة", "مراكش", "فاس", "مكناس", "أكادير", "تطوان", "نواكشوط",
)

FRENCH_REPLACEMENTS = {
    "notre commitment": "notre engagement",
    "#MarochesDemain": "#MarocDeDemain",
    "#Marochesdemain": "#MarocDeDemain",
}

ARABIC_REPLACEMENTS = {
    "حلول رقمية وحلقية": "حلول رقمية ودائرية",
    "أساس النظافة الحضرية الجودة": "أساس جودة النظافة الحضرية",
}

HASHTAG_RE = re.compile(r"(?<!\w)#[\w\u0600-\u06ff]+", flags=re.UNICODE)
NUMBER_RE = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?(?:\s*%)?(?!\w)")


class PostSafetyError(RuntimeError):
    """Erreur de validation factuelle ou éditoriale d'un post généré."""


def normalize_for_matching(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold()
    return re.sub(r"\s+", " ", text).strip()


def _clean_text(value: Any, *, language: str) -> str:
    text = str(value or "")
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    replacements = FRENCH_REPLACEMENTS if language == "fr" else ARABIC_REPLACEMENTS
    for old, new in replacements.items():
        text = re.sub(re.escape(old), new, text, flags=re.IGNORECASE)
    return text


def _normalize_hashtag(value: str) -> str | None:
    tag = str(value or "").strip().replace(" ", "")
    if not tag:
        return None
    if not tag.startswith("#"):
        tag = "#" + tag
    tag = re.sub(r"[^#\w\u0600-\u06ff]", "", tag)
    return tag if len(tag) > 1 else None


def _extract_inline_hashtags(body: str) -> tuple[str, list[str]]:
    tags = HASHTAG_RE.findall(body)
    cleaned = HASHTAG_RE.sub(" ", body)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned, tags


def sanitize_post_payload(payload: dict[str, Any], platform: str) -> dict[str, Any]:
    """Normalise le JSON Claude sans masquer les erreurs factuelles."""

    cleaned = deepcopy(payload)
    for language in ("fr", "ar"):
        block = cleaned.get(language)
        if not isinstance(block, dict):
            raise PostSafetyError(f"Le bloc {language} doit être un objet JSON.")

        body = _clean_text(block.get("body"), language=language)
        body, inline_tags = _extract_inline_hashtags(body)
        hashtags: list[str] = []
        for raw_tag in list(block.get("hashtags") or []) + inline_tags:
            tag = _normalize_hashtag(raw_tag)
            if tag and tag.casefold() not in {item.casefold() for item in hashtags}:
                hashtags.append(tag)

        if not body:
            raise PostSafetyError(f"Le texte {language} est vide.")
        block["body"] = body
        block["hashtags"] = hashtags[:8]

    cleaned["image_prompt"] = _clean_text(cleaned.get("image_prompt"), language="fr")
    tone = cleaned.get("tone")
    cleaned["tone"] = [str(item).strip() for item in tone] if isinstance(tone, list) else []
    cleaned["platform"] = platform
    return cleaned


def _source_context(*values: str) -> str:
    return normalize_for_matching(" ".join(value for value in values if value))


def _unsupported_numbers(text: str, context: str) -> list[str]:
    context_numbers = {item.replace(" ", "") for item in NUMBER_RE.findall(context)}
    return sorted(
        {
            item.replace(" ", "")
            for item in NUMBER_RE.findall(text)
            if item.replace(" ", "") not in context_numbers
        }
    )


def validate_post_payload(
    payload: dict[str, Any],
    *,
    platform: str,
    evidence_text: str,
    angle_title: str,
    angle_description: str,
) -> list[str]:
    """Retourne la liste des problèmes éditoriaux/factuels détectés."""

    issues: list[str] = []
    context = _source_context(evidence_text, angle_title, angle_description)

    for language in ("fr", "ar"):
        block = payload.get(language) or {}
        body = str(block.get("body") or "")
        normalized_body = normalize_for_matching(body)

        limit = PLATFORM_BODY_LIMITS.get(platform, 1800)
        rendered_length = len(body) + sum(len(str(tag)) + 1 for tag in block.get("hashtags") or [])
        if rendered_length > limit:
            issues.append(
                f"Le contenu {language} dépasse la limite éditoriale de {platform} "
                f"({rendered_length}>{limit} caractères)."
            )

        for pattern, label in UNSUPPORTED_ABSOLUTE_PATTERNS:
            if re.search(pattern, normalized_body, flags=re.IGNORECASE):
                # Une formulation absolue ne passe que si elle est présente dans
                # les preuves elles-mêmes, et non seulement dans l'angle générique.
                if not re.search(pattern, normalize_for_matching(evidence_text), flags=re.IGNORECASE):
                    issues.append(f"{language}: {label}.")

        numbers = _unsupported_numbers(body, context)
        if numbers:
            issues.append(f"{language}: chiffre(s) absent(s) des preuves : {', '.join(numbers)}.")

        for city in KNOWN_CITIES:
            normalized_city = normalize_for_matching(city)
            if normalized_city in normalized_body and normalized_city not in context:
                issues.append(f"{language}: ville non justifiée par les preuves : {city}.")

        organization_markers = (
            "arma", "notre", "nos ", "nous ", "nous.",
            "أرما", "نحن", "لدينا", "نقدم", "نستخدم", "نلتزم",
        )
        attributes_to_organization = any(
            normalize_for_matching(marker) in normalized_body
            for marker in organization_markers
        )
        normalized_evidence = normalize_for_matching(evidence_text)
        for claim in TECHNOLOGY_CLAIMS:
            normalized_claim = normalize_for_matching(claim)
            if (
                normalized_claim in normalized_body
                and attributes_to_organization
                and normalized_claim not in normalized_evidence
            ):
                issues.append(f"{language}: technologie attribuée à ARMA sans preuve : {claim}.")

        if language == "fr" and re.search(r"\b(commitment|reliability|sustainable solutions)\b", body, re.I):
            issues.append("fr: anglicisme ou segment anglais détecté.")

    image_prompt = normalize_for_matching(str(payload.get("image_prompt") or ""))
    if "logo arma" in image_prompt or "uniforme arma" in image_prompt:
        issues.append(
            "Le prompt image demande un logo ou uniforme ARMA potentiellement inventé ; "
            "utiliser une tenue professionnelle neutre ou fournir une charte officielle."
        )

    return list(dict.fromkeys(issues))


def prepare_and_validate_post_payload(
    payload: dict[str, Any],
    *,
    platform: str,
    evidence_text: str,
    angle_title: str,
    angle_description: str,
) -> dict[str, Any]:
    cleaned = sanitize_post_payload(payload, platform)
    issues = validate_post_payload(
        cleaned,
        platform=platform,
        evidence_text=evidence_text,
        angle_title=angle_title,
        angle_description=angle_description,
    )
    if issues:
        raise PostSafetyError(" | ".join(issues))
    return cleaned
