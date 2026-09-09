from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "data" / "fb.txt"
REGISTRY_JSON_PATH = PROJECT_ROOT / "data" / "fb_registry.json"
LEGACY_REGISTRY_PATH = PROJECT_ROOT / "data" / "facebook_retained_links.txt"

ALLOWED_HOSTS = {
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "mobile.facebook.com",
    "web.facebook.com",
    "l.facebook.com",
    "lm.facebook.com",
    "fb.watch",
}
ESSENTIAL_QUERY_KEYS = {"story_fbid", "id", "fbid", "v"}
FORBIDDEN_MARKERS = (
    "access_token=",
    "cookie=",
    "session=",
    "password=",
    "token=",
)
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def _unwrap_facebook_redirect(value: str) -> str:
    """Déplie les liens ``l.facebook.com/l.php?u=...`` sans suivre le réseau."""

    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower()
    if host not in {"l.facebook.com", "lm.facebook.com"}:
        return value.strip()
    target = (parse_qs(parsed.query).get("u") or [""])[-1]
    return unquote(target).strip() or value.strip()


def is_facebook_publication_url(value: str | None) -> bool:
    """Valide les principaux formats d'URL d'une publication Facebook publique."""

    if not value:
        return False
    value = _unwrap_facebook_redirect(value)
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    query = parse_qs(parsed.query)
    if parsed.scheme not in {"http", "https"} or host not in ALLOWED_HOSTS:
        return False
    lowered = value.casefold()
    if any(marker in lowered for marker in FORBIDDEN_MARKERS):
        return False
    if host == "fb.watch":
        return bool(path.strip("/"))
    if any(marker in path for marker in ("/posts/", "/reel/", "/videos/", "/share/", "/permalink/")):
        return True
    if path.rstrip("/").endswith(("/story.php", "/permalink.php")):
        return "story_fbid" in query
    if path.rstrip("/").endswith("/photo.php") or path.rstrip("/") in {"/photo", "/photos"}:
        return "fbid" in query
    if path.rstrip("/") == "/watch":
        return "v" in query
    return False


def is_public_facebook_url(value: str | None) -> bool:
    return is_facebook_publication_url(value)


def canonicalize_facebook_url(value: str) -> str:
    """Nettoie une URL Facebook sans supprimer ses identifiants indispensables."""

    value = _unwrap_facebook_redirect(value)
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower()
    if host in {
        "facebook.com",
        "m.facebook.com",
        "mobile.facebook.com",
        "web.facebook.com",
    }:
        host = "www.facebook.com"
    query = parse_qs(parsed.query, keep_blank_values=False)
    clean_query = {
        key: values[-1]
        for key, values in query.items()
        if key in ESSENTIAL_QUERY_KEYS and values
    }
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(("https", host, path, "", urlencode(clean_query), ""))


def _string_candidates(value: str) -> Iterable[str]:
    value = value.strip()
    if value.startswith(("http://", "https://")):
        yield value
    for match in URL_PATTERN.findall(value):
        yield match.rstrip(".,);]}")



def extract_facebook_post_identifiers(value: str | None) -> set[str]:
    """Extrait des identifiants stables d'une publication Facebook.

    Facebook et Apify peuvent représenter le même post avec des URLs différentes
    (slug, permalink.php, story_fbid ou URL canonique). Les identifiants extraits
    permettent de rattacher les commentaires au bon post même si l'URL diffère.
    """

    if not value:
        return set()
    value = _unwrap_facebook_redirect(value)
    parsed = urlparse(value.strip())
    query = parse_qs(parsed.query)
    identifiers: set[str] = set()
    for key in ("story_fbid", "fbid", "v", "id"):
        for candidate in query.get(key, []):
            candidate = str(candidate).strip()
            if candidate:
                identifiers.add(candidate)
    parts = [part for part in parsed.path.split("/") if part]
    for index, part in enumerate(parts):
        if part.casefold() in {"posts", "reel", "videos", "permalink"} and index + 1 < len(parts):
            identifiers.add(parts[index + 1])
    for candidate in re.findall(r"(?<!\d)\d{8,}(?!\d)", value):
        identifiers.add(candidate)
    return identifiers

def iter_facebook_publication_urls(payload: Any) -> Iterable[str]:
    """Recherche récursivement des permaliens Facebook dans un payload Serper/API.

    Les collecteurs ne rangent pas tous l'URL au même endroit. Cette fonction
    couvre ``mention.url``, les champs ``link``/``url`` des payloads Serper et
    les URLs enveloppées par ``l.facebook.com``.
    """

    if payload is None:
        return
    if isinstance(payload, str):
        for candidate in _string_candidates(payload):
            candidate = _unwrap_facebook_redirect(candidate)
            if is_facebook_publication_url(candidate):
                yield canonicalize_facebook_url(candidate)
        return
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            # Les champs d'URL sont parcourus en premier, mais tous les champs
            # restent inspectés car Serper peut les imbriquer dans raw_payload.
            if isinstance(key, str) and key.casefold() in {
                "url", "link", "source_url", "original_url", "facebook_url",
                "facebookurl", "posturl", "post_url", "inputurl", "input_url",
            }:
                yield from iter_facebook_publication_urls(value)
            else:
                yield from iter_facebook_publication_urls(value)
        return
    if isinstance(payload, Iterable) and not isinstance(payload, (bytes, bytearray)):
        for item in payload:
            yield from iter_facebook_publication_urls(item)


def extract_facebook_publication_urls(*values: Any) -> list[str]:
    """Retourne les permaliens Facebook uniques trouvés dans plusieurs valeurs."""

    urls: list[str] = []
    for value in values:
        for url in iter_facebook_publication_urls(value):
            if url not in urls:
                urls.append(url)
    return urls
