# Guide de démonstration V9

## Préparation

1. Copier `.env.example` vers `.env` et renseigner PostgreSQL, Serper et Claude.
2. Exécuter `python -m alembic upgrade head`.
3. Lancer le backend avec `.\scripts\run_backend.ps1`.
4. Lancer n8n avec `.\scripts\run_n8n.ps1`.
5. Importer `n8n/workflows/ARMA_Pipeline_Quotidien_n8n.json`.
6. Cliquer sur **Test workflow** et attendre le résumé final.
7. Lancer l'interface avec `.\scripts\run_frontend.ps1`.

## Démonstration POC 1

- montrer la veille qualifiée et les événements regroupés ;
- expliquer les catégories et le score de pertinence ;
- montrer les quatre angles ;
- vérifier 8 brouillons FR/AR sur 4 plateformes ;
- montrer les hashtags séparés, le prompt image et la validation humaine ;
- expliquer le garde-fou factuel et le fallback.

## Démonstration POC 2

- expliquer le score /100 et les périodes non chevauchantes ;
- montrer l'évolution temporelle ;
- expliquer low/medium/high et les catégories de risque ;
- montrer une escalade RH/juridique/institutionnelle ;
- tester `Marquer analysé`, puis `Marquer traité` ;
- interpréter le benchmark et la ligne sans données ;
- rappeler que les commentaires externes dépendent des permissions Meta.

## Contrôle final

Ouvrir :

```text
http://127.0.0.1:8000/api/quality/status
```

Le dernier run doit être `completed` ou `partial` avec une justification explicite.
