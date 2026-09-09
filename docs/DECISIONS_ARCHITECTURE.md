# Décision d'architecture : agents IA ou pipeline déterministe ?

## Choix retenu

Le projet utilise une architecture hybride et traçable :

1. **Agent Veille** : collecteurs Python + règles de qualification. Il gère les URLs, quotas, dates, déduplication, entités et anti-bruit. Aucun LLM n'est nécessaire pour cette partie critique.
2. **Agent Analyste** : NLP de sentiment FR/AR/darija, score et benchmark.
3. **Agent Stratège** : transforme les signaux qualifiés en angles. La V4 fournit une stratégie déterministe ; Claude peut être ajouté pour enrichir la synthèse après validation des preuves.
4. **Agent Rédacteur** : gabarits fiables par défaut ou Claude via `POST_CONTENT_PROVIDER=claude`.

## Pourquoi ne pas utiliser un agent autonome pour collecter ?

Un agent LLM ne garantit ni l'exhaustivité ni la conformité aux permissions des plateformes. Il peut aussi halluciner des sources. La collecte doit donc rester fondée sur les APIs/connecteurs, puis le LLM intervient uniquement après la qualification des données.

## Séparation des vues

- **Marketing Contenu** : actualités Serper News qualifiées uniquement par défaut.
- **Réputation Sociale** : articles, publications et commentaires liés à ARMA ; alertes et réponses uniquement pour ARMA.
- **Benchmark** : scores agrégés d'ARMA et des concurrents.
