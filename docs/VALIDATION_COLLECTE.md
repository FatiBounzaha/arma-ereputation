# Validation de la collecte

## Contenus conservés dans Marketing Contenu

- difficulté financière, contrat, grève ou performance d'un concurrent du secteur ;
- appel d'offres ou marché public de propreté/assainissement ;
- réglementation déchets/environnement ;
- innovation utile au secteur ;
- actualité sectorielle marocaine exploitable.

## Contenus masqués

- profils de salariés et parcours professionnels ;
- recrutements et offres d'emploi ;
- nominations individuelles sans impact métier ;
- vœux, Reels génériques, pages About et profils ;
- homonymes `ARMA`, `OZONE` ou `SOS` sans contexte déchets/propreté ;
- publications sociales génériques sans valeur stratégique.

## Exemple testé

`Soufiane Jakani a rejoint Suez en 2019 où il a occupé...`

Résultat : `display_in_marketing=false`, flag `noise_or_hr_content`.

## Contrôle après migration

```powershell
python -m backend.processing.qualify_existing_mentions
python -m backend.services.business_intelligence_collection_service
```

Puis lancer l'API et vérifier :

```text
GET /api/content/recent-mentions?limit=8&include_social=false
```
