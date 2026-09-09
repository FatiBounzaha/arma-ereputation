# Validation technique V9

## Contrôles automatisés

Résultat de la livraison : **35 tests réussis**. La sortie exacte est conservée dans `docs/RESULTATS_TESTS_V9.txt`.

La livraison est validée par :

```powershell
python -m compileall -q backend
python -m pytest -q
```

Les tests couvrent :

- distribution des 8 posts sur 4 plateformes ;
- validation factuelle et corrections linguistiques ;
- dédoublonnage de contenus ;
- pertinence métier et règles sociales ;
- détection FR/arabe/darija ;
- périodes de score non chevauchantes ;
- sévérité paie/RH, juridique et opérationnelle ;
- décisions de réponse ;
- tri des commentaires ;
- cohérence du workflow n8n ;
- absence de l'ancien message d'orchestration Python dans les interfaces.

## Tests de démonstration manuels

1. Exécuter le workflow n8n.
2. Vérifier `/api/quality/status`.
3. Contrôler 8 brouillons dans le POC Marketing.
4. Vérifier que les périodes actuelle/précédente ne se chevauchent pas.
5. Cliquer sur `Marquer analysé`, recharger et vérifier le statut.
6. Cliquer sur `Marquer traité` sur une alerte de test autorisée.
7. Ouvrir les sources originales avant toute validation de contenu.

## Critères de réussite

- aucun secret dans le dépôt ;
- aucune donnée POC fictive de commentaire ;
- run n8n traçable ;
- score calculé uniquement avec les mentions qualifiées ;
- zéro score concurrent affiché lorsque le volume est nul ;
- brouillons Claude marqués comme nécessitant une validation humaine ;
- fallback explicite lorsque Claude ne fournit pas un contenu sûr.
