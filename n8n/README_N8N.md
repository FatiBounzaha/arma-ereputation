# Orchestration ARMA VERSION FINALE avec n8n

n8n est l'orchestrateur officiel de cette version. Les traitements métier restent
en Python ; n8n les planifie, les appelle dans l'ordre et conserve un historique
visuel de chaque exécution.

## Architecture

```text
Déclencheur manuel ou planifié (07:00)
        ↓
Préflight GET /health
        ↓
POST /api/orchestration/runs/start
        ↓
21 étapes HTTP séquentielles
        ↓
Export data/fb.txt → commentaires publics Apify → analyse
        ↓
Captures Facebook publiques
        ↓
POST /api/orchestration/runs/{id}/finish
        ↓
GET /api/quality/status
        ↓
Résumé final du workflow
```

Le workflow contient aussi les nœuds de configuration, préparation des données et
résumé ; il possède donc plus de 19 nœuds au total, mais exactement 21 étapes
métier déclarées par le backend.

## Lancement local

1. Backend :

```powershell
.\scripts\run_backend.ps1
```

2. n8n :

```powershell
.\scripts\run_n8n.ps1
```

3. Ouvrir `http://127.0.0.1:5678` et importer :

```text
n8n/workflows/ARMA_Pipeline_Quotidien_n8n.json
```

## Configuration du workflow

Ouvrir le nœud **Configuration ARMA** :

```javascript
baseUrl: 'http://127.0.0.1:8000'
orchestrationKey: ''
```

Avec Docker :

```javascript
baseUrl: 'http://host.docker.internal:8000'
```

Si `N8N_ORCHESTRATION_TOKEN` est défini dans `.env`, mettre la même valeur dans
`orchestrationKey`. Le token est envoyé dans l'en-tête
`X-ARMA-Orchestration-Key`.

## Sécurité et concurrence

- comparaison en temps constant de la clé d'orchestration ;
- refus HTTP 409 si un run n8n récent est déjà actif ;
- aucun secret Serper, Claude ou Meta n'est enregistré dans le workflow ;
- le workflow importé est inactif par défaut : il faut le tester puis l'activer.

## États possibles

- `completed` : 21 étapes exécutées sans échec ;
- `partial` : une étape a échoué ou n'a pas été exécutée ;
- un échec d'un connecteur optionnel n'empêche pas les autres traitements de
  travailler sur les données déjà stockées.

Les traces sont enregistrées dans PostgreSQL :

```text
run_type = n8n_daily_pipeline
statistics.steps = détail de chaque étape
```

## Planification

Le Schedule Trigger est configuré à 07:00 avec :

```text
Africa/Casablanca
```

N'activez pas un Planificateur Windows ou un cron en parallèle.

## n8n avec Docker

```powershell
cd n8n
docker compose up -d
```

Le volume `n8n_data` conserve les identifiants et workflows locaux. Ce dossier est
ignoré par Git.

## Diagnostic

```text
GET http://127.0.0.1:8000/api/orchestration/steps
GET http://127.0.0.1:8000/api/quality/status
GET http://127.0.0.1:8000/docs
```

Le runner Python `backend.orchestration.run_daily_pipeline` reste un secours
manuel et non le planificateur officiel de la V10.3.

La nouvelle étape **10 - Commentaires Facebook Apify/Meta** utilise les URLs exportées à l’étape 09. Le token reste dans `.env` côté FastAPI.
