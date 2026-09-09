from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


CATEGORY_LABELS = {
    "innovation_sectorielle": "Innovation sectorielle",
    "economie_circulaire": "Économie circulaire",
    "reglementation": "Réglementation",
    "marche_public": "Marché public",
    "attribution_contrat": "Attribution de contrat",
    "opportunite_commerciale": "Opportunité commerciale",
    "veille_concurrentielle": "Veille concurrentielle",
    "veille_concurrentielle_sensible": "Veille concurrentielle sensible",
    "risque_reputationnel": "Risque réputationnel",
    "procedure_judiciaire": "Procédure judiciaire",
    "ressources_humaines": "Ressources humaines",
    "plainte_client": "Plainte client",
    "qualite_service": "Qualité de service",
    "institutionnel": "Institutionnel",
    "historique_marche": "Historique du marché",
    "information_generale": "Information générale",
}

MOROCCO_MARKERS = (
    "maroc", "morocco", "marocain", "marocaine", "royaume", "casablanca",
    "rabat", "tanger", "marrakech", "agadir", "fes", "fès", "meknes",
    "kénitra", "kenitra", "oujda", "tetouan", "tétouan", "safi",
    "el jadida", "bouznika", "collectivite territoriale", "commune",
)


def geographic_scope(*values: str | None, country: str | None = None) -> dict[str, Any]:
    """Return an explainable Morocco/international classification."""
    country_value = _normalise(country)
    combined = _normalise(" ".join(value or "" for value in values))
    if country_value in {"ma", "maroc", "morocco"}:
        return {"scope": "morocco", "label": "Maroc", "confidence": "confirmed", "reason": "Pays fourni par la source"}
    markers = [marker for marker in MOROCCO_MARKERS if _normalise(marker) in combined]
    if markers:
        return {"scope": "morocco", "label": "Maroc", "confidence": "inferred", "reason": f"Indice géographique : {markers[0]}"}
    if country_value:
        return {"scope": "international", "label": "International", "confidence": "confirmed", "reason": f"Pays source : {country}"}
    return {"scope": "unknown", "label": "Zone à vérifier", "confidence": "unknown", "reason": "Aucun indice géographique fiable"}


def clean_source_name(author_name: str | None, technical_name: str | None, url: str | None = None) -> str:
    """Prefer a readable publisher name and remove technical/numeric identifiers."""
    candidate = " ".join((author_name or "").split()).strip(" -–—|·")
    if not candidate or candidate.isdigit() or re.fullmatch(r"[\w-]*\d{5,}[\w-]*", candidate):
        candidate = " ".join((technical_name or "").split()).strip(" -–—|·")
    candidate = re.sub(r"\s*\(?(?:id|source)[ :#-]*\d+\)?\s*$", "", candidate, flags=re.I).strip()
    if candidate and candidate.casefold() not in {"serper", "search_api", "facebook", "rss"}:
        return candidate
    match = re.search(r"https?://(?:www\.)?([^/]+)", url or "", flags=re.I)
    return match.group(1).removeprefix("www.") if match else (candidate or "Source non identifiée")


def specific_business_insight(category: str, title: str | None, text: str | None, geo: dict[str, Any], state: str) -> str:
    """Create a deterministic, content-specific ARMA reading without inventing facts."""
    subject = (title or clean_display_text(None, text)["display_excerpt"] or "ce signal")[:140]
    place = geo.get("label", "Zone à vérifier")
    if category == "procedure_judiciaire":
        action = "Veille sensible à suivre en interne; aucune communication externe sans validation juridique."
    elif category == "marche_public":
        action = "Vérifier l’échéance, le résultat et le statut officiel avant toute action commerciale."
    elif category == "attribution_contrat":
        action = "Confirmer l’attribution, les zones et la date de démarrage auprès d’une source officielle."
    elif category == "plainte_client":
        action = "Transmettre aux opérations pour vérification du lieu et du service avant de préparer un brouillon de réponse."
    elif category == "veille_concurrentielle":
        action = "Comparer ce signal aux implantations et preuves de performance vérifiées d’ARMA, pour usage interne."
    elif category in {"reglementation", "institutionnel"}:
        action = "Identifier l’impact réglementaire ou opérationnel pour ARMA et faire valider l’interprétation."
    elif category in {"innovation_sectorielle", "economie_circulaire"}:
        action = "Évaluer l’applicabilité aux contrats et équipements réellement déployés par ARMA avant communication."
    else:
        action = "Surveiller et vérifier la pertinence concrète pour les activités d’ARMA avant réutilisation."
    freshness_note = "Contenu ancien : usage contextuel uniquement." if state in {"context", "historical"} else ""
    return f"{subject} — Zone : {place}. {action} {freshness_note}".strip()


def confidence_level(mention_count: int) -> dict[str, Any]:
    count = max(0, int(mention_count or 0))
    if count >= 20:
        return {"level": "high", "label": "Confiance élevée", "score": min(100, 70 + count), "reason": f"{count} mentions sur la période"}
    if count >= 7:
        return {"level": "medium", "label": "Confiance moyenne", "score": 45 + count, "reason": f"{count} mentions sur la période"}
    return {"level": "low", "label": "Confiance faible", "score": min(40, count * 6), "reason": f"Échantillon limité : {count} mention(s)"}

SENSITIVE = (
    "procedure judiciaire", "justice", "tribunal", "accusation", "accuse",
    "corruption", "surfacturation", "arrestation", "conflit d'interets",
    "conflit d’intérêts", "fraude", "enquete", "enquête",
)


def _normalise(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    return " ".join("".join(ch for ch in text if not unicodedata.combining(ch)).casefold().split())


def freshness(published_at: datetime | None, *, now: datetime | None = None) -> str:
    """Classify freshness strictly from publication time, never collection time."""
    if published_at is None:
        return "unknown"
    reference = now or datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age = max(0, (reference - published_at).days)
    if age < 7:
        return "fresh"
    if age <= 30:
        return "recent"
    if age <= 90:
        return "context"
    return "historical"


def clean_display_text(title: str | None, raw_text: str | None, *, social: bool = False) -> dict[str, Any]:
    """Build display-only fields without altering the source payload."""
    original = (raw_text or "").strip()
    excerpt = re.sub(r"https?://\S+|www\.\S+", " ", original, flags=re.I)
    excerpt = re.sub(r"(?:\s*\.{3,}\s*)+", "… ", excerpt)
    excerpt = re.sub(r"\b([\wÀ-ÿ]+)(?:\s+\1\b)+", r"\1", excerpt, flags=re.I)
    excerpt = " ".join(excerpt.split()).strip(" -–—|…")
    source_title = " ".join((title or "").split()).strip(" -–—|…")
    generated = False
    if not source_title and social:
        cautious = excerpt[:100].rstrip(" ,.;:!?")
        source_title = f"Publication sociale à vérifier — {cautious}" if cautious else "Publication sociale à vérifier"
        generated = True
    return {
        "display_title": source_title or None,
        "display_excerpt": excerpt[:500] or None,
        "display_title_generated": generated,
        "raw_text": original,
    }


def classify_business(title: str | None, text: str | None) -> str:
    value = _normalise(f"{title or ''} {text or ''}")
    if any(_normalise(marker) in value for marker in SENSITIVE):
        return "procedure_judiciaire"
    if any(word in value for word in ("appel d'offres", "appel offres", "marche public", "tender")):
        return "marche_public"
    if any(word in value for word in ("attribue", "attribution", "remporte le marche", "contrat attribue")):
        return "attribution_contrat"
    if any(word in value for word in ("plainte", "retard de collecte", "dechets non collectes", "salete")):
        return "plainte_client"
    if any(word in value for word in ("loi", "decret", "reglement", "conformite")):
        return "reglementation"
    if any(word in value for word in ("recyclage", "economie circulaire", "valorisation des dechets")):
        return "economie_circulaire"
    if any(word in value for word in ("innovation", "technologie", "digital", "intelligence artificielle")):
        return "innovation_sectorielle"
    return "information_generale"


@dataclass(frozen=True)
class RouteDecision:
    marketing_allowed: bool
    reputation_required: bool
    internal_only: bool
    legal_review_required: bool
    public_communication_allowed: bool
    destination: str
    sensitivity: str
    validation_required: str
    business_insight: str


def route_content(
    category: str,
    published_at: datetime | None,
    *,
    official_source: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    # `now` rend le routage testable et deterministe. Sans lui, la
    # fraicheur etait toujours evaluee par rapport a l'heure reelle :
    # un test a date fixe finissait par basculer de "recent" a
    # "context" au 31e jour, et echouait sans qu'aucun code ne change.
    state = freshness(published_at, now=now)
    if category in {"procedure_judiciaire", "veille_concurrentielle_sensible"}:
        decision = RouteDecision(False, True, True, True, False, "Interne / Réputation", "critique", "Juridique obligatoire", "Veille concurrentielle sensible à suivre en interne. Aucune communication externe sans validation juridique.")
    elif category == "plainte_client":
        decision = RouteDecision(False, True, False, False, True, "Réputation", "élevée", "Validation humaine", "Vérifier les faits opérationnels et préparer uniquement un brouillon de réponse soumis à validation humaine.")
    elif category == "attribution_contrat":
        allowed = bool(official_source and state in {"fresh", "recent"})
        decision = RouteDecision(allowed, False, not allowed, False, allowed, "Marketing" if allowed else "Interne", "moyenne", "Source officielle et validation interne", "Vérifier les zones attribuées, la date de démarrage et une source officielle avant de préparer une communication.")
    elif category == "marche_public" and state in {"historical", "context"}:
        decision = RouteDecision(False, False, True, False, False, "Interne / Historique", "faible", "Vérification du statut", "Vérifier le résultat et le statut actuel de l’appel d’offres avant toute action commerciale.")
    elif state in {"historical", "context", "unknown"}:
        decision = RouteDecision(False, False, True, False, False, "Contexte / Historique", "faible", "Vérification de la date", "Conserver comme contexte; ne pas présenter ce contenu comme une opportunité actuelle.")
    else:
        decision = RouteDecision(True, False, False, False, True, "Marketing", "faible", "Validation éditoriale", "Usage commercial interne ou communication externe selon pertinence et preuves vérifiées.")
    return {**asdict(decision), "freshness": state}


def analyse_comment(text: str | None) -> dict[str, Any]:
    value = _normalise(text)
    if len(re.sub(r"\W", "", value)) < 3 or re.search(r"\b(spam|promo|bitcoin|crypto)\b", value):
        return {"category": "spam", "decision": "no_reply", "reply_required": False}
    if any(_normalise(marker) in value for marker in SENSITIVE):
        return {"category": "affaire_juridique", "decision": "internal_escalation", "reply_required": False, "legal_risk": True}
    if any(word in value for word in ("retard", "pas collecte", "non collecte", "salete", "ordures")):
        return {"category": "plainte_operationnelle", "decision": "public_reply", "reply_required": True, "human_validation_required": True}
    return {"category": "autre", "decision": "monitor", "reply_required": False}
