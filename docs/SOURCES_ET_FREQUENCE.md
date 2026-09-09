# Sources, fréquence et responsabilités — V9

Le workflow n8n quotidien appelle les sources dans l'ordre suivant. Les fréquences
plus courtes indiquées ci-dessous sont des options de production ; le POC livré
utilise un déclenchement global quotidien à 07:00.

| Source | Module Python | Fréquence POC | Données | Condition |
|---|---|---:|---|---|
| Serper News | `collection_service` | quotidienne | actualités ARMA | `SERPER_API_KEY` |
| Serper Web | `web_collection_service` | quotidienne | résultats web ARMA | `SERPER_API_KEY` |
| RSS presse marocaine | `rss_collection_service` | quotidienne | articles des flux activés | flux accessibles |
| Veille stratégique | `business_intelligence_collection_service` | quotidienne | concurrents, appels d'offres, réglementation, innovation | `SERPER_API_KEY` |
| Social public indexé | `social_collection_service_v2` | quotidienne | posts Facebook/Instagram/LinkedIn/X indexés | indexation moteur |
| X API | `x_api_collection_service` | quotidienne, optionnelle | posts X récents | `X_BEARER_TOKEN` |
| Facebook commentaires | `facebook_comment_collection_service` | quotidienne, optionnelle | commentaires accessibles | permissions Meta |
| Instagram commentaires | `instagram_comment_collection_service` | quotidienne, optionnelle | compte professionnel accessible | compte Business + Meta |
| NLP et réputation | services de traitement | après collecte | langue, thèmes, sentiment, score, alertes | modèle local/Claude |
| Marketing | services de contenu | après analyse | angles et 8 brouillons FR/AR | Claude + fallback |

## Planification officielle

```text
n8n/workflows/ARMA_Pipeline_Quotidien_n8n.json
Tous les jours à 07:00 — Africa/Casablanca
```

Ne programmez pas le runner Python en parallèle. Il reste une commande de secours
pour un diagnostic manuel.
