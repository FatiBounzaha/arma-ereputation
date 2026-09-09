# Architecture technique V9 — n8n + FastAPI + PostgreSQL

## 1. Principes

La plateforme sépare clairement :

- **orchestration** : n8n ;
- **traitement métier** : services Python ;
- **stockage et traçabilité** : PostgreSQL/SQLAlchemy/Alembic ;
- **API d'intégration** : FastAPI ;
- **NLP** : Hugging Face et Claude ;
- **restitution** : POC Marketing et POC Réputation.

## 2. Flux quotidien

```text
Schedule Trigger n8n
  → collecte Serper News/Web
  → RSS presse marocaine
  → veille stratégique
  → découverte sociale indexée
  → connecteurs officiels disponibles
  → tri des commentaires avec Claude
  → qualification/anti-bruit
  → nettoyage et langue FR/AR/darija
  → thèmes
  → sentiment Hugging Face
  → score et historique
  → alertes et risque métier
  → décisions/réponses Claude
  → angles stratégiques
  → 8 posts bilingues contrôlés
  → qualité finale
```

## 3. Pourquoi une architecture hybride

Claude n'est pas utilisé pour tout. Les tâches qui exigent reproductibilité,
contrôle ou sécurité restent déterministes :

- dédoublonnage ;
- calcul du score ;
- bornes des périodes ;
- sévérité minimale de certains risques ;
- permissions sociales ;
- statuts et traçabilité ;
- validation factuelle des brouillons.

Claude est utilisé pour :

- comprendre si un commentaire est utile ;
- recommander une action contextuelle ;
- rédiger les réponses FR/AR ;
- rédiger les posts par plateforme.

## 4. Modèle de données

Les tables couvrent notamment :

- organisations et concurrents ;
- sources et requêtes de veille ;
- mentions, publications et commentaires ;
- association mention–organisation ;
- analyses NLP et thèmes ;
- snapshots de réputation ;
- alertes et brouillons de réponse ;
- angles et posts générés ;
- exécutions de pipeline.

Les données brutes restent conservées. La déduplication de restitution regroupe
les événements sans supprimer la traçabilité des sources originales.

## 5. Résilience

- un connecteur optionnel en échec produit un run `partial` ;
- les étapes suivantes continuent sur les données disponibles ;
- les générations Claude invalides sont retentées ;
- un fournisseur template sert de fallback ;
- le contrôle qualité signale les données anciennes, les étapes en échec, les
  posts manquants et les connecteurs absents.

## 6. Sécurité

- `.env` ignoré par Git ;
- aucune clé dans le workflow n8n ;
- en-tête n8n optionnel protégé par `N8N_ORCHESTRATION_TOKEN` ;
- CORS limité aux origines configurées ;
- aucun détail de connexion PostgreSQL exposé par `/db-health` ;
- publication sociale automatique désactivée : validation humaine obligatoire.
