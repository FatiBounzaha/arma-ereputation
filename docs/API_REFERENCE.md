# Référence API utile au portail ARMA

Base locale : `http://127.0.0.1:8000`

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/health` | santé du backend |
| GET | `/db-health` | disponibilité PostgreSQL sans fuite de secret |
| GET | `/api/quality/status` | contrôle qualité technique et métier |
| GET | `/api/content/recent-mentions` | veille marketing qualifiée et regroupée |
| GET | `/api/content/angles` | angles stratégiques du dernier run |
| GET | `/api/content/posts` | 8 brouillons FR/AR du dernier run |
| GET | `/api/reputation/score?organization=ARMA` | dernier score ARMA |
| GET | `/api/reputation/history?organization=ARMA` | historique non chevauchant |
| GET | `/api/reputation/benchmark` | benchmark concurrents |
| GET | `/api/alerts?organization=ARMA` | alertes ouvertes/récentes |
| GET | `/api/alerts/{id}/response` | décision et brouillon Claude |
| PATCH | `/api/alerts/{id}/status` | open/acknowledged/resolved/ignored |
| GET | `/api/orchestration/steps` | registre des 19 étapes |
| POST | `/api/orchestration/runs/start` | ouvre un run n8n |
| POST | `/api/orchestration/runs/{id}/steps/{key}` | exécute une étape |
| POST | `/api/orchestration/runs/{id}/finish` | clôture le run |

La documentation interactive complète est disponible dans `/docs`.
