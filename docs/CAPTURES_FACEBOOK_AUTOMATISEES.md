# Captures Facebook automatisées — V10.3

## Objectif

Le projet conserve une preuve visuelle des **publications Facebook publiques** qui ont été retenues dans l'un des deux POC :

- veille Marketing (`display_in_marketing = true`) ;
- alerte Réputation encore ouverte ou reconnue.

Les commentaires enfants ne sont pas utilisés comme cible de capture : le script ouvre la publication Facebook parente.

## Chaîne automatisée

```text
Collecte et qualification
→ export des liens retenus dans data/fb.txt
→ collecte des commentaires publics via Apify
→ analyse, score et création des alertes
→ Selenium ouvre chaque page publique
→ captures dans data/facebook_screenshots
→ manifest.json + summary.json
→ affichage d'un lien vers la capture dans les deux POC
```

Dans n8n, les étapes sont :

```text
09 - Export liens Facebook retenus
18 - Captures Facebook publiques
```

L’export est effectué avant la collecte Apify ; les captures sont réalisées après la création des alertes et avant les brouillons de réponse.

## Fichiers produits

- `data/fb.txt` : un lien public par ligne ;
- `data/fb_registry.json` : mention IDs, alert IDs et origine Marketing/Réputation ;
- `data/facebook_screenshots/run_.../` : captures et manifests ;
- `data/facebook_screenshots/latest_run.json` : résumé du dernier run.

Les captures sont accessibles depuis FastAPI sous :

```text
http://127.0.0.1:8000/artifacts/facebook-screenshots/...
```

## Lancement manuel

```powershell
python scripts\export_facebook_retained_links.py
python scripts\fb_screenshot_collector.py --visible
```

Ou :

```powershell
.\scripts\run_facebook_screenshots.ps1
```

Le mode `--visible` sert au diagnostic. n8n utilise le mode invisible par défaut.

## API

```text
GET  /api/facebook-screenshots/status
POST /api/facebook-screenshots/export-links
POST /api/facebook-screenshots/capture
```

## Configuration `.env`

```env
FACEBOOK_SCREENSHOT_ENABLED=true
FACEBOOK_SCREENSHOT_VISIBLE=false
FACEBOOK_SCREENSHOT_SCROLLS=8
FACEBOOK_SCREENSHOT_PAUSE_SECONDS=2.0
FACEBOOK_SCREENSHOT_MAX_LINKS=20
FACEBOOK_SCREENSHOT_KEEP_RUNS=10
```

## Limites et conformité

- seules les pages publiques sont ouvertes ;
- aucun compte, cookie importé, mot de passe ou CAPTCHA n'est contourné ;
- Facebook peut afficher un mur de connexion ou rendre le contenu indisponible ;
- dans ce cas, le run est marqué `login_required` ou `unavailable` ;
- une capture est une preuve visuelle, pas une extraction structurée de commentaires ;
- l'envoi d'une réponse reste réservé à l'API Meta officielle et à une validation humaine.
