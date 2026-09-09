# Commencer ici — ARMA PFA VERSION FINALE

## Configuration Apify obligatoire pour les commentaires publics

Ajoutez dans `.env` :

```env
FACEBOOK_COMMENTS_PROVIDER=apify
APIFY_FACEBOOK_COMMENTS_ENABLED=true
APIFY_API_TOKEN=...
APIFY_FACEBOOK_ACTOR_ID=apify/facebook-comments-scraper
APIFY_COLLECT_ALL_COMMENTS=true
APIFY_ALL_COMMENTS_LIMIT=500
APIFY_MAX_COMMENTS_PER_POST=500
APIFY_INCLUDE_REPLIES=true
APIFY_COMMENTS_MODE=Newest
APIFY_ONLY_COMMENTS_NEWER_THAN=
FACEBOOK_REGISTRY_PRESERVE_EXISTING=true
```

Le workflow exporte les posts Facebook retenus vers `data/fb.txt`, appelle Apify,
rattache chaque commentaire au post original, puis le classe en positif, neutre ou
négatif. Tous les commentaires utiles participent au score. Chaque commentaire
négatif concernant ARMA apparaît comme une alerte individuelle.

## 1. Ouvrir le bon dossier

Placez PowerShell à la racine du projet, là où se trouvent `backend`, `frontend`,
`n8n`, `requirements.txt` et `.env.example`.

## 2. Préparer l'environnement

Installation automatique :

```powershell
.\scripts\setup_project.ps1
```

Ou réutiliser un environnement Python déjà fonctionnel :

```powershell
& "C:\Users\Ho\Downloads\ARMA_PFA_v4_corrige\ARMA_PFA_v4\.venv\Scripts\Activate.ps1"
python -m pip install -r requirements.txt
```

Créez `.env` à partir de `.env.example` et placez-y vos vraies clés. Ne partagez
jamais ce fichier et ne l'ajoutez pas à GitHub.

Configuration IA recommandée :

```env
SENTIMENT_PROVIDER=huggingface
COMMENT_TRIAGE_PROVIDER=claude
COMMENT_TRIAGE_MODEL=claude-haiku-4-5-20251001
RESPONSE_DRAFT_PROVIDER=claude
POST_CONTENT_PROVIDER=claude
```

## 3. Mettre PostgreSQL à jour

```powershell
python -m alembic upgrade head
python -m backend.database.seed
python -m backend.database.seed_rss_sources
```

## 4. Lancer le backend

```powershell
.\scripts\run_backend.ps1
```

Vérifiez :

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/db-health
http://127.0.0.1:8000/api/orchestration/steps
```

Gardez ce terminal ouvert.

## 5. Lancer n8n

Dans un deuxième terminal :

```powershell
.\scripts\run_n8n.ps1
```

Ouvrez `http://127.0.0.1:5678`. Si votre workflow **V10.3 Apify** existe déjà,
gardez-le : aucun nouveau workflow n’est nécessaire. Sur une nouvelle installation
seulement, importez :

```text
n8n/workflows/ARMA_Pipeline_Quotidien_n8n.json
```

Dans le nœud **Configuration ARMA** :

- utilisez `http://127.0.0.1:8000` si n8n tourne directement sur Windows ;
- utilisez `http://host.docker.internal:8000` si n8n tourne dans Docker ;
- renseignez la même clé que `N8N_ORCHESTRATION_TOKEN` seulement si vous en avez
  configuré une.

Cliquez sur **Test workflow**. Le dernier nœud doit indiquer :

- `completed` si toutes les étapes réussissent ;
- `partial` uniquement si une étape métier échoue réellement. Un collecteur Facebook optionnel non configuré retourne un avertissement non bloquant.

Enregistrez puis activez le workflow. Il est planifié chaque lundi à 07:00 dans le
fuseau `Africa/Casablanca`. Le reporting porte sur la semaine complète précédente (lundi → dimanche) et utilise la date de publication, pas la date de collecte.

## 6. Lancer les interfaces

Dans un troisième terminal :

```powershell
.\scripts\run_frontend.ps1
```

Ouvrez :

```text
http://127.0.0.1:5500/MarketingContenuARMA.html
http://127.0.0.1:5500/ReputationSocialeARMA.html
```

Rechargez avec `Ctrl + F5` après l'exécution n8n.


## 7. Captures Facebook automatiques

Le workflow reconstruit `data/fb.txt` à partir des publications Facebook retenues dans la veille, des alertes existantes et des candidats réputationnels. Apify récupère leurs commentaires publics, puis Selenium capture les posts comme preuve visuelle. Vérifiez le résultat ici :

```text
http://127.0.0.1:8000/api/facebook-screenshots/status
```

Test manuel avec Chrome visible :

```powershell
.\scripts\run_facebook_screenshots.ps1
```

Facebook peut demander une connexion. Le projet ne contourne pas cette restriction ; le statut le signale clairement.

## 8. Vérifier le résultat

```text
http://127.0.0.1:8000/api/quality/status
http://127.0.0.1:8000/api/facebook/comments/diagnostic
http://127.0.0.1:8000/api/facebook/comments/summary?organization=ARMA&days=90
```

Le contrôle indique la fraîcheur de la collecte, le dernier run n8n, les étapes
en échec, les alertes ouvertes, la formule de score et les 8 posts attendus.

## 9. Commande Python de secours

La commande suivante reste disponible uniquement pour un diagnostic manuel :

```powershell
python -m backend.orchestration.run_daily_pipeline
```

Ne la programmez pas en parallèle du workflow n8n, sinon le pipeline peut être
exécuté deux fois.

## Limites externes

- Claude analyse et rédige, mais ne télécharge pas lui-même les données sociales.
- Apify peut collecter les commentaires Facebook rendus publiquement visibles. Meta reste nécessaire pour envoyer une réponse depuis une Page autorisée.
- Le portail HTML/FastAPI est prêt à être intégré, mais l'authentification du vrai
  portail ARMA doit être branchée par l'équipe qui le gère.

## Correctif V11 — commentaires Facebook

Après installation de cette version, exécutez une fois `scripts\reprocess_facebook_comments.ps1` pour réparer les anciennes dates de collecte, retirer les commentaires hors sujet et recalculer le score. Le portail utilise ensuite exactement la période affichée par le score pour les commentaires Facebook. Voir `MODIFICATIONS_V11_COMMENTAIRES_PERIODE_COLLECTE.md`.
