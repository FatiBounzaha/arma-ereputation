# Collecte multi-source - stratégie V4

## Deux flux séparés

### Flux e-réputation

Objectif : tout contenu qui parle réellement de la qualité du service d'ARMA ou d'un concurrent.

- articles et presse ;
- posts sociaux ;
- commentaires autorisés ;
- plaintes, retards, qualité, grèves, satisfaction.

Les contenus officiels et les profils RH sont conservés si nécessaire pour audit, mais exclus du score.

### Flux Marketing Contenu

Objectif : sélectionner des signaux utiles pour prendre une décision éditoriale.

Catégories :

- `competitor` ;
- `opportunity` ;
- `regulation` ;
- `innovation` ;
- `sector`.

Un contenu n'est affiché que si `display_in_marketing=true` et si son score dépasse le seuil de l'API.

## Pourquoi ne pas mettre un LLM au début de toute la collecte ?

Un LLM peut aider sur les cas ambigus, mais il ne doit pas remplacer :

- les règles d'URL ;
- la gestion des quotas ;
- la déduplication ;
- les permissions des plateformes ;
- les exclusions légales et les filtres de bruit.

La meilleure architecture est :

```text
règles déterministes -> score de pertinence -> LLM optionnel pour synthèse
```

## Matrice des connecteurs

| Plateforme | Découverte publique | Commentaires | Remarque |
|---|---|---|---|
| Facebook | Serper | Meta Graph si autorisé | pages externes parfois inaccessibles |
| Instagram | Serper | Graph API du compte pro ARMA | pas de recherche publique exhaustive |
| LinkedIn | Serper | API officielle pour organisations administrées | accès restreint |
| X | Serper + X API optionnelle | réponses via X API selon plan | bearer token requis |
| Presse | Serper News + RSS | selon source | filtrage métier V4 |
