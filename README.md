# ARMA PFA — VERSION FINALE V2

La V2 finale sépare clairement les commentaires Facebook à traiter, crée aussi des alertes pour les questions/suggestions actionnables et répare le rattachement des commentaires aux posts Serper/Marketing. Voir `MODIFICATIONS_VERSION_FINALE_V2_COMMENTAIRES_ACTIONNABLES.md`.

> **VERSION FINALE — commentaires Facebook, sentiment et alertes individuelles.**

# ARMA PFA — Veille marketing et e-réputation

Version consolidée du PFA, avec **n8n comme orchestrateur principal**, FastAPI,
PostgreSQL, Serper, NLP multilingue et API Claude. Les deux POC sont alimentés
par la base et non par des exemples figés.

## POC couverts

### POC 1 — Marketing Contenu (quotidien)

```text
Veille sectorielle qualifiée
→ dédoublonnage par événement
→ angles stratégiques
→ 8 brouillons FR/AR
→ LinkedIn, Instagram, Facebook et X
→ prompts d'images
→ validation humaine
```

### POC 2 — Réputation Sociale (hebdomadaire)

```text
Écoute ARMA + concurrents
→ sentiment FR/AR/darija
→ score /100 sur périodes non chevauchantes
→ alertes de risque
→ réponses FR/AR avec décision métier
→ benchmark concurrentiel
```

## Architecture

```text
n8n (planification + suivi visuel)
        │
        ▼
FastAPI /api/orchestration
        │
        ├─ Collecte : Serper News/Web, RSS, social indexé
        ├─ Connecteurs : Apify (commentaires Facebook publics), Meta Graph, Instagram, X API
        ├─ Traitement : normalisation, anti-bruit, langue, thèmes, dédoublonnage
        ├─ NLP : sentiment Hugging Face + compréhension/génération Claude
        ├─ Réputation : score, historique, alertes, benchmark
        └─ Marketing : angles, 8 posts FR/AR, prompts image
        │
        ▼
PostgreSQL → API REST → deux interfaces HTML
```

Les règles déterministes restent utilisées pour les contrôles sensibles :
permissions, dédoublonnage, sévérité, périodes de calcul, traçabilité et garde-fous
factuels. Claude intervient là où la compréhension contextuelle et la rédaction
apportent une valeur réelle.

## Fonctionnalités consolidées

- orchestration officielle par workflow n8n quotidien à 07:00, fuseau `Africa/Casablanca` ;
- verrou anti-double exécution et historique détaillé dans PostgreSQL ;
- comparaison hebdomadaire avec périodes adjacentes, sans chevauchement ;
- reclassification `high` et escalade interne pour paie/RH, juridique, autorités,
  conflits sociaux et marchés publics ;
- dédoublonnage sémantique léger des événements multi-sources ;
- benchmark sans score fictif lorsqu'un concurrent n'a aucune mention ;
- 8 posts répartis sur 4 plateformes, numérotation stable de 1/8 à 8/8 ;
- validation factuelle des contenus Claude, détection des promesses absolues,
  nombres/villes/technologies non étayés et fragments linguistiques incorrects ;
- gabarit de secours sûr si Claude renvoie un JSON invalide ou un contenu risqué ;
- boutons d'alertes avec statuts `acknowledged` et `resolved` ;
- contrôle qualité exposé par `/api/quality/status` ;
- interfaces mises à jour pour indiquer que n8n est l'orchestrateur principal ;
- collecte de tous les commentaires publics renvoyés par Apify pour chaque URL Facebook retenue, avec une limite configurable ;
- rattachement des commentaires au post Facebook original, y compris lorsqu’il a été découvert par Serper sous la source `facebook.com` ;
- classification de chaque commentaire utile en **positif, neutre ou négatif** ;
- prise en compte des trois classes dans le calcul du score de réputation ;
- création d’une alerte individuelle pour chaque commentaire négatif concernant ARMA ;
- génération d’un brouillon FR/AR modifiable lorsque la réponse est recommandée ;
- envoi toujours séparé et réservé à l’API Meta officielle après validation humaine.

## Installation rapide sous Windows

Prérequis : Python 3.10+, PostgreSQL, Node.js/npm.

```powershell
.\scripts\setup_project.ps1
```

Ou manuellement :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m alembic upgrade head
python -m backend.database.seed
python -m backend.database.seed_rss_sources
```

Renseigner au minimum dans `.env` :

```env
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/arma_marketing
SERPER_API_KEY=...
ANTHROPIC_API_KEY=...

SENTIMENT_PROVIDER=huggingface
COMMENT_TRIAGE_PROVIDER=claude
RESPONSE_DRAFT_PROVIDER=claude
POST_CONTENT_PROVIDER=claude
```

## Lancer la plateforme

### Terminal 1 — backend

```powershell
.\scripts\run_backend.ps1
```

### Terminal 2 — n8n

```powershell
.\scripts\run_n8n.ps1
```

Importer ensuite :

```text
n8n/workflows/ARMA_Pipeline_Quotidien_n8n.json
```

Lancer une première fois avec **Test workflow**, puis activer le workflow.

### Terminal 3 — frontend

```powershell
.\scripts\run_frontend.ps1
```

Ouvrir :

- `http://127.0.0.1:5500/MarketingContenuARMA.html`
- `http://127.0.0.1:5500/ReputationSocialeARMA.html`
- `http://127.0.0.1:8000/api/quality/status`
- `http://127.0.0.1:8000/docs`


## Configurer Apify pour les commentaires Facebook publics

Dans `.env`, ajouter :

```env
FACEBOOK_COMMENTS_PROVIDER=apify
APIFY_FACEBOOK_COMMENTS_ENABLED=true
APIFY_API_TOKEN=...
APIFY_FACEBOOK_ACTOR_ID=apify/facebook-comments-scraper
APIFY_MAX_POSTS_PER_RUN=20
APIFY_COLLECT_ALL_COMMENTS=true
APIFY_ALL_COMMENTS_LIMIT=500
APIFY_MAX_COMMENTS_PER_POST=500
APIFY_INCLUDE_REPLIES=true
APIFY_COMMENTS_MODE=Newest
APIFY_ONLY_COMMENTS_NEWER_THAN=
APIFY_RUN_TIMEOUT_SECONDS=300
FACEBOOK_REGISTRY_PRESERVE_EXISTING=true
```

Le workflow construit d’abord `data/fb.txt` depuis les posts Facebook retenus
dans les deux POC. L’étape **10 - Commentaires Facebook Apify/Meta** envoie
ensuite ces URLs à Apify, stocke les commentaires publics dans PostgreSQL, puis
les étapes suivantes classent tous les commentaires utiles en positif, neutre ou négatif.
Les trois classes participent au score et chaque commentaire négatif ARMA devient
une alerte individuelle. Les brouillons de réponse restent soumis à validation humaine. Le token Apify est lu par FastAPI depuis `.env` et n’est
jamais stocké dans le workflow n8n.

Vérifications utiles :

- `GET http://127.0.0.1:8000/api/facebook/integration/status`
- `POST http://127.0.0.1:8000/api/facebook/comments/sync`
- `GET http://127.0.0.1:8000/api/facebook/comments?limit=100`
- `GET http://127.0.0.1:8000/api/facebook/comments/summary?organization=ARMA&days=90`

Apify collecte uniquement les commentaires publiquement accessibles. Le bouton
**Envoyer la réponse** reste dépendant de Meta Graph API et d’une Page autorisée.

## Sources et limites réelles

- Serper découvre les contenus web, presse et certains posts sociaux publics indexés.
- Apify collecte les commentaires Facebook publiquement visibles des posts retenus.
  Le volume peut être inférieur au compteur Facebook lorsque certains commentaires
  ne sont pas publics. Le projet n’accède ni aux groupes privés ni aux messages privés.
- Meta Graph API reste nécessaire pour envoyer une réponse depuis une Page autorisée.
- L'intégration au portail interne ARMA est prête via FastAPI, mais le branchement
  final dépend du dépôt, de l'authentification et de l'infrastructure du portail,
  qui ne sont pas inclus dans ce package.
- Les brouillons générés ne sont jamais publiés automatiquement : une validation
  Communication/Juridique reste obligatoire.

## Documentation

- `COMMENCER_ICI.md`
- `n8n/README_N8N.md`
- `docs/APIFY_FACEBOOK_COMMENTS.md`
- `docs/ARCHITECTURE_V9_N8N.md` (historique)
- `docs/MATRICE_CONFORMITE_CAHIER_DES_CHARGES.md`
- `docs/SOURCES_ET_FREQUENCE.md`
- `docs/VALIDATION_VERSION_FINALE.txt`
- `docs/VALIDATION_V10_3_APIFY.txt` (historique)
- `docs/VALIDATION_V9.md` (historique)
- `docs/GUIDE_DEMO.md`
- `docs/API_REFERENCE.md`
- `docs/BASE_RAPPORT_PFA.md`
# Évolutions V10 — gouvernance des veilles et Meta

Les dates de publication et de collecte sont désormais distinctes. Une date de collecte n’est jamais affichée comme date de publication. La migration `a10f0c202608` ajoute provenance, fiabilité, champs d’affichage non destructifs, routage, validation manuelle et audit des réponses Facebook.

Sous Windows PowerShell :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m alembic upgrade head
python -m uvicorn backend.main:app --reload
python -m http.server 5500 --directory frontend
pytest -q
```

PostgreSQL doit être démarré et `DATABASE_URL` défini dans `.env`. Ne commitez jamais `.env`. Lancez n8n avec `scripts\run_n8n.ps1`, puis importez `n8n\workflows\ARMA_Pipeline_Quotidien_n8n.json`. Serper utilise `SERPER_API_KEY`; Claude utilise `ANTHROPIC_API_KEY`. Pour Meta, renseignez la version Graph, un token autorisé et l’identifiant de Page dans `.env` à partir des noms documentés dans `.env.example`.

Le workflow synchronise les commentaires via Apify par défaut et peut utiliser Meta lorsque les autorisations sont disponibles. Il continue sans bloquer les autres étapes si aucun collecteur n’est configuré. Il n’envoie jamais de réponse. Dans le portail, l’utilisateur modifie le brouillon, le valide, relit la confirmation exacte puis déclenche l’API Meta. Une donnée DEMO ne produit qu’une simulation locale. Voir [limites Meta](docs/META_FACEBOOK_LIMITATIONS.md) et [fiche de vérification](docs/VERIFICATION_MANUELLE_VEILLES.md).

Rollback applicatif : restaurer la sauvegarde préalable puis exécuter `python -m alembic downgrade 91c2f4a0b7de`. Sauvegarder PostgreSQL avant tout downgrade.

## Captures automatisées des posts Facebook retenus

Après la qualification, n8n reconstruit `data/fb.txt` avec les publications Facebook retenues pour le Marketing, les publications déjà associées à une alerte et les candidats réputationnels du run courant. Selenium réalise ensuite des captures publiques sans authentification et les enregistre dans `data/facebook_screenshots`.

```powershell
python scripts\export_facebook_retained_links.py
python scripts\fb_screenshot_collector.py --visible
```

Les étapes n8n `09 - Export liens Facebook retenus`, `10 - Commentaires Facebook Apify/Meta` et `18 - Captures Facebook publiques` automatisent ce processus. Voir `docs/CAPTURES_FACEBOOK_AUTOMATISEES.md`.
