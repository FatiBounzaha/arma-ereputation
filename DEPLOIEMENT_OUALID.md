# Déploiement e-réputation ARMA — Runbook Oualid

Backend **FastAPI + PostgreSQL** (social-listening ARMA) + 2 dashboards + orchestration n8n hebdomadaire (lundi 7h). Testé et fonctionnel en local (238→420 mentions réelles, 225 commentaires Facebook, 50 alertes). Ce guide = mise en production serveur.

> Les scripts fournis dans `scripts/*.ps1` sont **Windows**. Ci-dessous les équivalents **Linux** (serveur ARMA type Ubuntu/Debian).

---

## 0. Prérequis serveur
- **Python 3.12** (`python3.12 --version`) + `python3.12-venv`.
- **PostgreSQL 14+** (18 en local, ≥14 suffit).
- ~1 Go d'espace (sentiment via **Claude** par défaut → `torch`/`transformers` **NON requis** ; ne les installer que si `SENTIMENT_PROVIDER=huggingface`).
- Sortie internet vers `serper.dev`, `api.apify.com`, `api.anthropic.com`.
- (Optionnel) **Google Chrome + chromedriver** seulement si on active les captures d'écran Facebook (`FACEBOOK_SCREENSHOT_ENABLED=true`, désactivé par défaut).

---

## 1. PostgreSQL sur le serveur  ← (ta question)

Exactement ce qu'on a fait en local, en ligne de commande cette fois :

```bash
sudo apt update && sudo apt install -y postgresql
sudo -u postgres psql <<'SQL'
CREATE ROLE arma_user LOGIN PASSWORD 'CHANGER_CE_MOT_DE_PASSE';
CREATE DATABASE arma_marketing OWNER arma_user;
\c arma_marketing
GRANT ALL ON SCHEMA public TO arma_user;
ALTER SCHEMA public OWNER TO arma_user;
SQL
```

- **`arma_user` doit être PROPRIÉTAIRE** de la base ET du schéma `public` (sinon Alembic ne peut pas créer les tables — c'est l'erreur « droit refusé » qu'on a eue).
- Choisis un vrai mot de passe et reporte-le dans `DATABASE_URL` du `.env` (étape 3).
- Postgres reste **local au serveur** (`localhost:5432`) — pas exposé au réseau. Si le backend tourne sur une autre machine que Postgres, ouvre le port 5432 uniquement entre ces deux hôtes et adapte l'hôte dans `DATABASE_URL`.

Test connexion : `psql "postgresql://arma_user:MDP@localhost:5432/arma_marketing" -c "select 1"`.

---

## 2. Code + environnement Python

```bash
cd /opt   # ou /var/www
git clone <repo-arma-ereputation> arma-ereputation && cd arma-ereputation
python3.12 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

⚠️ **IMPORTANT — wheels compilés** : selon le cache pip du serveur, `psycopg`, `pydantic-core`, `anthropic`/`jiter` peuvent s'installer cassés (on a eu `No module named 'psycopg_c'`, `pydantic_core._pydantic_core`, `jiter.jiter`). Si le backend refuse de démarrer avec ce type d'erreur, corrige d'un coup :

```bash
pip install --force-reinstall --no-cache-dir "psycopg[binary]" pydantic pydantic-core anthropic jiter
```

Vérif : `python -c "import backend.main; print('OK')"` doit afficher `OK`.

---

## 3. Fichier `.env`

Copier `.env.example` → `.env` et renseigner. **Ne jamais committer `.env`** (déjà dans `.gitignore`). Les valeurs réelles des clés te seront données par Fatima (hors git). Points clés :

```env
DATABASE_URL=postgresql+psycopg://arma_user:MDP@localhost:5432/arma_marketing

SERPER_API_KEY=<clé fournie>          # rechargée 2026-09-09, OK
ANTHROPIC_API_KEY=<clé fournie>        # ⚠️ crédits à recharger (voir §8)
APIFY_API_TOKEN=<clé fournie>          # OK (commentaires Facebook)

SENTIMENT_PROVIDER=claude
COMMENT_TRIAGE_PROVIDER=claude
RESPONSE_DRAFT_PROVIDER=claude
POST_CONTENT_PROVIDER=claude

# Collecte incrémentale : repère glissant automatique (ne re-scrape jamais
# l'historique ; chaque run ne prend que les nouveaux commentaires).
APIFY_ONLY_COMMENTS_NEWER_THAN=auto

# Origines autorisées pour les dashboards (adapter à l'URL réelle servie).
CORS_ORIGINS=https://ereputation.arma.local,http://127.0.0.1:5500

# Jeton partagé quand l'API d'orchestration est exposée sur le réseau.
N8N_ORCHESTRATION_TOKEN=<générer une longue valeur aléatoire>
```

---

## 4. Base : migrations + données de référence

```bash
. .venv/bin/activate
python -m alembic upgrade head
python -m backend.database.seed
python -m backend.database.seed_rss_sources
```

→ crée ~20 tables + les organisations (ARMA + concurrents), thèmes, sources RSS et requêtes de veille.

---

## 5. Backend en service (systemd)

`/etc/systemd/system/arma-ereputation.service` :

```ini
[Unit]
Description=ARMA e-reputation API (FastAPI)
After=network.target postgresql.service

[Service]
User=arma
WorkingDirectory=/opt/arma-ereputation
EnvironmentFile=/opt/arma-ereputation/.env
ExecStart=/opt/arma-ereputation/.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now arma-ereputation
curl http://127.0.0.1:8000/health        # {"status":"ok",...}
curl http://127.0.0.1:8000/db-health      # {"status":"ok","database":"connected"}
```

---

## 6. Intégration portail (les 2 dashboards DANS portal.arma.ma) — FAIT

Les 2 dashboards s'affichent directement dans le portail, sous **Marketing & Communication** (modules `mc-reputation` « Réputation Sociale ARMA » et `mc-contenu` « Marketing Contenu ARMA », qui existent déjà). Plus besoin de nginx dédié ni de CORS : **le portail sert les dashboards (iframe) et proxifie leurs appels API vers ce backend interne, sous l'auth du portail.**

Côté **repo portail** (`arma-ai-backend`), branche **`feat/ereputation-dashboards`** (basée sur `main`) déjà préparée :
- `PortalController` : sert le dashboard live pour ces 2 modules + route proxy authentifiée `ereputation.api`.
- `routes/web.php` : `/ereputation-api/{path}` (GET/POST/PATCH…) → relaie vers le backend.
- `config/services.php` : `ereputation.url` / `ereputation.token`.
- `bootstrap/app.php` : `/ereputation-api/*` exempté de CSRF (POST/PATCH du dashboard).
- `resources/ereputation/*.html` : les 2 dashboards embarqués.

**Déploiement portail (comme les autres features) :**
```bash
cd /var/www/portal.arma.ma
git fetch && git checkout feat/ereputation-dashboards   # (ou merge dans main puis pull)
# .env du PORTAIL : pointer vers ce backend interne
#   EREPUTATION_API_URL=http://<hote-backend>:8000
#   EREPUTATION_API_TOKEN=<même valeur que N8N_ORCHESTRATION_TOKEN du backend, si défini>
composer install --no-dev -o
npm ci && npm run build
php artisan migrate --force        # (les modules mc-* existent déjà via ModuleSeeder)
php artisan optimize:clear && php artisan config:cache && php artisan route:cache
sudo systemctl restart php8.3-fpm  # opcache : sinon les changements contrôleur/route ne prennent pas
```

> Résultat : dans le portail, cliquer sur **Réputation Sociale ARMA** ou **Marketing Contenu ARMA** affiche le tableau de bord temps réel (score, alertes, commentaires FB, veille). Le badge « Bientôt » disparaît. L'API FastAPI reste **interne** (jamais exposée) ; seul le portail authentifié y accède.

---

## 7. Orchestration n8n (hebdo, lundi 7h)

Sur le n8n existant (conteneur Docker `192.168.1.41`) :
1. Importer `n8n/workflows/ARMA_Pipeline_Quotidien_n8n.json`.
2. Nœud **« Configuration ARMA »** : `baseUrl` = URL du backend (`http://<hôte-backend>:8000` ou `http://host.docker.internal:8000` si même hôte que n8n) ; `orchestrationKey` = la valeur de `N8N_ORCHESTRATION_TOKEN`.
3. **Test workflow** → dernier nœud `completed`. Puis **Activer** (planifié lundi 07:00 Africa/Casablanca, rapporte la semaine civile précédente).

Le workflow ne fait que piloter le backend en HTTP (21 étapes) — aucun Python côté n8n.

---

## 8. À savoir / crédits externes
- **Serper** : rechargée le 2026-09-09, fonctionne (veille news/web/social).
- **Apify** : fonctionne (commentaires Facebook). Collecte incrémentale via `auto` (§3).
- **Anthropic (Claude)** : ⚠️ **crédits épuisés** → le triage bascule automatiquement sur des règles et les posts sur des templates (le système ne plante pas), mais **la génération des angles + posts marketing et le triage fin ne reviendront qu'après recharge** sur console.anthropic.com.
- **Premier run** : garder `APIFY_ONLY_COMMENTS_NEWER_THAN=auto` — le 1er run construit l'historique, les suivants sont incrémentaux.
- **Sécurité** : l'API FastAPI n'a pas d'auth propre → la garder **interne** (derrière nginx/pare-feu), l'auth utilisateur sera portée par le portail à l'intégration.

---

## 9. Vérification post-déploiement
```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/quality/status
curl "http://127.0.0.1:8000/api/reputation/periods?organization=ARMA"
```
Puis lancer un run (via n8n **Test workflow**, ou manuellement `python -m backend.orchestration.run_daily_pipeline`) et recharger les dashboards.
