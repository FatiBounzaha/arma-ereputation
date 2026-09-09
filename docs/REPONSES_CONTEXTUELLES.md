# Réponses contextuelles et validation humaine

La V5 ne transforme plus automatiquement toute mention négative en réponse générique.

## Étape de décision

Avant la rédaction, le module `backend.ai.response_drafts.decision` classe l'alerte :

- `public_reply` : réclamation directe et actionnable ;
- `official_statement` : projet de communiqué ;
- `internal_escalation` : article institutionnel à transmettre à la Communication/Direction ;
- `monitor` : surveillance et vérification, sans réponse immédiate ;
- `no_reply` : bruit, spam ou contenu hors sujet.

## Diffusion

Le portail ne publie rien automatiquement. Il permet de :

- copier le texte français ou arabe ;
- ouvrir la source originale ;
- marquer l'alerte comme analysée/traitée.

Toute diffusion reste soumise à validation humaine et aux autorisations officielles de la plateforme concernée.

## Régénérer les anciens brouillons

```powershell
python -m backend.ai.response_drafts.service --replace-existing
```

Les brouillons déjà validés ou envoyés ne sont pas écrasés.
