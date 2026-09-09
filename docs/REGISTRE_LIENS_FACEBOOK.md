# Registre des liens Facebook retenus

Le fichier `data/fb.txt` est généré automatiquement depuis PostgreSQL. Il contient les URL publiques des publications Facebook qui sont soit affichées dans la veille Marketing, soit associées à une alerte Réputation ouverte ou reconnue.

Règles :

- un lien par ligne ;
- les lignes vides et celles commençant par `#` sont ignorées ;
- aucun token, cookie ou secret ;
- les contenus exclus manuellement sont retirés au prochain export ;
- `data/fb_registry.json` conserve les IDs de mentions, d'alertes et l'origine du lien ;
- l'inscription d'un lien ne garantit pas que Facebook affichera son contenu sans connexion.

Le pipeline n8n exécute ensuite le collecteur de captures publiques. Voir `CAPTURES_FACEBOOK_AUTOMATISEES.md`.
