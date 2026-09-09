# Limites de l’intégration Facebook Meta

ARMA utilise exclusivement l’API Graph officielle. L’accès dépend d’une application Meta, d’une Page administrée, d’un jeton valide, de l’examen éventuel de l’application et des permissions accordées par Meta. Ces autorisations ne garantissent pas l’accès aux commentaires de pages externes ni à toutes les publications.

Le portail n’intègre ni scraping privé, ni cookies, ni contournement d’authentification/CAPTCHA, ni API non autorisée. Sans autorisation, `/api/facebook/integration/status` retourne `permission_required`; le pipeline continue avec un avertissement et aucun commentaire réel n’est inventé.

Le mode `DEMO_FACEBOOK_COMMENTS=false` est désactivé par défaut. Toute donnée de démonstration porte `raw_payload.is_demo=true`, reste hors des statistiques réelles et ne peut jamais être envoyée à Meta.

Une réponse nécessite une plainte opérationnelle éligible, un brouillon non vide, une confirmation humaine et un token valide. Les sujets juridiques sont bloqués et escaladés. Le statut `sent` n’est enregistré qu’après réception d’un identifiant de réponse Meta.
