from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlsplit, urlunsplit

from dateutil.relativedelta import relativedelta
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.collectors.serper_client import SerperClient
from backend.database.connection import SessionLocal
from backend.database.models import (
    Mention,
    MentionOrganization,
    Organization,
    PipelineRun,
    Source,
    WatchQuery,
)
from backend.services.collection_service import (
    clean_text,
    create_content_hash,
    create_external_id,
    create_pipeline_run,
    get_serper_source,
    mark_pipeline_as_failed,
    utc_now,
)
from backend.services.rss_relevance_service import classify_article
from backend.processing.business_relevance import evaluate_business_relevance


# ============================================================
# Configuration
# ============================================================

ORGANIZATION_SEARCH_NAMES: dict[str, str] = {
    "ARMA": "ARMA Environnement",
    "OZONE": "OZONE Environnement",
    "Averda": "Averda Maroc",
    "Suez Maroc": "Suez Maroc",
    "SOS": "SOS NDD",
}

PLATFORMS: dict[str, dict[str, Any]] = {
    "Facebook": {
        "source_name": "Facebook",
        "query_label": "Facebook",
        "accepted_domains": ("facebook.com",),
    },
    "Instagram": {
        "source_name": "Instagram",
        "query_label": "Instagram",
        "accepted_domains": ("instagram.com",),
    },
    "LinkedIn": {
        "source_name": "LinkedIn",
        "query_label": "LinkedIn",
        "accepted_domains": ("linkedin.com",),
    },
    "X": {
        "source_name": "X / Twitter",
        "query_label": "X Twitter",
        "accepted_domains": ("x.com", "twitter.com"),
    },
}

# Collecte Facebook et LinkedIn pour ARMA et ses concurrents.
DEFAULT_ORGANIZATIONS_TO_RUN = ["ARMA", "OZONE", "Averda", "Suez Maroc", "SOS"]
DEFAULT_PLATFORMS_TO_RUN = ["Facebook", "Instagram", "LinkedIn", "X"]

ORGANIZATIONS_TO_RUN = [
    item.strip()
    for item in os.getenv(
        "SOCIAL_ORGANIZATIONS",
        ",".join(DEFAULT_ORGANIZATIONS_TO_RUN),
    ).split(",")
    if item.strip() in ORGANIZATION_SEARCH_NAMES
]

PLATFORMS_TO_RUN = [
    item.strip()
    for item in os.getenv(
        "SOCIAL_PLATFORMS",
        ",".join(DEFAULT_PLATFORMS_TO_RUN),
    ).split(",")
    if item.strip() in PLATFORMS
]

# Plusieurs requêtes précises valent mieux qu'une seule requête générale.
# Le volume reste configurable afin de maîtriser les crédits Serper.
MAX_RESULTS_PER_QUERY = int(os.getenv("SOCIAL_MAX_RESULTS_PER_QUERY", "5"))

ORGANIZATION_SEARCH_ALIASES: dict[str, tuple[str, ...]] = {
    "ARMA": ("ARMA Environnement", "ARMA Maroc", "ARMA"),
    "OZONE": ("OZONE Environnement", "Ozone Maroc", "OZONE"),
    "Averda": ("Averda Maroc", "Averda"),
    "Suez Maroc": ("Suez Maroc", "Suez Environnement"),
    "SOS": ("SOS NDD", "SOS Environnement"),
}

ARABIC_SEARCH_ALIASES: dict[str, tuple[str, ...]] = {
    "ARMA": ("أرما", "ارما", "شركة أرما"),
    "OZONE": ("أوزون", "اوزون"),
    "Averda": ("أفيردا", "افيردا"),
    "Suez Maroc": ("سويز", "سويز المغرب"),
    "SOS": (),
}

# Comptes officiels dont l'URL permet une identification fiable.
OFFICIAL_ACCOUNT_SLUGS: dict[str, dict[str, set[str]]] = {
    "ARMA": {
        "Facebook": {"armaenvironnement"},
        "Instagram": {"arma.environnement"},
        "X": set(),
        "LinkedIn": {"arma-environnement"},
    },
    "OZONE": {
        "Facebook": {"groupeozone"},
        "Instagram": set(),
        "X": set(),
        "LinkedIn": {"groupe-ozone"},
    },
    "Averda": {
        "Facebook": {"averda"},
        "Instagram": {"averda"},
        "X": set(),
        "LinkedIn": {"averda"},
    },
    "Suez Maroc": {
        "Facebook": set(),
        "Instagram": set(),
        "X": set(),
        "LinkedIn": set(),
    },
    "SOS": {
        "Facebook": set(),
        "Instagram": set(),
        "X": set(),
        "LinkedIn": set(),
    },
}

EMPLOYMENT_KEYWORDS = (
    "recrutement",
    "recrute",
    "offre d emploi",
    "offres d emploi",
    "opportunite chez",
    "opportunites chez",
    "hiring",
    "job",
    "jobs",
    "emploi",
    "وظيفة",
    "وظائف",
    "توظيف",
)

FRENCH_MONTHS = {
    "janvier": 1,
    "fevrier": 2,
    "février": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "août": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
    "décembre": 12,
}


# ============================================================
# Fonctions utilitaires
# ============================================================


def normalize_simple(value: Any) -> str:
    """Normalise légèrement un texte pour les règles simples."""

    text = clean_text(value).casefold()
    text = re.sub(r"[^\w\s@]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def detect_basic_language(value: str) -> str:
    """
    Première détection technique de l'écriture.

    - ar : présence significative de caractères arabes ;
    - fr : texte latin par défaut.

    La distinction arabe standard / darija sera faite dans le module NLP.
    """

    arabic_characters = len(
        re.findall(r"[\u0600-\u06FF]", value)
    )
    letters = len(re.findall(r"[^\W\d_]", value, flags=re.UNICODE))

    if letters and arabic_characters / letters >= 0.20:
        return "ar"

    return "fr"


def parse_serper_date(value: Any) -> datetime | None:
    """Convertit quelques formats de date courants retournés par Serper."""

    raw = clean_text(value)

    if not raw:
        return None

    now = datetime.now(timezone.utc)
    normalized = raw.casefold()

    relative_match = re.fullmatch(
        r"il y a\s+(\d+)\s+"
        r"(minute|minutes|heure|heures|jour|jours|semaine|semaines|mois|an|ans)",
        normalized,
    )

    if relative_match:
        amount = int(relative_match.group(1))
        unit = relative_match.group(2)

        if unit.startswith("minute"):
            return now - timedelta(minutes=amount)
        if unit.startswith("heure"):
            return now - timedelta(hours=amount)
        if unit.startswith("jour"):
            return now - timedelta(days=amount)
        if unit.startswith("semaine"):
            return now - timedelta(weeks=amount)
        if unit == "mois":
            return now - relativedelta(months=amount)
        if unit.startswith("an"):
            return now - relativedelta(years=amount)

    absolute_match = re.fullmatch(
        r"(\d{1,2})\s+([a-zéèêëàâäîïôöùûüç]+)\s+(\d{4})",
        normalized,
    )

    if absolute_match:
        day = int(absolute_match.group(1))
        month_name = absolute_match.group(2)
        year = int(absolute_match.group(3))
        month = FRENCH_MONTHS.get(month_name)

        if month:
            try:
                return datetime(
                    year,
                    month,
                    day,
                    tzinfo=timezone.utc,
                )
            except ValueError:
                return None

    iso_value = raw.replace("Z", "+00:00")

    try:
        parsed = datetime.fromisoformat(iso_value)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed


def get_url_parts(value: Any) -> tuple[str, list[str]]:
    """Retourne le domaine et les segments du chemin d'une URL."""

    url = clean_text(value)

    if not url:
        return "", []

    try:
        parsed = urlsplit(url)
    except ValueError:
        return "", []

    hostname = parsed.netloc.casefold()

    if hostname.startswith("www."):
        hostname = hostname[4:]

    segments = [
        unquote(segment).strip().casefold()
        for segment in parsed.path.split("/")
        if segment.strip()
    ]

    return hostname, segments


def canonicalize_social_url(value: Any) -> str:
    """Normalise une URL sociale et supprime les paramètres de suivi."""

    raw = clean_text(value)
    if not raw:
        return ""

    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw

    hostname = parsed.netloc.casefold()
    if hostname in {"m.facebook.com", "web.facebook.com"}:
        hostname = "www.facebook.com"

    query = ""
    query_values = parse_qs(parsed.query)

    # story.php/permalink.php ont besoin de story_fbid et id pour
    # identifier le post. Tous les paramètres de tracking sont retirés.
    if parsed.path.casefold().rstrip("/") in {"/story.php", "/permalink.php"}:
        kept: list[tuple[str, str]] = []
        for key in ("story_fbid", "fbid", "id"):
            for item in query_values.get(key, []):
                kept.append((key, item))
        query = urlencode(kept)

    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme or "https", hostname, path, query, ""))


def extract_facebook_post_id(value: Any) -> str | None:
    """Extrait story_fbid ou l'identifiant placé après /posts/."""

    raw = clean_text(value)
    if not raw:
        return None

    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None

    query_values = parse_qs(parsed.query)
    for key in ("story_fbid", "fbid"):
        values = query_values.get(key, [])
        if values and values[0].strip():
            return values[0].strip()

    segments = [
        unquote(segment).strip()
        for segment in parsed.path.split("/")
        if segment.strip()
    ]

    for marker in ("posts", "videos", "reel"):
        if marker in [segment.casefold() for segment in segments]:
            marker_index = [segment.casefold() for segment in segments].index(marker)
            candidates = segments[marker_index + 1 :]
            for candidate in reversed(candidates):
                if candidate.isdigit():
                    return candidate
            if candidates:
                return candidates[-1]

    return None


def create_social_external_id(
    result: dict[str, Any],
    platform_name: str,
) -> str:
    """Produit un identifiant stable même si plusieurs requêtes trouvent le post."""

    if platform_name == "Facebook":
        post_id = extract_facebook_post_id(result.get("link"))
        if post_id:
            return f"facebook_post:{post_id}"

    return create_external_id(result)


def create_social_content_hash(
    result: dict[str, Any],
    platform_name: str,
) -> str:
    """Empreinte propre au post social.

    Un titre Google générique comme « Le360 » ne doit jamais fusionner deux
    publications Facebook différentes. L'identifiant du post ou l'URL
    canonique est donc prioritaire.
    """

    external_id = create_social_external_id(result, platform_name)
    canonical_url = canonicalize_social_url(result.get("link"))
    stable_value = f"{platform_name.casefold()}|{external_id}|{canonical_url}"
    return hashlib.sha256(stable_value.encode("utf-8")).hexdigest()


def normalize_social_result(result: dict[str, Any]) -> dict[str, Any]:
    """Copie un résultat Serper en normalisant son lien."""

    normalized = dict(result)
    canonical_url = canonicalize_social_url(result.get("link"))
    if canonical_url:
        normalized["link"] = canonical_url
    return normalized


def result_matches_platform(
    result: dict[str, Any],
    accepted_domains: tuple[str, ...],
) -> bool:
    """Vérifie que l'URL appartient réellement à la plateforme."""

    hostname, _ = get_url_parts(result.get("link"))

    return bool(hostname) and any(
        hostname == domain
        or hostname.endswith(f".{domain}")
        for domain in accepted_domains
    )


def classify_social_object(
    platform_name: str,
    url: Any,
) -> str:
    """
    Retourne : post, profile, navigation, job ou unknown.
    Seules les URL de type post seront enregistrées.
    """

    _, segments = get_url_parts(url)

    if not segments:
        return "unknown"

    if platform_name == "Facebook":
        parsed = urlsplit(clean_text(url))
        query_values = parse_qs(parsed.query)

        # Les liens Facebook partagés par les utilisateurs utilisent
        # souvent story.php?story_fbid=... : il s'agit bien d'un post.
        if (
            segments[0] in {"story.php", "permalink.php"}
            and (query_values.get("story_fbid") or query_values.get("fbid"))
        ):
            return "post"

        if segments[0] in {"p", "profile.php"}:
            return "profile"

        if (
            len(segments) == 2
            and segments[1] in {"about", "photos", "reels", "videos"}
        ):
            return "navigation"

        if "posts" in segments:
            return "post"
        if "videos" in segments and len(segments) >= 3:
            return "post"
        if "photos" in segments and len(segments) >= 3:
            return "post"
        if "reel" in segments and len(segments) >= 2:
            return "post"

        return "profile"

    if platform_name == "Instagram":
        if segments[0] in {"p", "reel", "tv"} and len(segments) >= 2:
            return "post"
        if segments[0] in {"popular", "explore"}:
            return "navigation"
        if len(segments) >= 2 and segments[1] in {"reels", "tagged"}:
            return "navigation"
        return "profile"

    if platform_name == "LinkedIn":
        if segments[0] == "jobs":
            return "job"
        if segments[0] in {"posts", "pulse"}:
            return "post"
        if (
            len(segments) >= 2
            and segments[0] == "feed"
            and segments[1] == "update"
        ):
            return "post"
        if segments[0] in {"in", "company"}:
            return "profile"
        return "unknown"

    if platform_name == "X":
        if "status" in segments:
            return "post"
        return "profile"

    return "unknown"


def detect_content_purpose(result: dict[str, Any]) -> str:
    """Distingue les publications générales des contenus de recrutement."""

    text = normalize_simple(
        " ".join(
            str(value)
            for value in (
                result.get("title"),
                result.get("snippet"),
            )
            if value
        )
    )

    for keyword in EMPLOYMENT_KEYWORDS:
        if normalize_simple(keyword) in text:
            return "employment"

    return "general"


def detect_content_origin(
    platform_name: str,
    organization_name: str,
    result: dict[str, Any],
) -> tuple[str, str | None]:
    """
    Retourne owned, earned ou unknown.

    Pour Instagram, l'URL /p/CODE ou /reel/CODE ne contient
    généralement pas l'auteur. Sans indice explicite dans le titre,
    l'origine reste unknown.

    Pour LinkedIn, une URL /posts/auteur_contenu contient le compte
    auteur dans le deuxième segment de l'URL.
    """

    _, segments = get_url_parts(result.get("link"))

    if not segments:
        return "unknown", None

    official_slugs = OFFICIAL_ACCOUNT_SLUGS.get(
        organization_name,
        {},
    ).get(
        platform_name,
        set(),
    )

    if platform_name == "Instagram":
        title = clean_text(result.get("title"))
        author_match = re.match(
            r"^\s*(.+?)\s+on\s+instagram\s*:",
            title,
            flags=re.IGNORECASE,
        )

        if author_match:
            author_hint = author_match.group(1).strip()
            normalized_author = author_hint.casefold().lstrip("@")

            if normalized_author in official_slugs:
                return "owned", author_hint

            return "earned", author_hint

        return "unknown", None

    if platform_name == "LinkedIn":
        if segments[0] == "posts" and len(segments) >= 2:
            account_slug = segments[1].split("_", 1)[0]

            if account_slug in official_slugs:
                return "owned", account_slug

            return "earned", account_slug

        # Les URL /feed/update/... n'exposent pas toujours l'auteur.
        if (
            len(segments) >= 2
            and segments[0] == "feed"
            and segments[1] == "update"
        ):
            return "unknown", None

        return "unknown", None

    account_slug = segments[0]

    if account_slug in official_slugs:
        return "owned", account_slug

    return "earned", account_slug


def build_social_queries(
    organization_name: str,
    platform_name: str,
) -> list[str]:
    """Construit plusieurs requêtes de veille, pas seulement le compte officiel."""

    aliases = ORGANIZATION_SEARCH_ALIASES[organization_name]
    exact_name = aliases[0]
    short_name = aliases[-1]
    domains = PLATFORMS[platform_name]["accepted_domains"]

    queries: list[str] = []
    for domain in domains:
        # Les requêtes exigent le nom ET un contexte métier : cela évite
        # les profils de salariés, recrutements et homonymes sans intérêt.
        queries.extend([
            f'site:{domain} "{exact_name}" '
            '("propreté" OR "déchets" OR "collecte" OR "nettoyage" OR "assainissement")',
            f'site:{domain} "{short_name}" '
            '("appel d\'offres" OR "marché" OR "contrat" OR "grève" OR "réclamation") '
            '("déchets" OR "propreté" OR "nettoyage" OR "assainissement")',
            f'site:{domain} "{short_name}" '
            '("Casablanca" OR "Rabat" OR "Maroc" OR "Nouakchott") '
            '("déchets" OR "propreté" OR "collecte")',
        ])

    arabic_aliases = ARABIC_SEARCH_ALIASES.get(organization_name, ())
    if arabic_aliases:
        aliases_expression = " OR ".join(
            f'"{alias}"' for alias in arabic_aliases
        )
        for domain in domains:
            queries.append(
                f'site:{domain} ({aliases_expression}) '
                '("النظافة" OR "النفايات" OR "جمع النفايات" OR "تدبير النفايات")'
            )

    # Supprime les doublons tout en conservant l'ordre.
    return list(dict.fromkeys(queries))


# ============================================================
# Accès PostgreSQL
# ============================================================


def get_target_organizations(
    session: Session,
) -> dict[str, Organization]:
    """Charge uniquement les organisations configurées pour cette exécution."""

    statement = select(Organization).where(
        Organization.name.in_(ORGANIZATIONS_TO_RUN),
        Organization.is_active.is_(True),
    )

    organizations = {
        organization.name: organization
        for organization in session.scalars(statement).all()
    }

    missing = [
        name
        for name in ORGANIZATIONS_TO_RUN
        if name not in organizations
    ]

    if missing:
        raise RuntimeError(
            "Organisations absentes de PostgreSQL : "
            + ", ".join(missing)
        )

    return organizations


def get_all_organizations(
    session: Session,
) -> dict[str, Organization]:
    """Charge toutes les organisations utiles pour créer les relations."""

    names = list(ORGANIZATION_SEARCH_NAMES)
    statement = select(Organization).where(
        Organization.name.in_(names),
        Organization.is_active.is_(True),
    )

    return {
        organization.name: organization
        for organization in session.scalars(statement).all()
    }


def get_platform_source(
    session: Session,
    source_name: str,
) -> Source:
    """Récupère la source Facebook, Instagram, LinkedIn ou X."""

    source = session.scalar(
        select(Source).where(
            Source.name == source_name,
            Source.is_active.is_(True),
        )
    )

    if source is None:
        raise RuntimeError(
            f"La source sociale '{source_name}' est absente de PostgreSQL."
        )

    return source


def get_or_create_watch_query(
    session: Session,
    organization: Organization,
    platform_name: str,
    query_text: str,
) -> WatchQuery:
    """Récupère ou crée la requête de veille sociale."""

    watch_query = session.scalar(
        select(WatchQuery).where(
            WatchQuery.organization_id == organization.id,
            WatchQuery.query_text == query_text,
        )
    )

    if watch_query is not None:
        return watch_query

    watch_query = WatchQuery(
        organization_id=organization.id,
        query_text=query_text,
        language="fr",
        category="social_post",
        frequency="daily",
        filters={
            "country": "ma",
            "platform": platform_name,
            "content_type": "social_post",
        },
        is_active=True,
    )

    session.add(watch_query)
    session.flush()
    return watch_query


def find_existing_mention(
    session: Session,
    source_id: int,
    external_id: str,
    content_hash: str,
) -> Mention | None:
    """Recherche un doublon déjà présent dans la base."""

    return session.scalar(
        select(Mention)
        .where(
            or_(
                Mention.content_hash == content_hash,
                (
                    (Mention.source_id == source_id)
                    & (Mention.external_id == external_id)
                ),
            )
        )
        .limit(1)
    )


def ensure_organization_links(
    session: Session,
    mention: Mention,
    detected_names: list[str],
    organizations: dict[str, Organization],
    primary_name: str,
    include_in_reputation: bool,
    detection_method: str = "social_text_matching",
    relevance_score: float = 1.0,
) -> int:
    """
    Crée uniquement les relations MentionOrganization manquantes.

    La vérification utilise à la fois les relations déjà présentes
    dans PostgreSQL et celles ajoutées pendant la transaction actuelle.
    """

    existing_relations = {
        relation.organization_id: relation
        for relation in session.scalars(
            select(MentionOrganization).where(
                MentionOrganization.mention_id == mention.id
            )
        ).all()
    }

    created = 0
    has_primary = any(relation.is_primary for relation in existing_relations.values())

    for name in detected_names:
        organization = organizations.get(name)

        if organization is None:
            continue

        existing_relation = existing_relations.get(organization.id)
        if existing_relation is not None:
            existing_relation.include_in_reputation = include_in_reputation
            if name == primary_name and not has_primary:
                existing_relation.is_primary = True
                has_primary = True
            continue

        relation_is_primary = name == primary_name and not has_primary
        relation = MentionOrganization(
            mention_id=mention.id,
            organization_id=organization.id,
            relevance_score=relevance_score,
            is_primary=relation_is_primary,
            detection_method=detection_method,
            include_in_reputation=include_in_reputation,
        )

        session.add(relation)
        if relation_is_primary:
            has_primary = True

        # Empêche la création de la même relation une deuxième fois
        # pendant cette transaction.
        existing_relations[organization.id] = relation

        created += 1

    # Envoie immédiatement les nouvelles relations à PostgreSQL.
    # Ainsi, un deuxième résultat identique les verra comme existantes.
    if created > 0:
        session.flush()

    return created


# ============================================================
# Classification et collecte
# ============================================================


def classify_social_result(
    result: dict[str, Any],
    platform_name: str,
    queried_organization: str,
) -> dict[str, Any]:
    """Décide si un résultat social doit être conservé."""

    platform = PLATFORMS[platform_name]

    if not result_matches_platform(
        result=result,
        accepted_domains=platform["accepted_domains"],
    ):
        return {
            "keep": False,
            "reason": "wrong_platform_domain",
        }

    object_type = classify_social_object(
        platform_name=platform_name,
        url=result.get("link"),
    )

    if object_type != "post":
        return {
            "keep": False,
            "reason": f"social_object_{object_type}",
            "social_object_type": object_type,
        }

    classification = classify_article(result)
    detected_names = list(classification["organizations"])

    # ARMA, OZONE et SOS sont des termes ambigus. Sans contexte explicite
    # déchets/propreté/assainissement, le résultat est rejeté afin de ne pas
    # fausser la réputation avec une autre société ou un sens commun.
    if (
        queried_organization in {"ARMA", "OZONE", "SOS"}
        and queried_organization in detected_names
        and not classification["sector_topics"]
    ):
        return {
            "keep": False,
            "reason": "ambiguous_organization_without_sector_context",
            "social_object_type": object_type,
            **classification,
        }

    if queried_organization not in detected_names:
        return {
            "keep": False,
            "reason": "queried_organization_not_detected",
            "social_object_type": object_type,
            **classification,
        }

    content_origin, author_hint = detect_content_origin(
        platform_name=platform_name,
        organization_name=queried_organization,
        result=result,
    )
    content_purpose = detect_content_purpose(result)

    business_decision = evaluate_business_relevance(
        result,
        organizations=detected_names,
        sector_topics=classification["sector_topics"],
        content_origin=content_origin,
        content_purpose=content_purpose,
        source_name=platform_name,
        query_category="competitor",
    )

    # Une simple citation du nom de l'entreprise ne suffit pas pour le score
    # de réputation. Il faut un contexte métier et aucun indicateur de bruit
    # (profil salarié, recrutement, vœux, post générique, etc.).
    include_in_reputation = (
        content_origin == "earned"
        and content_purpose == "general"
        and (
            bool(classification["sector_topics"])
            or business_decision.score >= 0.55
        )
        and "noise_or_hr_content" not in business_decision.quality_flags
    )

    return {
        "keep": True,
        "reason": "valid_social_post",
        "social_object_type": object_type,
        "content_origin": content_origin,
        "author_hint": author_hint,
        "content_purpose": content_purpose,
        "include_in_reputation": include_in_reputation,
        "business_relevance": business_decision.to_dict(),
        **classification,
    }


def create_social_mention(
    result: dict[str, Any],
    source: Source,
    pipeline_run: PipelineRun,
    decision: dict[str, Any],
    platform_name: str,
    queried_organization: Organization,
    query_text: str,
) -> Mention | None:
    """Transforme un résultat validé en Mention."""

    title = clean_text(result.get("title"))
    snippet = clean_text(result.get("snippet"))
    raw_text = snippet or title

    if not raw_text:
        return None

    payload = dict(result)
    payload["_collection"] = {
        "channel": "social",
        "content_type": "social_post",
        "aggregator": "Serper",
        "platform": platform_name,
        "search_query": query_text,
        "queried_organization_id": queried_organization.id,
        "queried_organization_name": queried_organization.name,
        "detected_organizations": decision["organizations"],
        "content_scope": decision["content_scope"],
        "sector_topics": decision["sector_topics"],
        "social_object_type": decision["social_object_type"],
        "content_origin": decision["content_origin"],
        "author_hint": decision["author_hint"],
        "content_purpose": decision["content_purpose"],
        "include_in_reputation": decision["include_in_reputation"],
    }

    normalized_result = normalize_social_result(result)

    return Mention(
        source_id=source.id,
        content_type="social_post",
        business_category=decision["business_relevance"]["category"],
        business_relevance_score=decision["business_relevance"]["score"],
        business_summary=decision["business_relevance"]["summary"] or None,
        display_in_marketing=decision["business_relevance"]["display_in_marketing"],
        quality_flags=decision["business_relevance"]["quality_flags"],
        parent_mention_id=None,
        pipeline_run_id=pipeline_run.id,
        external_id=create_social_external_id(
            normalized_result,
            platform_name,
        ),
        url=clean_text(normalized_result.get("link")) or None,
        title=title[:1000] if title else None,
        raw_text=raw_text,
        clean_text=None,
        author_name=(decision["author_hint"] or None),
        author_handle=None,
        published_at=parse_serper_date(result.get("date")),
        collected_at=utc_now(),
        detected_language=detect_basic_language(raw_text),
        country="MA",
        city=None,
        content_hash=create_social_content_hash(normalized_result, platform_name),
        engagement={},
        raw_payload=payload,
        processing_status="new",
    )


def collect_one_query(
    organization_id: int,
    platform_name: str,
    client: SerperClient,
    query_text: str,
) -> dict[str, Any]:
    """Collecte les publications d'une organisation sur une plateforme."""

    session = SessionLocal()
    pipeline_run_id: int | None = None

    try:
        organization = session.get(Organization, organization_id)

        if organization is None:
            raise RuntimeError(
                f"Organisation introuvable : {organization_id}"
            )

        platform = PLATFORMS[platform_name]
        serper_source = get_serper_source(session)
        platform_source = get_platform_source(
            session=session,
            source_name=platform["source_name"],
        )
        all_organizations = get_all_organizations(session)

        watch_query = get_or_create_watch_query(
            session=session,
            organization=organization,
            platform_name=platform_name,
            query_text=query_text,
        )

        pipeline_run = create_pipeline_run(
            session=session,
            source=serper_source,
            watch_query=watch_query,
            run_type="serper_social_post_collection_v2",
            requested_results=MAX_RESULTS_PER_QUERY,
        )
        pipeline_run_id = pipeline_run.id

        print("\n" + "=" * 78)
        print(f"Organisation : {organization.name}")
        print(f"Plateforme   : {platform_name}")
        print(f"Requête      : {query_text}")
        print(f"Pipeline     : {pipeline_run_id}")

        results = client.search_web(
            query=query_text,
            language="fr",
            country="ma",
            num=MAX_RESULTS_PER_QUERY,
        )[:MAX_RESULTS_PER_QUERY]

        counters = {
            "received": len(results),
            "created": 0,
            "duplicates": 0,
            "repaired_links": 0,
            "ignored": 0,
            "owned": 0,
            "earned": 0,
            "unknown": 0,
            "reputation_eligible": 0,
        }
        ignored_reasons: dict[str, int] = {}

        for result in results:
            if not isinstance(result, dict):
                counters["ignored"] += 1
                ignored_reasons["invalid_result"] = (
                    ignored_reasons.get("invalid_result", 0) + 1
                )
                continue

            result = normalize_social_result(result)

            decision = classify_social_result(
                result=result,
                platform_name=platform_name,
                queried_organization=organization.name,
            )
            title = clean_text(result.get("title")) or "Sans titre"

            if not decision.get("keep"):
                reason = str(decision.get("reason", "unknown_reason"))
                counters["ignored"] += 1
                ignored_reasons[reason] = ignored_reasons.get(reason, 0) + 1
                print(f"IGNORÉ [{reason}] : {title}")
                continue

            origin = decision["content_origin"]
            counters[origin] += 1

            if decision["include_in_reputation"]:
                counters["reputation_eligible"] += 1

            external_id = create_social_external_id(result, platform_name)
            content_hash = create_social_content_hash(result, platform_name)
            existing_mention = find_existing_mention(
                session=session,
                source_id=platform_source.id,
                external_id=external_id,
                content_hash=content_hash,
            )

            if existing_mention is not None:
                existing_mention.content_type = "social_post"
                business = decision["business_relevance"]
                existing_mention.business_category = business["category"]
                existing_mention.business_relevance_score = business["score"]
                existing_mention.business_summary = business["summary"] or None
                existing_mention.display_in_marketing = business["display_in_marketing"]
                existing_mention.quality_flags = business["quality_flags"]
                existing_mention.url = clean_text(result.get("link")) or existing_mention.url

                links_created = ensure_organization_links(
                    session=session,
                    mention=existing_mention,
                    detected_names=decision["organizations"],
                    organizations=all_organizations,
                    primary_name=organization.name,
                    include_in_reputation=decision["include_in_reputation"],
                )

                payload = dict(existing_mention.raw_payload or {})
                collection_metadata = dict(payload.get("_collection") or {})
                collection_metadata.update(
                    {
                        "content_type": "social_post",
                        "social_object_type": decision["social_object_type"],
                        "content_origin": decision["content_origin"],
                        "author_hint": decision["author_hint"],
                        "content_purpose": decision["content_purpose"],
                        "include_in_reputation": decision[
                            "include_in_reputation"
                        ],
                        "detected_organizations": decision["organizations"],
                        "business_relevance": decision["business_relevance"],
                    }
                )
                payload["_collection"] = collection_metadata
                existing_mention.raw_payload = payload

                if decision["author_hint"]:
                    existing_mention.author_name = decision["author_hint"]

                counters["duplicates"] += 1
                counters["repaired_links"] += links_created
                print(
                    f"DOUBLON RÉPARÉ ({links_created} lien(s)) : {title}"
                )
                continue

            mention = create_social_mention(
                result=result,
                source=platform_source,
                pipeline_run=pipeline_run,
                decision=decision,
                platform_name=platform_name,
                queried_organization=organization,
                query_text=query_text,
            )

            if mention is None:
                counters["ignored"] += 1
                ignored_reasons["empty_text"] = (
                    ignored_reasons.get("empty_text", 0) + 1
                )
                continue

            session.add(mention)
            session.flush()

            ensure_organization_links(
                session=session,
                mention=mention,
                detected_names=decision["organizations"],
                organizations=all_organizations,
                primary_name=organization.name,
                include_in_reputation=decision["include_in_reputation"],
            )

            counters["created"] += 1
            print(
                f"AJOUTÉ [{origin}] "
                f"réputation={decision['include_in_reputation']} : {title}"
            )

        current_pipeline = session.get(PipelineRun, pipeline_run_id)

        if current_pipeline is None:
            raise RuntimeError("Pipeline social introuvable après collecte.")

        current_pipeline.status = "completed"
        current_pipeline.finished_at = utc_now()
        current_pipeline.items_received = counters["received"]
        current_pipeline.items_created = counters["created"]
        current_pipeline.items_duplicated = counters["duplicates"]
        current_pipeline.error_message = None
        current_pipeline.statistics = {
            "version": 2,
            "organization_id": organization.id,
            "organization_name": organization.name,
            "platform": platform_name,
            "query": query_text,
            "content_type": "social_post",
            "received": counters["received"],
            "created": counters["created"],
            "duplicates": counters["duplicates"],
            "repaired_links": counters["repaired_links"],
            "ignored": counters["ignored"],
            "ignored_reasons": ignored_reasons,
            "owned": counters["owned"],
            "earned": counters["earned"],
            "unknown_origin": counters["unknown"],
            "reputation_eligible": counters["reputation_eligible"],
            "comments_collected": 0,
        }

        session.commit()

        # Synchronise automatiquement les liens apres une collecte Facebook.
        if platform_name == "facebook":
            from backend.services.facebook_retained_links_service import (
                export_retained_facebook_links,
            )

            export_retained_facebook_links(session)

        print(
            "Fin : "
            f"{counters['created']} ajout(s), "
            f"{counters['duplicates']} doublon(s), "
            f"{counters['repaired_links']} lien(s) réparé(s), "
            f"{counters['ignored']} ignoré(s)."
        )

        return {
            "status": "completed",
            "organization": organization.name,
            "platform": platform_name,
            **counters,
        }

    except Exception as error:
        if pipeline_run_id is not None:
            mark_pipeline_as_failed(
                session=session,
                pipeline_run_id=pipeline_run_id,
                error=error,
            )
        else:
            session.rollback()

        print(f"Erreur collecte sociale V2 : {error}")

        return {
            "status": "failed",
            "organization_id": organization_id,
            "platform": platform_name,
            "error": str(error),
        }

    finally:
        session.close()


def collect_social_posts_v2() -> None:
    """Point d'entrée de la collecte sociale V2."""

    session = SessionLocal()

    try:
        organizations = get_target_organizations(session)
        organization_ids = {
            name: organization.id
            for name, organization in organizations.items()
        }
    finally:
        session.close()

    client = SerperClient()
    summaries: list[dict[str, Any]] = []

    print("DÉBUT DE LA COLLECTE SOCIALE V2")
    print("=" * 78)
    print("Commentaires : collectés ensuite via Meta Graph API si configuré")
    print("Organisations : " + ", ".join(ORGANIZATIONS_TO_RUN))
    print("Plateformes   : " + ", ".join(PLATFORMS_TO_RUN))

    for organization_name in ORGANIZATIONS_TO_RUN:
        organization_id = organization_ids[organization_name]

        for platform_name in PLATFORMS_TO_RUN:
            query_texts = build_social_queries(
                organization_name=organization_name,
                platform_name=platform_name,
            )

            for query_text in query_texts:
                summaries.append(
                    collect_one_query(
                        organization_id=organization_id,
                        platform_name=platform_name,
                        client=client,
                        query_text=query_text,
                    )
                )

    completed = [
        summary
        for summary in summaries
        if summary.get("status") == "completed"
    ]
    failed = [
        summary
        for summary in summaries
        if summary.get("status") == "failed"
    ]

    print("\n" + "=" * 78)
    print("RÉSUMÉ GLOBAL V2")
    print(f"Recherches terminées : {len(completed)}")
    print(f"Recherches en erreur : {len(failed)}")
    print(
        "Contenus ajoutés     : "
        f"{sum(int(item.get('created', 0)) for item in completed)}"
    )
    print(
        "Doublons trouvés     : "
        f"{sum(int(item.get('duplicates', 0)) for item in completed)}"
    )
    print(
        "Liens réparés        : "
        f"{sum(int(item.get('repaired_links', 0)) for item in completed)}"
    )
    print(
        "Résultats ignorés    : "
        f"{sum(int(item.get('ignored', 0)) for item in completed)}"
    )


if __name__ == "__main__":
    collect_social_posts_v2()
