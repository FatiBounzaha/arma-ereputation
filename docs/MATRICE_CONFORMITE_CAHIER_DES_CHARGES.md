# Matrice de conformité au cahier des charges

Légende : ✅ réalisé · 🟡 partiel/dépendance externe · ⏳ livrable académique à compléter.

| Exigence | Statut | Implémentation V9 |
|---|---:|---|
| Collecte web et réseaux sociaux ARMA + concurrents | ✅ | Serper News/Web et recherches sociales ciblées |
| Presse marocaine | ✅ | RSS + Serper, sources configurables |
| Connecteurs sociaux officiels | 🟡 | Meta/Instagram/X présents, limités aux autorisations réellement accordées |
| Normalisation et nettoyage | ✅ | services de nettoyage et qualification |
| Dédoublonnage | ✅ | URL/external ID + regroupement d'événements multi-sources |
| Horodatage | ✅ | dates de publication, collecte, traitement et run |
| FR / arabe / darija | ✅ | détection explicite + NLP multilingue |
| Modèle de données mentions/sources/entités/scores | ✅ | PostgreSQL, SQLAlchemy, Alembic |
| Pipeline planifié | ✅ | workflow n8n quotidien, fuseau Casablanca |
| Sentiment bilingue | ✅ | modèle Hugging Face multilingue |
| Score de réputation temporel | ✅ | score versionné, périodes non chevauchantes |
| Benchmark concurrents | ✅ | volume, score, positif, delta, sujet dominant |
| POC 1 : 8 posts FR/AR | ✅ | cible 8, 4 plateformes, prompts image, validation factuelle |
| POC 2 : alertes et réponses FR/AR | ✅ | sévérité, risque, décision, réponse, escalade |
| API pour le portail | ✅ | FastAPI et documentation OpenAPI |
| Branchement au portail interne réel | 🟡 | API prête ; dépôt/authentification ARMA non fournis |
| Base alimentée en continu | ✅ | n8n quotidien + upsert/dédoublonnage |
| Documentation sources/fréquence | ✅ | `SOURCES_ET_FREQUENCE.md` |
| Démonstration fonctionnelle | ✅ | guide et deux interfaces réelles |
| Validation scientifique sur corpus annoté réel | 🟡 | code fonctionnel ; corpus métier annoté à constituer avec ARMA |
| Rapport final de PFA | ⏳ | structure et preuves techniques fournies, rédaction académique à finaliser |

## Limite Facebook externe

La collecte automatique des commentaires de Pages externes ne peut pas être
garantie par le code seul. Elle dépend de la validation et des permissions Meta.
Cette limite est rendue visible dans les logs et le contrôle qualité ; aucune donnée
fictive n'est générée pour la masquer.
