"""Lance manuellement la chaîne complète des commentaires Facebook publics.

Avant le correctif, ce script ne faisait que collecter les commentaires
(Apify/Meta) sans jamais les classer ni générer d'alerte : les commentaires
apparaissaient bien dans PostgreSQL et sur GET /api/facebook/comments, mais
JAMAIS dans la section "Alertes" du portail Réputation Sociale, car une
alerte n'est créée qu'après le tri (comment_triage) d'un commentaire pertinent
nécessitant une réponse. Le script enchaîne donc désormais :

    1. collecte des commentaires (Apify ou Meta selon .env)
    2. tri intelligent des commentaires (triage_social_comments)
    3. génération des alertes (generate_alerts_for_negative_mentions)

comme le fait déjà le pipeline quotidien complet (n8n / run_daily_pipeline).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Rend le dossier racine importable lorsque ce script est lancé directement
# (ex. python scripts\sync_apify_facebook_comments.py depuis la racine, ou
# via scripts\run_apify_comments.ps1) : sans cela, Python ne place que le
# dossier scripts/ dans sys.path et "import backend..." échoue avec
# ModuleNotFoundError.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.ai.comment_triage.service import triage_social_comments
from backend.alerts.service import generate_alerts_for_negative_mentions
from backend.services.facebook_comment_collection_service import (
    collect_facebook_comments,
    comments_collection_status,
)


def main() -> int:
    status = comments_collection_status()
    print(json.dumps(status, ensure_ascii=False, indent=2, default=str))
    if not status.get("collection_available"):
        print("Collecte non configurée. Vérifiez .env.")
        return 1

    print("\n--- Étape 1/3 : collecte des commentaires Facebook ---")
    result = collect_facebook_comments()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if result.get("status") not in {"completed", "no_links"}:
        return 1

    print("\n--- Étape 2/3 : tri intelligent des commentaires ---")
    triage_result = triage_social_comments()
    print(json.dumps(triage_result, ensure_ascii=False, indent=2, default=str))

    print("\n--- Étape 3/3 : génération des alertes ---")
    alerts_result = generate_alerts_for_negative_mentions()
    print(json.dumps(alerts_result, ensure_ascii=False, indent=2, default=str))

    print(
        "\nTerminé. "
        f"{alerts_result.get('created', 0)} nouvelle(s) alerte(s) créée(s), "
        f"{triage_result.get('reply_recommended', 0)} commentaire(s) nécessitant une réponse."
    )
    print("Consultez la section 'Commentaires Facebook à traiter' du portail Réputation Sociale.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
