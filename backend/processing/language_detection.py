from __future__ import annotations

import re

from sqlalchemy import select

from backend.database.connection import SessionLocal
from backend.database.models import Mention

ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
LATIN_RE = re.compile(r"[A-Za-zÀ-ÿ]")

DARIJA_ARABIC_MARKERS = {
    "واش", "بزاف", "ديال", "مزيان", "ماشي", "حيت", "علاش", "دابا",
    "هاد", "هادشي", "كاين", "خاص", "بغيت", "شنو", "فين", "راه",
}
DARIJA_LATIN_MARKERS = {
    "wach", "bzaf", "dial", "dyal", "mzyan", "machi", "7it", "3lach",
    "daba", "hadchi", "kayn", "khass", "bghit", "chno", "fin", "rah",
}
FRENCH_MARKERS = {
    "le", "la", "les", "des", "une", "un", "dans", "pour", "avec",
    "service", "déchets", "propreté", "collecte", "ville", "quartier",
}
ENGLISH_MARKERS = {"the", "and", "with", "for", "waste", "city", "service", "cleaning"}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[\wÀ-ÿ\u0600-\u06FF']+", text.lower()))


def detect_language(text: str | None) -> str:
    """Détecte fr/ar/darija/en avec une heuristique traçable.

    Ce module normalise la langue avant le sentiment. Il ne remplace pas un
    modèle linguistique : les contenus mixtes restent signalés comme ``mixed``.
    """
    value = (text or "").strip()
    if not value:
        return "unknown"

    tokens = _tokens(value)
    has_arabic = bool(ARABIC_RE.search(value))
    has_latin = bool(LATIN_RE.search(value))

    if tokens & DARIJA_ARABIC_MARKERS or tokens & DARIJA_LATIN_MARKERS:
        return "darija"
    if has_arabic and has_latin:
        return "mixed"
    if has_arabic:
        return "ar"

    french_score = len(tokens & FRENCH_MARKERS)
    english_score = len(tokens & ENGLISH_MARKERS)
    if english_score > french_score and english_score >= 2:
        return "en"
    return "fr"


def detect_pending_languages(force: bool = False, limit: int | None = None) -> None:
    """Renseigne ``mentions.detected_language`` pour les lignes à traiter."""
    session = SessionLocal()
    try:
        statement = select(Mention).order_by(Mention.id)
        if not force:
            statement = statement.where(
                (Mention.detected_language.is_(None))
                | (Mention.detected_language == "")
                | (Mention.detected_language == "unknown")
            )
        if limit is not None:
            statement = statement.limit(limit)

        mentions = list(session.scalars(statement))
        if not mentions:
            print("Aucune langue à détecter.")
            return

        counts: dict[str, int] = {}
        for mention in mentions:
            language = detect_language(mention.clean_text or mention.raw_text)
            mention.detected_language = language
            counts[language] = counts.get(language, 0) + 1

        session.commit()
        print(f"Langues détectées : {len(mentions)} mention(s) -> {counts}")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    detect_pending_languages()
