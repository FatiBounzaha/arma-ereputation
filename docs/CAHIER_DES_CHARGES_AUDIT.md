# Audit de conformité au cahier des charges — V9 finale n8n

La matrice détaillée et maintenue se trouve dans :

```text
docs/MATRICE_CONFORMITE_CAHIER_DES_CHARGES.md
```

## Synthèse

La V9 réalise le socle de données attendu : collecte multi-source, PostgreSQL,
normalisation, dédoublonnage, NLP FR/arabe/darija, score historisé, benchmark,
alertes, réponses FR/AR, huit contenus marketing et API FastAPI. La planification
principale est assurée par n8n.

Les deux dépendances externes non livrables dans le code seul sont :

1. l'accès exhaustif aux commentaires de Pages Facebook externes, soumis aux
   permissions et à l'examen Meta ;
2. le branchement final dans le véritable portail interne ARMA, dont le dépôt et
   l'authentification ne sont pas fournis.

La documentation technique, le guide de démonstration et les preuves de validation
sont inclus. La rédaction académique finale du rapport reste un livrable étudiant.
