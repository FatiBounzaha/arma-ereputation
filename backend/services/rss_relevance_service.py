from __future__ import annotations

import html
import re
import unicodedata
from typing import Any


# Variantes possibles des noms d'ARMA et de ses concurrents.
# Cette liste pourra ensuite être remplacée par les alias enregistrés
# dans la table organization_aliases.
ORGANIZATION_KEYWORDS: dict[str, list[str]] = {
    "ARMA": [
        "arma",
        "arma environnement",
        "arma maroc",
        "@arma_ma",
        "أرما",
        "ارما",
        "شركة أرما",
        "شركة ارما",
    ],
    "OZONE": [
        "ozone",
        "ozone environnement",
        "ozone maroc",
        "أوزون",
        "اوزون",
    ],
    "Averda": [
        "averda",
        "averda maroc",
        "أفيردا",
        "افيردا",
    ],
    "Suez Maroc": [
        "suez",
        "suez maroc",
        "suez environnement",
        "سويز",
        "سويز المغرب",
    ],
    "SOS": [
        "sos environnement",
        "sos déchets",
        "sos dechets",
    ],
}


# Mots-clés de veille sectorielle.
# Les clés correspondent aux slugs déjà présents dans la table topics.
SECTOR_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "retard-collecte": [
        "retard de collecte",
        "absence de collecte",
        "déchets non ramassés",
        "dechets non ramasses",
        "poubelles non ramassées",
        "poubelles non ramassees",
        "تأخر جمع النفايات",
        "عدم جمع النفايات",
        "النفايات لم تجمع",
    ],
    "proprete-urbaine": [
        "propreté urbaine",
        "proprete urbaine",
        "nettoyage urbain",
        "services de propreté",
        "services de proprete",
        "collecte des déchets",
        "collecte des dechets",
        "gestion des déchets",
        "gestion des dechets",
        "déchets ménagers",
        "dechets menagers",
        "ordures ménagères",
        "ordures menageres",
        "النظافة الحضرية",
        "النظافة",
        "جمع النفايات",
        "تدبير النفايات",
        "النفايات المنزلية",
        "الزبالة",
    ],
    "reglementation": [
        "réglementation déchets",
        "reglementation dechets",
        "loi sur les déchets",
        "loi sur les dechets",
        "tri à la source",
        "tri a la source",
        "norme environnementale",
        "obligation environnementale",
        "قانون النفايات",
        "تنظيم النفايات",
        "الفرز من المصدر",
        "تشريع بيئي",
    ],
    "appel-offres": [
        "appel d offres",
        "appel d'offres",
        "marché public",
        "marche public",
        "marchés publics",
        "marches publics",
        "gestion déléguée",
        "gestion deleguee",
        "délégation de service public",
        "delegation de service public",
        "contrat de propreté",
        "contrat de proprete",
        "صفقة عمومية",
        "الصفقات العمومية",
        "طلب عروض",
        "تدبير مفوض",
    ],
    "developpement-durable": [
        "économie circulaire",
        "economie circulaire",
        "recyclage",
        "valorisation des déchets",
        "valorisation des dechets",
        "gestion durable des déchets",
        "gestion durable des dechets",
        "zéro déchet",
        "zero dechet",
        "réduction des déchets",
        "reduction des dechets",
        "pollution liée aux déchets",
        "pollution liee aux dechets",
        "ville propre",
        "villes propres",
        "إعادة التدوير",
        "تدوير النفايات",
        "الاقتصاد الدائري",
        "تثمين النفايات",
        "تقليل النفايات",
        "مدينة نظيفة",
        "مدن نظيفة",
    ],
    "traitement-eau": [
        "traitement de l eau",
        "traitement de l'eau",
        "eaux usées",
        "eaux usees",
        "assainissement",
        "station d épuration",
        "station d'epuration",
        "station d'épuration",
        "معالجة المياه",
        "المياه العادمة",
        "التطهير السائل",
        "محطة معالجة المياه",
    ],
    "performance-operationnelle": [
        "taux de collecte",
        "taux de propreté",
        "taux de proprete",
        "performance opérationnelle",
        "performance operationnelle",
        "kilomètres parcourus",
        "kilometres parcourus",
        "tonnes collectées",
        "tonnes collectees",
        "معدل الجمع",
        "مؤشرات النظافة",
        "الأداء التشغيلي",
    ],
}


# Certains thèmes sont trop généraux pour être acceptés seuls.
# Par exemple, un appel d'offres ferroviaire ou une performance
# opérationnelle dans l'énergie ne concernent pas ARMA.
CONTEXT_REQUIRED_TOPICS: set[str] = {
    "appel-offres",
    "performance-operationnelle",
}


# Un thème contextuel n'est conservé que si le même article contient
# aussi au moins une expression clairement liée aux métiers d'ARMA.
SECTOR_CONTEXT_KEYWORDS: list[str] = [
    # Déchets et propreté — français.
    "déchet",
    "déchets",
    "dechet",
    "dechets",
    "ordure",
    "ordures",
    "poubelle",
    "poubelles",
    "propreté",
    "proprete",
    "nettoyage urbain",
    "collecte des déchets",
    "collecte des dechets",
    "gestion des déchets",
    "gestion des dechets",
    "tri à la source",
    "tri a la source",
    "recyclage",
    "valorisation des déchets",
    "valorisation des dechets",
    "décharge",
    "decharge",

    # Eau et assainissement — français.
    "eaux usées",
    "eaux usees",
    "assainissement",
    "station d'épuration",
    "station d epuration",
    "traitement de l'eau",
    "traitement de l eau",

    # Déchets et propreté — arabe/darija.
    "النفايات",
    "نفايات",
    "النظافة",
    "نظافة",
    "الزبالة",
    "زبالة",
    "جمع النفايات",
    "تدبير النفايات",
    "إعادة التدوير",
    "اعادة التدوير",
    "تدوير النفايات",
    "الفرز من المصدر",

    # Eau et assainissement — arabe.
    "المياه العادمة",
    "التطهير السائل",
    "معالجة المياه",
    "محطة معالجة المياه",
]


def normalize_text(value: Any) -> str:
    """
    Normalise un texte français, arabe ou darija afin de rendre
    la recherche par mots-clés plus robuste.
    """

    if value is None:
        return ""

    text = html.unescape(str(value))
    text = text.lower().strip()

    # Supprimer les accents français et les voyelles/diacritiques arabes.
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )

    # Normaliser certaines lettres arabes.
    text = text.translate(
        str.maketrans(
            {
                "أ": "ا",
                "إ": "ا",
                "آ": "ا",
                "ى": "ي",
                "ؤ": "و",
                "ئ": "ي",
                "ة": "ه",
                "ـ": "",
            }
        )
    )

    # Remplacer la ponctuation et les séparateurs par des espaces.
    text = re.sub(
        r"[^\w\s]",
        " ",
        text,
        flags=re.UNICODE,
    )
    text = text.replace("_", " ")

    return " ".join(text.split())


def article_to_text(article: dict[str, Any]) -> str:
    """Regroupe les champs textuels disponibles d'un résultat."""

    fields = [
        article.get("title"),
        article.get("snippet"),
        article.get("summary"),
        article.get("description"),
        article.get("content"),
        article.get("raw_text"),
    ]

    return normalize_text(
        " ".join(
            str(value)
            for value in fields
            if value
        )
    )


def contains_keyword(
    normalized_text: str,
    keyword: str,
) -> bool:
    """Vérifie un mot ou une expression sans correspondance partielle."""

    normalized_keyword = normalize_text(keyword)

    if not normalized_keyword:
        return False

    return (
        f" {normalized_keyword} "
        in f" {normalized_text} "
    )


def find_mentioned_organizations(
    article: dict[str, Any],
) -> list[str]:
    """Retourne les organisations explicitement citées."""

    article_text = article_to_text(article)

    if not article_text:
        return []

    mentioned: list[str] = []

    for organization_name, keywords in (
        ORGANIZATION_KEYWORDS.items()
    ):
        if any(
            contains_keyword(article_text, keyword)
            for keyword in keywords
        ):
            mentioned.append(organization_name)

    return mentioned


def find_sector_topics(
    article: dict[str, Any],
) -> dict[str, list[str]]:
    """
    Retourne les thèmes sectoriels détectés et les mots-clés
    responsables de la détection.

    Les thèmes trop généraux, comme appel-offres et
    performance-operationnelle, exigent aussi un contexte lié
    aux déchets, à la propreté ou à l'assainissement.
    """

    article_text = article_to_text(article)

    if not article_text:
        return {}

    has_sector_context = any(
        contains_keyword(article_text, keyword)
        for keyword in SECTOR_CONTEXT_KEYWORDS
    )

    detected_topics: dict[str, list[str]] = {}

    for topic_slug, keywords in (
        SECTOR_TOPIC_KEYWORDS.items()
    ):
        matched_keywords = [
            keyword
            for keyword in keywords
            if contains_keyword(article_text, keyword)
        ]

        if not matched_keywords:
            continue

        if (
            topic_slug in CONTEXT_REQUIRED_TOPICS
            and not has_sector_context
        ):
            continue

        detected_topics[topic_slug] = matched_keywords

    return detected_topics


def classify_article(
    article: dict[str, Any],
) -> dict[str, Any]:
    """
    Classe un contenu dans l'une des quatre catégories :

    - reputation : cite directement une organisation ;
    - sector : actualité sectorielle sans organisation ;
    - both : organisation + sujet sectoriel ;
    - irrelevant : aucun lien utile avec le projet.
    """

    organizations = find_mentioned_organizations(article)
    sector_topics = find_sector_topics(article)

    if organizations and sector_topics:
        content_scope = "both"
    elif organizations:
        content_scope = "reputation"
    elif sector_topics:
        content_scope = "sector"
    else:
        content_scope = "irrelevant"

    return {
        "content_scope": content_scope,
        "organizations": organizations,
        "sector_topics": list(sector_topics.keys()),
        "matched_sector_keywords": sector_topics,
        "is_relevant": content_scope != "irrelevant",
    }


def is_relevant_article(
    article: dict[str, Any],
) -> bool:
    """Un contenu est utile pour la réputation ou le marketing."""

    return bool(classify_article(article)["is_relevant"])


def filter_relevant_articles(
    articles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Garde les contenus de réputation et de veille sectorielle."""

    return [
        article
        for article in articles
        if is_relevant_article(article)
    ]


def test_relevance_filter() -> None:
    """Test local sans RSS et sans PostgreSQL."""

    test_articles = [
        {
            "title": (
                "ARMA Environnement lance une nouvelle "
                "opération de propreté urbaine"
            ),
        },
        {
            "title": (
                "OZONE annonce une réorganisation "
                "de ses activités"
            ),
        },
        {
            "title": (
                "Casablanca lance un appel d'offres "
                "pour la collecte des déchets"
            ),
        },
        {
            "title": (
                "المغرب يعزز الفرز من المصدر "
                "وإعادة تدوير النفايات"
            ),
        },
        {
            "title": (
                "L'ONCF lance un appel d'offres pour une nouvelle "
                "liaison ferroviaire"
            ),
        },
        {
            "title": (
                "De nouvelles locomotives renforcent la performance "
                "opérationnelle du réseau ferroviaire"
            ),
        },
        {
            "title": (
                "La météo prévoit une forte chaleur "
                "à Casablanca"
            ),
        },
    ]

    print("TEST DE CLASSIFICATION DES CONTENUS")
    print("=" * 72)

    for article in test_articles:
        classification = classify_article(article)

        print(f"\nTitre : {article['title']}")
        print(
            "Catégorie : "
            f"{classification['content_scope']}"
        )
        print(
            "Organisations : "
            f"{classification['organizations']}"
        )
        print(
            "Thèmes sectoriels : "
            f"{classification['sector_topics']}"
        )


if __name__ == "__main__":
    test_relevance_filter()