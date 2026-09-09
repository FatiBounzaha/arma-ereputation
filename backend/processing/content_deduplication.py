from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

LOCAL_MARKERS = (
    "maroc", "marocain", "casablanca", "rabat", "tanger", "kénitra", "kenitra",
    "el jadida", "marrakech", "agadir", "fès", "fes", "meknès", "meknes",
    "tetouan", "tétouan", "collectivités marocaines", "commune de",
)

STOPWORDS = {
    "a", "au", "aux", "avec", "ce", "ces", "cette", "dans", "de", "des",
    "du", "en", "et", "est", "la", "le", "les", "leur", "leurs", "pour",
    "sur", "un", "une", "plus", "apres", "avant", "par", "vers", "entre",
    "the", "and", "of", "to", "in", "for", "on", "with", "from",
    "في", "من", "على", "إلى", "عن", "مع", "هذا", "هذه", "التي", "الذي",
    "و", "أو", "ثم", "بعد", "قبل", "شركة", "مدينة",
}

SOURCE_NOISE = {
    "instagram", "facebook", "linkedin", "twitter", "telquelofficiel", "le360fr",
    "source", "actualité", "news", "officiel", "official",
}


def normalize_title(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"https?://\S+", " ", text.lower())
    text = re.sub(r"[^a-z0-9\u0600-\u06ff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def significant_tokens(value: str | None) -> set[str]:
    tokens = set(normalize_title(value).split())
    return {
        token
        for token in tokens
        if len(token) >= 3 and token not in STOPWORDS and token not in SOURCE_NOISE
    }


def title_similarity(left: str | None, right: str | None) -> float:
    a, b = normalize_title(left), normalize_title(right)
    if not a or not b:
        return 0.0
    seq = SequenceMatcher(None, a, b).ratio()
    ta, tb = significant_tokens(a), significant_tokens(b)
    jaccard = len(ta & tb) / max(1, len(ta | tb))
    containment = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return max(seq, jaccard, containment * 0.92)


def event_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_title = left.get("title") or ""
    right_title = right.get("title") or ""
    title_score = title_similarity(left_title, right_title)

    left_context = " ".join(
        str(left.get(key) or "") for key in ("title", "summary", "category")
    )
    right_context = " ".join(
        str(right.get(key) or "") for key in ("title", "summary", "category")
    )
    lt, rt = significant_tokens(left_context), significant_tokens(right_context)
    context_jaccard = len(lt & rt) / max(1, len(lt | rt))
    containment = len(lt & rt) / max(1, min(len(lt), len(rt)))

    # Les titres tronqués des réseaux sociaux sont souvent peu similaires en
    # chaîne mais partagent les mots-clés de l'événement avec l'article source.
    return max(title_score, context_jaccard, containment * 0.9)


def local_priority(item: dict[str, Any]) -> int:
    text = normalize_title(
        " ".join(str(item.get(key) or "") for key in ("title", "summary", "source_name"))
    )
    return 1 if any(normalize_title(marker) in text for marker in LOCAL_MARKERS) else 0


def _source_descriptor(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item.get("source_name"),
        "url": item.get("url"),
        "published_at": item.get("published_at"),
    }


def rank_and_deduplicate(
    items: list[dict[str, Any]],
    limit: int,
    similarity_threshold: float = 0.64,
) -> list[dict[str, Any]]:
    """Priorise le Maroc et regroupe les sources d'un même événement.

    Le regroupement est effectué à l'affichage : les mentions brutes restent
    traçables dans PostgreSQL. La carte principale conserve la source la plus
    pertinente et expose ``related_sources`` pour l'audit.
    """

    ranked = sorted(
        items,
        key=lambda item: (
            local_priority(item),
            float(item.get("relevance_score") or 0.0),
            str(item.get("published_at") or ""),
        ),
        reverse=True,
    )

    kept: list[dict[str, Any]] = []
    for raw_item in ranked:
        item = dict(raw_item)
        item.setdefault("related_sources", [_source_descriptor(item)])
        item.setdefault("duplicate_count", 1)

        duplicate_target: dict[str, Any] | None = None
        for existing in kept:
            same_category = (
                not item.get("category")
                or not existing.get("category")
                or item.get("category") == existing.get("category")
            )
            if same_category and event_similarity(item, existing) >= similarity_threshold:
                duplicate_target = existing
                break

        if duplicate_target is not None:
            descriptors = duplicate_target.setdefault("related_sources", [])
            descriptor = _source_descriptor(item)
            if descriptor not in descriptors:
                descriptors.append(descriptor)
            duplicate_target["duplicate_count"] = int(
                duplicate_target.get("duplicate_count") or 1
            ) + 1
            continue

        kept.append(item)
        if len(kept) >= limit:
            # Continuer à parcourir uniquement pour regrouper des doublons des
            # cartes déjà retenues, sans ajouter de nouvelles cartes.
            continue

    return kept[:limit]
