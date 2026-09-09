# Base de rapport PFA — Plateforme de veille marketing et e-réputation ARMA

Ce document fournit une structure directement réutilisable pour le rapport final.
Les résultats chiffrés doivent être actualisés après la dernière exécution n8n et
validés par l'encadrante.

## 1. Contexte et problématique

La veille sur ARMA, ses concurrents et le secteur de la propreté urbaine est
fragmentée entre presse, web et réseaux sociaux. Le projet industrialise la
collecte, l'analyse et la restitution afin de réduire le travail manuel et de
rendre les décisions traçables.

## 2. Objectifs

- automatiser l'ingestion multi-source ;
- centraliser les mentions dans PostgreSQL ;
- gérer le français, l'arabe et la darija ;
- mesurer le sentiment et la réputation dans le temps ;
- détecter les risques réputationnels ;
- proposer des réponses et contenus bilingues ;
- alimenter deux vues orientées métier ;
- orchestrer le pipeline avec n8n.

## 3. Analyse fonctionnelle

### POC Marketing

Veille qualifiée, angles stratégiques et huit brouillons adaptés à LinkedIn,
Instagram, Facebook et X.

### POC Réputation

Score /100, historique, alertes, décisions de réponse, brouillons FR/AR et
benchmark concurrents.

## 4. Architecture

Décrire le diagramme présent dans `ARCHITECTURE_V9_N8N.md` : n8n, FastAPI,
services Python, PostgreSQL, Hugging Face, Claude et interfaces.

## 5. Collecte et ingénierie des données

Présenter :

- sources et fréquences ;
- external IDs, URLs canoniques et dédoublonnage ;
- stockage brut et données qualifiées ;
- traitement des erreurs et connecteurs optionnels ;
- limites des plateformes sociales.

## 6. NLP multilingue

- détection FR/arabe/darija/mixte ;
- nettoyage ;
- classification des thèmes ;
- sentiment Hugging Face ;
- tri contextuel et génération Claude ;
- validation humaine et garde-fous factuels.

## 7. Score et benchmark

La formule V9 est :

```text
score = 50 + 50 × (positives - négatives) / total
```

Le résultat est borné entre 0 et 100. Les périodes comparées sont adjacentes et
ne se chevauchent pas. En l'absence de mentions, le portail affiche « données
insuffisantes » au lieu d'un faux score.

## 8. Orchestration n8n

Présenter le déclencheur quotidien, le préflight, les 19 étapes, les statuts
`completed/partial`, le verrou anti-concurrence et le contrôle qualité final.

## 9. Tests et validation

S'appuyer sur `VALIDATION_V9.md`. Ajouter :

- captures n8n ;
- résultats de tests ;
- exemples de mentions ;
- matrice sentiment attendu/prédit sur un corpus annoté ;
- test des boutons de statut ;
- limites et incidents observés.

## 10. Résultats

Insérer les derniers chiffres réels : nombre de mentions, score ARMA, tendance,
alertes par sévérité, classement concurrentiel, nombre de posts sûrs/fallback et
fraîcheur de collecte.

## 11. Limites

- couverture non exhaustive de l'indexation sociale ;
- permissions Meta ;
- quotas et coûts API ;
- nécessité d'un corpus darija annoté ;
- validation Communication/Juridique ;
- branchement final au portail interne.

## 12. Perspectives

- déploiement sécurisé ;
- authentification du portail ;
- webhooks Meta autorisés ;
- observabilité et alerting ;
- évaluation continue des modèles ;
- stockage documentaire si le volume le justifie ;
- human-in-the-loop et workflow d'approbation complet.
