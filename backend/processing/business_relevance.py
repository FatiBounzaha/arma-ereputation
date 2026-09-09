from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from backend.services.rss_relevance_service import normalize_text


MARKETING_CATEGORIES = (
    "competitor",
    "opportunity",
    "regulation",
    "innovation",
    "sector",
)

# Signaux qui ont une valeur métier pour la direction Marketing / Communication.
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "opportunity": (
        "appel d offres", "marche public", "marches publics", "contrat",
        "concession", "gestion deleguee", "delegation de service public",
        "adjudication", "attribution", "soumission", "cahier des charges",
        "partenariat public prive", "investissement", "projet", "extension",
        "صفقه عموميه", "طلب عروض", "تدبير مفوض", "عقد", "مشروع",
    ),
    "regulation": (
        "reglementation", "loi", "decret", "norme", "obligation",
        "tri a la source", "etude d impact", "impact environnemental",
        "autorisation environnementale", "taxe", "sanction", "mise en demeure",
        "قانون", "مرسوم", "تنظيم", "الفرز من المصدر", "دراسه التاثير",
    ),
    "innovation": (
        "innovation", "intelligence artificielle", "digitalisation", "smart city",
        "vehicule electrique", "flotte electrique", "capteur", "iot", "robot",
        "recyclage", "valorisation", "economie circulaire", "decarbonation",
        "energie propre", "mobilite durable", "technologie", "plateforme numerique",
        "ابتكار", "الذكاء الاصطناعي", "مدينه ذكيه", "اعاده التدوير",
        "الاقتصاد الدائري", "رقمنه",
    ),
    "competitor": (
        "redressement", "difficulte financiere", "difficultes financieres",
        "faillite", "litige", "proces", "condamnation", "amende", "greve",
        "rupture de contrat", "resiliation", "performance", "resultats",
        "chiffre d affaires", "croissance", "acquisition", "fusion", "restructuration",
        "nouveau marche", "gagne le marche", "remporte", "perd le marche",
        "تعثر مالي", "افلاس", "نزاع", "اضراب", "فسخ العقد", "صفقه جديده",
    ),
    "sector": (
        "proprete urbaine", "collecte des dechets", "gestion des dechets",
        "dechets menagers", "nettoyage urbain", "traitement des dechets",
        "traitement de l eau", "eaux usees", "assainissement", "decharge",
        "centre d enfouissement", "ville durable", "developpement durable",
        "النظافه الحضريه", "جمع النفايات", "تدبير النفايات", "معالجه النفايات",
        "معالجه المياه", "التطهير السائل", "التنميه المستدامه",
    ),
}

# Contenus qui remplissent la base mais n'aident pas la veille stratégique.
NOISE_KEYWORDS: tuple[str, ...] = (
    "a rejoint", "rejoint suez", "joined", "a occupe", "nomme au poste",
    "nomination de", "parcours professionnel", "profil de", "employee",
    "recrutement", "recrute", "hiring", "offre d emploi", "job", "career",
    "anniversaire", "eid mubarak", "bonne fete", "happy eid", "photo added",
    "added a new photo", "on reels", "reels", "about", "mentions j aime",
    "responsable de", "directeur chez", "etudiant", "stagiaire", "cv",
    "aimez et partagez", "follow us", "abonnez vous",
    "توظيف", "وظيفه", "وظائف", "انضم الى", "مسار مهني", "عيد مبارك",
)

MOROCCO_KEYWORDS: tuple[str, ...] = (
    "maroc", "casablanca", "rabat", "fes", "fès", "tanger", "marrakech",
    "agadir", "kenitra", "kénitra", "meknes", "meknès", "nouakchott",
    "المغرب", "الدار البيضاء", "الرباط", "فاس", "طنجه", "مراكش",
)

# Alias ambigus qui ne peuvent pas être acceptés seuls.
AMBIGUOUS_ORGANIZATIONS = {"OZONE", "SOS", "ARMA"}


@dataclass(frozen=True)
class BusinessRelevanceDecision:
    category: str | None
    score: float
    display_in_marketing: bool
    summary: str
    reasons: list[str]
    quality_flags: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _combined_text(result: dict[str, Any]) -> str:
    values = (
        result.get("title"),
        result.get("snippet"),
        result.get("summary"),
        result.get("description"),
        result.get("raw_text"),
    )
    return normalize_text(" ".join(str(value) for value in values if value))


def _contains_any(text: str, keywords: tuple[str, ...]) -> list[str]:
    matches: list[str] = []
    for keyword in keywords:
        normalized = normalize_text(keyword)
        if normalized and re.search(rf"(?<!\w){re.escape(normalized)}(?!\w)", text):
            matches.append(keyword)
    return matches


def _build_summary(result: dict[str, Any], limit: int = 240) -> str:
    snippet = str(result.get("snippet") or result.get("summary") or "").strip()
    title = str(result.get("title") or "").strip()
    summary = snippet or title
    summary = re.sub(r"\s+", " ", summary)
    if len(summary) > limit:
        summary = summary[: limit - 1].rstrip() + "…"
    return summary


def evaluate_business_relevance(
    result: dict[str, Any],
    *,
    organizations: list[str] | tuple[str, ...] = (),
    sector_topics: list[str] | tuple[str, ...] = (),
    content_origin: str | None = None,
    content_purpose: str | None = None,
    source_name: str | None = None,
    query_category: str | None = None,
) -> BusinessRelevanceDecision:
    """Évalue si un contenu mérite d'apparaître dans la veille Marketing.

    Cette décision est volontairement déterministe : la collecte brute et le
    filtrage qualité doivent rester traçables. Un LLM pourra ensuite résumer ou
    challenger les cas proches du seuil, mais il ne remplace pas ces règles.
    """

    text = _combined_text(result)
    reasons: list[str] = []
    flags: list[str] = []
    score = 0.0

    noise_matches = _contains_any(text, NOISE_KEYWORDS)
    if noise_matches:
        score -= 0.70
        flags.append("noise_or_hr_content")
        reasons.append("contenu RH, profil ou publication sociale générique")

    if content_purpose == "employment":
        score -= 0.60
        flags.append("employment")

    if content_origin == "owned":
        # Les publications officielles restent utiles dans la base de réputation,
        # mais elles ne sont pas la veille stratégique attendue dans le POC Contenu.
        score -= 0.20
        flags.append("owned_content")

    organizations = list(dict.fromkeys(organizations))
    if organizations:
        score += 0.20
        reasons.append("entreprise surveillée détectée")

    if any(name != "ARMA" for name in organizations):
        score += 0.15
        reasons.append("signal concurrentiel")

    if sector_topics:
        score += min(0.25, 0.10 + 0.05 * len(set(sector_topics)))
        reasons.append("lien explicite avec le secteur ARMA")

    category_scores: dict[str, float] = {}
    category_matches: dict[str, list[str]] = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        matches = _contains_any(text, keywords)
        category_matches[category] = matches
        category_scores[category] = min(0.45, 0.14 * len(matches))

    if query_category in MARKETING_CATEGORIES:
        category_scores[query_category] = category_scores.get(query_category, 0.0) + 0.12

    category = max(category_scores, key=category_scores.get)
    category_strength = category_scores[category]
    if category_strength > 0:
        score += category_strength
        reasons.append(f"signal métier : {category}")
    else:
        category = None

    if _contains_any(text, MOROCCO_KEYWORDS):
        score += 0.08
        reasons.append("contexte Maroc / villes ciblées")

    if source_name and source_name.casefold() not in {
        "facebook", "instagram", "linkedin", "x / twitter"
    }:
        score += 0.05

    # Un alias ambigu n'est jamais suffisant sans contexte sectoriel ou stratégique.
    if organizations and all(name in AMBIGUOUS_ORGANIZATIONS for name in organizations):
        if not sector_topics and category_strength < 0.20:
            score -= 0.35
            flags.append("ambiguous_entity_without_sector_context")

    if not str(result.get("date") or result.get("published_at") or "").strip():
        flags.append("date_missing")
        score -= 0.05

    score = max(0.0, min(1.0, score))
    display = bool(category and score >= 0.62 and not noise_matches)

    if not display and "low_business_relevance" not in flags:
        flags.append("low_business_relevance")

    return BusinessRelevanceDecision(
        category=category,
        score=round(score, 3),
        display_in_marketing=display,
        summary=_build_summary(result),
        reasons=reasons,
        quality_flags=flags,
    )
