"""V11.8 — Filtre par ville dans la section Alertes.

ARMA opère par contrat de gestion déléguée : une alerte n'a de valeur
opérationnelle que rapportée à un territoire. Le nom de la ville n'existe dans
aucune colonne, il est lu dans le texte, le titre ou l'URL.
"""

from pathlib import Path

from backend.processing.city_detection import (
    CITY_ALIASES,
    NEIGHBOURHOOD_ALIASES,
    detect_city,
    known_cities,
    normalise,
)

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# 1. Les trois emplacements où la ville peut apparaître
# --------------------------------------------------------------------------


def test_city_is_read_from_the_comment_text():
    result = detect_city(text="Les poubelles débordent depuis 3 jours à Casablanca")
    assert result["city"] == "Casablanca"
    assert result["city_source"] == "text"
    assert result["city_source_label"] == "texte de l'alerte"


def test_city_is_read_from_the_post_title():
    result = detect_city(
        text="Rien n'a changé chez nous",
        title="Propreté urbaine : El Jadida revoit sa copie",
    )
    assert result["city"] == "El Jadida"
    assert result["city_source"] == "title"


def test_city_is_read_from_the_url_slug():
    result = detect_city(
        text="Article à lire",
        url="https://leseco.ma/maroc/kenitra-mecomar-decroche-le-contrat.html",
    )
    assert result["city"] == "Kénitra"
    assert result["city_source"] == "url"


def test_text_wins_over_title_and_url():
    """Un commentaire qui cite une ville parle de cette ville.

    Même publié sous un article consacré à une autre ville : c'est le signal
    le plus spécifique à l'alerte. C'est cette ville-là, et elle seule, qui
    rattache l'alerte à un territoire.
    """

    result = detect_city(
        text="Le même problème existe à Tanger",
        title="Dossier déchets à Casablanca",
        url="https://example.ma/casablanca/dechets",
    )
    assert result["city"] == "Tanger"
    assert result["city_source"] == "text"
    # Les autres villes citées restent connues, pour information seulement :
    # elles ne comptent pas dans la répartition.
    assert set(result["cities"]) == {"Tanger", "Casablanca"}


# --------------------------------------------------------------------------
# 1 bis. La ville est très souvent citée indirectement
# --------------------------------------------------------------------------


POST_CASABLANCA = (
    "En tant que citoyen de Casablanca, je suis préoccupé par la qualité "
    "du service de nettoyage assuré dans mon quartier"
)


def test_a_neighbourhood_names_its_city():
    """« mazbala fi Aïn Sebaa » parle de Casablanca sans jamais l'écrire."""

    result = detect_city(text="Les bennes de Sidi Moumen ne sont jamais vidées")
    assert result["city"] == "Casablanca"
    assert result["city_evidence"] == "sidi moumen"


def test_arabic_proclitic_does_not_hide_the_neighbourhood():
    """En arabe, « ف » se colle au mot : « فعين السبع » = « à Aïn Sebaa ».

    Sans tolérance sur ces particules, l'alias « عين السبع » entouré
    d'espaces ne serait jamais trouvé.
    """

    result = detect_city(text="اما عندنا مزبلة فعين السبع غير بعيد عن المقاطعة")
    assert result["city"] == "Casablanca"
    assert result["city_evidence"] == "عين السبع"


def test_a_landmark_names_its_city():
    result = detect_city(text="les restaurants la place de 16 novembre sale avec le snack")
    assert result["city"] == "Casablanca"


def test_comment_without_city_inherits_the_parent_post():
    """Un commentaire sous un post consacré à une ville concerne cette ville.

    « L'odeur commence à s'intensifier » ne nomme aucun territoire, mais il
    répond à un article sur Casablanca : opérationnellement, la plainte
    relève bien du contrat de Casablanca.
    """

    result = detect_city(
        text="Oui effectivement car l'odeur commence a s'intensifier",
        parent_text=POST_CASABLANCA,
    )
    assert result["city"] == "Casablanca"
    assert result["city_source"] == "parent_text"
    assert result["city_source_label"] == "publication parente"


def test_the_comment_own_city_still_wins_over_the_parent_post():
    result = detect_city(text="Le même souci à Tanger", parent_text=POST_CASABLANCA)
    assert result["city"] == "Tanger"
    assert result["city_source"] == "text"


def test_without_a_parent_a_generic_comment_stays_unattached():
    """L'héritage est la seule chose qui rattache un texte générique.

    Isolé, « Manque d'éducation » ne désigne aucun territoire.
    """

    assert detect_city(text="Manque d éducation")["city"] is None


def test_neighbourhood_aliases_are_unambiguous():
    """Un quartier ne doit pas exister sous le même nom dans deux villes."""

    seen: dict[str, str] = {}
    for city, aliases in NEIGHBOURHOOD_ALIASES.items():
        for alias in aliases:
            key = normalise(alias).strip()
            assert key not in seen, f"{alias} revendique {seen.get(key)} et {city}"
            seen[key] = city


# --------------------------------------------------------------------------
# 2. Pièges linguistiques
# --------------------------------------------------------------------------


def test_dirty_in_french_is_never_the_city_of_sale():
    """« c'est sale » est le mot le plus fréquent des plaintes déchets.

    Sans accent, « sale » et « Salé » se confondent une fois normalisés.
    Rattacher toutes ces plaintes à la ville de Salé fausserait complètement
    le filtre, donc cette graphie est volontairement ignorée.
    """

    for phrase in ("c'est vraiment sale dans mon quartier", "Casa est trop salle", "sale"):
        assert detect_city(text=phrase)["city"] != "Salé"


def test_accented_sale_is_recognised():
    assert detect_city(text="La collecte à Salé s'est améliorée")["city"] == "Salé"


def test_city_name_inside_a_longer_word_is_ignored():
    # Les alias sont cherchés entre deux espaces, jamais au milieu d'un mot.
    assert detect_city(text="safiarrive demain")["city"] is None
    assert detect_city(text="La benne de Safi est pleine")["city"] == "Safi"


def test_arabic_city_names_are_detected():
    assert detect_city(text="الأزبال متراكمة في الدار البيضاء منذ أسبوع")["city"] == "Casablanca"
    assert detect_city(text="النظافة في طنجة تحسنت")["city"] == "Tanger"


def test_common_nickname_is_detected():
    assert detect_city(text="Casa est trop sale il faut une société par région")["city"] == "Casablanca"


def test_no_city_returns_none_rather_than_a_default():
    result = detect_city(text="Rien à signaler", title="Actualité nationale")
    assert result["city"] is None
    assert result["cities"] == []
    assert result["city_source"] is None


# --------------------------------------------------------------------------
# 3. Normalisation
# --------------------------------------------------------------------------


def test_normalisation_turns_url_slugs_into_searchable_words():
    assert "beni mellal" in normalise("https://ville.ma/beni-mellal/dechets")


def test_every_alias_survives_normalisation():
    """Un alias qui disparaît à la normalisation ne matcherait jamais."""

    for city, aliases in CITY_ALIASES.items():
        for alias in aliases:
            assert normalise(alias).strip(), f"alias vide après normalisation : {city} / {alias}"


def test_reference_list_is_not_empty_and_sorted():
    cities = known_cities()
    assert len(cities) > 30
    assert cities == sorted(cities)


# --------------------------------------------------------------------------
# 4. Contrat d'interface
# --------------------------------------------------------------------------


def test_alert_response_exposes_the_city_fields():
    from backend.api.schemas import AlertResponse

    for field in ("city", "city_source", "city_source_label", "city_evidence", "cities"):
        assert field in AlertResponse.model_fields


def test_alerts_endpoint_accepts_a_city_parameter():
    import inspect

    from backend.api.alerts import read_alerts

    assert "city" in inspect.signature(read_alerts).parameters


def test_portal_offers_the_city_filter():
    page = (ROOT / "frontend" / "ReputationSocialeARMA.html").read_text(encoding="utf-8")
    assert 'id="alert-city-filter"' in page
    assert "refreshCityFilterOptions" in page
    # Le filtre s'applique avant le tri par sentiment.
    assert "alerts.filter(alertMatchesCity)" in page
    # Une alerte compte pour une seule ville, pas pour chacune de celles
    # qu'elle cite : sans cela la repartition depasserait le total.
    assert "city === ALERT_CITY_FILTER" in page
    assert "counts.set(city, (counts.get(city) || 0) + 1)" in page
    # Les villes citees en second restent visibles, en infobulle seulement.
    assert "Cite aussi" in page
    # L'origine du rattachement est affichée pour vérification.
    assert "city_source_label" in page


def test_each_alert_counts_for_exactly_one_city():
    """La répartition par ville doit totaliser le nombre d'alertes.

    Une alerte qui cite Tanger et Casablanca ne doit apparaître que sous la
    ville retenue, sinon la somme des compteurs dépasse le nombre réel
    d'alertes et la répartition devient illisible.
    """

    alerts = [
        detect_city(text="Le même problème existe à Tanger", title="Dossier Casablanca"),
        detect_city(text="Poubelles pleines à Casablanca"),
        detect_city(text="Rien à signaler"),
        detect_city(text="Collecte correcte", title="Propreté à El Jadida"),
    ]

    counts: dict[str, int] = {}
    without_city = 0
    for alert in alerts:
        if alert["city"] is None:
            without_city += 1
        else:
            counts[alert["city"]] = counts.get(alert["city"], 0) + 1

    assert sum(counts.values()) + without_city == len(alerts)
    assert counts == {"Tanger": 1, "Casablanca": 1, "El Jadida": 1}
    assert without_city == 1
