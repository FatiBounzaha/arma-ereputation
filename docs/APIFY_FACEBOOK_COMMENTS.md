# Commentaires Facebook publics via Apify — V10.3

## Objectif

Le projet utilise `apify/facebook-comments-scraper` pour récupérer les
commentaires **publiquement visibles** des posts Facebook retenus dans les deux
POC. La collecte produit des données structurées, contrairement aux captures
Selenium qui servent seulement de preuve visuelle.

## Chaîne automatisée

```text
Découverte des posts Facebook
→ qualification métier
→ export automatique vers data/fb.txt
→ appel Apify
→ commentaires JSON
→ normalisation PostgreSQL
→ nettoyage et détection de langue
→ triage, sentiment et alertes
→ décisions et brouillons FR/AR
→ affichage dans Réputation Sociale
```

Le workflow n8n appelle FastAPI. Le token Apify n'est jamais enregistré dans le
workflow : il reste dans `.env` côté backend.

## Configuration `.env`

```env
FACEBOOK_COMMENTS_PROVIDER=apify
APIFY_FACEBOOK_COMMENTS_ENABLED=true
APIFY_API_TOKEN=...
APIFY_FACEBOOK_ACTOR_ID=apify/facebook-comments-scraper
APIFY_API_BASE_URL=https://api.apify.com
APIFY_MAX_POSTS_PER_RUN=20
APIFY_COLLECT_ALL_COMMENTS=true
APIFY_ALL_COMMENTS_LIMIT=500
APIFY_MAX_COMMENTS_PER_POST=500
APIFY_INCLUDE_REPLIES=true
APIFY_COMMENTS_MODE=Newest
APIFY_ONLY_COMMENTS_NEWER_THAN=
FACEBOOK_REGISTRY_PRESERVE_EXISTING=true
APIFY_ONLY_COMMENTS_NEWER_THAN=
APIFY_RUN_TIMEOUT_SECONDS=300
APIFY_STORE_PROFILE_URLS=false
```

Valeurs autorisées pour `APIFY_COMMENTS_MODE` : `All`, `Most relevant`,
`Newest`.

## Test manuel

```powershell
.\.venv\Scripts\Activate.ps1
python scripts\export_facebook_retained_links.py
python scripts\sync_apify_facebook_comments.py
```

Ou :

```powershell
.\scripts\run_apify_comments.ps1
```

Ce script (comme `POST /api/facebook/comments/sync`) enchaîne désormais
**collecte → tri → génération des alertes** en une seule commande : un
commentaire actionnable apparaît donc directement dans la section
« Commentaires Facebook à traiter » du portail Réputation Sociale, sans avoir
à relancer le pipeline quotidien complet.

> **Historique du correctif (V2.1) — commentaires absents des alertes**
> Avant ce correctif, la collecte manuelle (script ou bouton "Synchroniser")
> enregistrait bien les commentaires en base de données, mais s'arrêtait là :
> le tri (`triage_social_comments`) et la génération des alertes
> (`generate_alerts_for_negative_mentions`) n'étaient exécutés que par le
> pipeline n8n complet. Résultat : des commentaires réels (ex. sur un post
> ayant 360 commentaires) restaient invisibles dans la section "Alertes" tant
> que le pipeline quotidien n'avait pas tourné. La collecte manuelle appelle
> maintenant systématiquement les trois étapes dans l'ordre.

## Diagnostiquer un blocage

`GET /api/facebook/comments/diagnostic` (sans secret) donne un état de santé
de la chaîne :

- `facebook_comments_not_yet_triaged` : commentaires collectés mais pas encore
  classés (`triage_comments` n'a pas encore tourné dessus) ;
- `facebook_comments_actionable` : commentaires négatifs ou nécessitant une
  réponse d'après le tri ;
- `facebook_comments_actionable_missing_alert` : commentaires actionnables qui
  n'ont **toujours pas** d'alerte associée — s'il est différent de 0, relancez
  `scripts/sync_apify_facebook_comments.py` ou le pipeline complet ;
- `pipeline_health` : `"ok"` ou un message expliquant l'action à effectuer.

## Endpoints

- `GET /api/facebook/integration/status`
- `GET /api/facebook/comments/diagnostic`
- `POST /api/facebook/comments/sync` (collecte + tri + alertes)
- `GET /api/facebook/comments?limit=100`

## Données enregistrées

Pour chaque commentaire : identifiant Facebook, texte, URL du commentaire,
post parent, auteur public lorsque disponible, date, likes, profondeur de fil,
provider `apify`, payload brut et date de collecte.

## Envoi des réponses

Apify sert uniquement à la **collecte**. Une réponse réelle ne peut être envoyée
que via Meta Graph API, avec une Page autorisée et une validation humaine. Sans
Meta, le portail permet toujours de générer, copier et valider un brouillon.

## Limites

- seuls les commentaires visibles publiquement sont accessibles ;
- certains commentaires privés ne figurent pas dans le Dataset ;
- l'Actor est un service payant selon l'usage ;
- aucune donnée privée, aucun cookie personnel et aucun contournement de
  connexion ne sont utilisés.

Par défaut, les URLs de profils et les photos de profil ne sont pas conservées (`APIFY_STORE_PROFILE_URLS=false`).
