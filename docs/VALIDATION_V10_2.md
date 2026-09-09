# Validation V10.2

## Contrôles exécutés

- 59 cas de test Pytest : réussis ;
- compilation Python de `backend`, `scripts`, `migrations` et `tests` : réussie ;
- validation JSON du workflow n8n : réussie ;
- correspondance entre les 21 étapes du registre FastAPI et les 21 appels n8n : réussie ;
- syntaxe JavaScript des deux interfaces : réussie avec `node --check` ;
- test du collecteur avec un `fb.txt` vide : statut `no_links`, sans lancement inutile de Chrome ;
- vérification de l'absence de `.env` et `.venv` dans la livraison finale.

## Test local encore nécessaire

Le test de bout en bout doit être exécuté sur le poste Windows avec :

- PostgreSQL démarré ;
- `.env` configuré ;
- toutes les dépendances de `requirements.txt` installées ;
- Google Chrome disponible ;
- n8n démarré.

Facebook peut afficher un mur de connexion même pour une URL publique. Ce cas est enregistré comme `login_required` et n'est pas contourné.
