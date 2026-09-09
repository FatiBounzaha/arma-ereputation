"""Détection de la ville concernée par une alerte.

ARMA opère par contrat de gestion déléguée, ville par ville. Une alerte n'a donc
de valeur opérationnelle que rapportée à un territoire : « 12 alertes négatives »
ne veut rien dire, « 9 alertes négatives à Casablanca » déclenche une action.

Le nom de la ville n'est stocké dans aucune colonne : il apparaît en clair dans
le texte du commentaire, dans le titre de la publication, ou dans l'URL de la
source. Ce module le cherche dans ces trois endroits et indique lequel a
répondu, pour que l'utilisateur puisse vérifier.

Ordre de recherche, du plus spécifique au moins spécifique :

1. **le texte de l'alerte** — un commentaire qui cite une ville parle de cette
   ville, même s'il est publié sous un article consacré à une autre ;
2. **le titre** de la publication ou de la publication parente ;
3. **l'URL**, où la ville apparaît souvent en slug (`.../el-jadida/...`).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

# Chaque entrée : nom affiché -> variantes reconnues (français, arabe, slugs).
# Les variantes sont comparées sur du texte normalisé (minuscules, sans accents,
# ponctuation réduite à des espaces), sauf pour les noms marqués ambigus.
CITY_ALIASES: dict[str, tuple[str, ...]] = {
    "Casablanca": ("casablanca", "casa", "dar el beida", "dar beida", "الدار البيضاء", "كازابلانكا", "البيضاء"),
    "Rabat": ("rabat", "الرباط"),
    "Salé": ("sla", "سلا"),
    "Témara": ("temara", "تمارة"),
    "Mohammedia": ("mohammedia", "mohammadia", "المحمدية"),
    "Tanger": ("tanger", "tangier", "طنجة"),
    "Tétouan": ("tetouan", "tetuan", "تطوان"),
    "Kénitra": ("kenitra", "القنيطرة"),
    "Fès": ("fes", "fez", "فاس"),
    "Meknès": ("meknes", "مكناس"),
    "Marrakech": ("marrakech", "marrakesh", "مراكش"),
    "Agadir": ("agadir", "أكادير", "اكادير"),
    "Oujda": ("oujda", "وجدة"),
    "El Jadida": ("el jadida", "eljadida", "jadida", "الجديدة"),
    "Safi": ("safi", "asfi", "آسفي", "اسفي"),
    "Essaouira": ("essaouira", "الصويرة"),
    "Béni Mellal": ("beni mellal", "benimellal", "بني ملال"),
    "Khouribga": ("khouribga", "خريبكة"),
    "Settat": ("settat", "سطات"),
    "Berrechid": ("berrechid", "برشيد"),
    "Nador": ("nador", "الناظور"),
    "Al Hoceïma": ("al hoceima", "alhoceima", "hoceima", "الحسيمة"),
    "Larache": ("larache", "العرائش"),
    "Ksar El Kébir": ("ksar el kebir", "ksar elkebir", "القصر الكبير"),
    "Taza": ("taza", "تازة"),
    "Taourirt": ("taourirt", "تاوريرت"),
    "Berkane": ("berkane", "بركان"),
    "Guercif": ("guercif", "جرسيف"),
    "Ouarzazate": ("ouarzazate", "ورزازات"),
    "Errachidia": ("errachidia", "الرشيدية"),
    "Laâyoune": ("laayoune", "el aaiun", "العيون"),
    "Dakhla": ("dakhla", "الداخلة"),
    "Guelmim": ("guelmim", "كلميم"),
    "Tiznit": ("tiznit", "تيزنيت"),
    "Inezgane": ("inezgane", "إنزكان", "انزكان"),
    "Sidi Kacem": ("sidi kacem", "سيدي قاسم"),
    "Sidi Bennour": ("sidi bennour", "سيدي بنور"),
    "Sidi Slimane": ("sidi slimane", "سيدي سليمان"),
    "Youssoufia": ("youssoufia", "اليوسفية"),
    "Benslimane": ("benslimane", "ben slimane", "بنسليمان"),
    "Bouskoura": ("bouskoura", "بوسكورة"),
    "Dar Bouazza": ("dar bouazza", "دار بوعزة"),
    "Nouaceur": ("nouaceur", "النواصر"),
    "Médiouna": ("mediouna", "مديونة"),
    "Skhirat": ("skhirat", "الصخيرات"),
    "Khémisset": ("khemisset", "الخميسات"),
    "Fquih Ben Salah": ("fquih ben salah", "فقيه بن صالح"),
    "Taroudant": ("taroudant", "تارودانت"),
    "Chefchaouen": ("chefchaouen", "chaouen", "شفشاون"),
}

# Une alerte nomme rarement la ville : elle nomme un quartier, une place, une
# avenue. « mazbala fi Ain Sebaa » parle de Casablanca sans jamais l'écrire.
# Seuls des noms non ambigus figurent ici : « Bourgogne » ou « Californie »,
# qui sont aussi des quartiers de Casablanca, sont volontairement écartés.
NEIGHBOURHOOD_ALIASES: dict[str, tuple[str, ...]] = {
    "Casablanca": (
        "ain sebaa", "عين السبع", "ain chock", "عين الشق", "ain diab", "ain borja",
        "anfa", "casa anfa", "sidi belyout", "maarif", "المعاريف",
        "hay mohammadi", "الحي المحمدي", "hay hassani", "الحي الحسني",
        "sidi moumen", "سيدي مومن", "sidi bernoussi", "سيدي البرنوصي",
        "sidi othmane", "سيدي عثمان", "moulay rachid", "مولاي رشيد",
        "ben msick", "بن مسيك", "sbata", "سباتة",
        "derb sultan", "درب السلطان", "derb ghallef", "درب غلف",
        "mers sultan", "roches noires", "oulfa", "lissasfa", "sidi maarouf",
        "el fida", "الفداء", "zerktouni", "hay el farah",
        "place 16 novembre", "place du 16 novembre", "place de 16 novembre",
    ),
    "Rabat": ("hay riad", "حي الرياض", "souissi", "السويسي", "yacoub el mansour", "يعقوب المنصور"),
    "Salé": ("tabriquet", "تابريكت", "bettana", "بطانة", "sala al jadida", "سلا الجديدة"),
    "Marrakech": ("gueliz", "كليز", "jamaa el fna", "جامع الفنا", "menara", "المنارة", "daoudiate"),
    "Tanger": ("beni makada", "بني مكادة", "malabata", "boukhalef", "marchan", "dradeb"),
    "Agadir": ("talborjt", "تالبرجت"),
    "Fès": ("fes el bali", "فاس البالي", "zouagha", "زواغة"),
}


# Pièges du français : une fois les accents retirés, ces noms de villes
# deviennent des mots courants. « c'est sale » ne parle pas de la ville de Salé,
# et « on a fete la reprise » ne parle pas de Fès. Pour ces noms, on exige la
# forme accentuée exacte, quitte à manquer une graphie sans accent : rattacher à
# tort des dizaines de plaintes « c'est sale » à Salé serait bien plus grave.
ACCENT_SENSITIVE_ALIASES: dict[str, tuple[str, ...]] = {
    "Salé": ("salé",),
}

# Sources possibles du rattachement, exposées à l'interface pour vérification.
SOURCE_LABELS = {
    "text": "texte de l'alerte",
    "title": "titre de la publication",
    "parent_text": "publication parente",
    "parent_title": "titre de la publication parente",
    "url": "lien de la source",
}


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def _normalise_arabic(value: str) -> str:
    """Ramène les variantes d'alef et retire les diacritiques arabes."""

    value = re.sub(r"[ؐ-ًؚ-ٰٟـ]", "", value)
    value = re.sub(r"[آأإٱ]", "ا", value)
    return value


def normalise(value: str | None, *, keep_accents: bool = False) -> str:
    """Texte comparable : minuscules, ponctuation réduite à des espaces.

    `keep_accents` sert aux noms ambigus qui n'existent que sous leur forme
    accentuée (voir ACCENT_SENSITIVE_ALIASES).
    """

    if not value:
        return ""
    text = _normalise_arabic(str(value).lower())
    if not keep_accents:
        text = _strip_accents(text)
    # On garde les lettres arabes (؀-ۿ) en plus des alphanumériques :
    # tout le reste devient un espace, ce qui transforme « el-jadida » en
    # « el jadida » et permet de retrouver un slug d'URL.
    text = re.sub(r"[^0-9a-z؀-ۿ]+", " ", text)
    return f" {text.strip()} "


# En arabe, les particules « و ف ب ل ك » et l'article « ال » se collent au mot
# suivant : « فعين السبع » (« à Aïn Sebaa ») ne contient pas « عين السبع »
# entouré d'espaces. Sans cette tolérance, la moitié des commentaires arabes
# passeraient à côté de leur ville.
ARABIC_PROCLITICS = "وفبلك"
ARABIC_RANGE = re.compile(r"[؀-ۿ]")


def _contains(haystack: str, alias: str) -> bool:
    """Cherche un alias sans jamais matcher au milieu d'un mot latin."""

    if not alias:
        return False
    if ARABIC_RANGE.search(alias):
        pattern = rf"[\s{ARABIC_PROCLITICS}]{re.escape(alias)}(?=\s)"
        return re.search(pattern, haystack) is not None
    return f" {alias} " in haystack


def _iter_aliases():
    """Toutes les correspondances (ville, alias, sensible aux accents)."""

    for city, aliases in CITY_ALIASES.items():
        for alias in aliases:
            yield city, alias, False
    for city, aliases in NEIGHBOURHOOD_ALIASES.items():
        for alias in aliases:
            yield city, alias, False
    for city, aliases in ACCENT_SENSITIVE_ALIASES.items():
        for alias in aliases:
            yield city, alias, True


def _matches(value: str | None) -> list[tuple[int, str, str]]:
    """Correspondances trouvées dans `value`, les alias les plus longs d'abord.

    Un alias long l'emporte sur un alias court : « sidi bennour » ne doit pas
    être ramené à un fragment plus court trouvé dans la même phrase.
    """

    if not value:
        return []

    plain = normalise(value)
    accented = normalise(value, keep_accents=True)

    found: list[tuple[int, str, str]] = []
    for city, alias, accent_sensitive in _iter_aliases():
        needle = normalise(alias, keep_accents=accent_sensitive).strip()
        if not needle:
            continue
        haystack = accented if accent_sensitive else plain
        if _contains(haystack, needle):
            found.append((len(needle), city, alias))

    found.sort(key=lambda item: item[0], reverse=True)
    return found


def detect_city(
    *,
    text: str | None = None,
    title: str | None = None,
    parent_text: str | None = None,
    parent_title: str | None = None,
    url: str | None = None,
    extra_texts: Iterable[str | None] = (),
) -> dict[str, Any]:
    """Rattache une alerte à une ville.

    Ordre de recherche, du plus spécifique au moins spécifique :

    1. `text` — le texte de l'alerte elle-même ;
    2. `title` — son titre ;
    3. `parent_text` — le texte de la publication sous laquelle elle est
       publiée. Un commentaire qui ne nomme aucune ville hérite du territoire
       de son post : « l'odeur commence à s'intensifier » sous un article
       consacré à Casablanca concerne bien Casablanca ;
    4. `parent_title` ;
    5. `url`.

    Retourne toujours un dictionnaire :

    - `city` : nom affiché, ou None si aucune ville n'est reconnue ;
    - `city_source` : la clé ci-dessus qui a répondu ;
    - `city_source_label` : la même information en français ;
    - `city_evidence` : le mot exact qui a déclenché le rattachement, pour
      qu'un quartier (« ain sebaa ») soit vérifiable et non magique ;
    - `cities` : toutes les villes citées, pour information.
    """

    ordered: tuple[tuple[str, str | None], ...] = (
        ("text", text),
        ("title", title),
        ("parent_text", parent_text),
        ("parent_title", parent_title),
        ("url", url),
    )

    city: str | None = None
    source: str | None = None
    evidence: str | None = None

    for source_key, value in ordered:
        matches = _matches(value)
        if matches:
            _, city, evidence = matches[0]
            source = source_key
            break

    if city is None:
        for value in extra_texts:
            matches = _matches(value)
            if matches:
                _, city, evidence = matches[0]
                source = "text"
                break

    cities: list[str] = []
    for _, value in ordered:
        for _, found, _alias in _matches(value):
            if found not in cities:
                cities.append(found)
    for value in extra_texts:
        for _, found, _alias in _matches(value):
            if found not in cities:
                cities.append(found)

    return {
        "city": city,
        "city_source": source,
        "city_source_label": SOURCE_LABELS.get(source or "", None),
        "city_evidence": evidence,
        "cities": cities,
    }


def known_cities() -> list[str]:
    """Liste de référence, triée, pour les tests et l'interface."""

    return sorted(
        set(CITY_ALIASES) | set(ACCENT_SENSITIVE_ALIASES) | set(NEIGHBOURHOOD_ALIASES)
    )
