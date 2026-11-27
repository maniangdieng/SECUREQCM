# Checklist avant un examen réel

- [ ] Définir `DJANGO_SECRET_KEY` avec une valeur aléatoire longue.
- [ ] Définir un mot de passe PostgreSQL robuste.
- [ ] Configurer `DJANGO_ALLOWED_HOSTS` avec le domaine réel.
- [ ] Déployer derrière HTTPS (obligatoire).
- [ ] Configurer les cookies sécurisés et les paramètres proxy HTTPS dans Django.
- [ ] Vérifier `AXES_FAILURE_LIMIT` / `AXES_COOLOFF_MINUTES` (blocage après échecs de connexion). Derrière un reverse proxy (Caddy, nginx…), mettre `AXES_BEHIND_PROXY=1` pour que django-axes lise la vraie IP (`X-Forwarded-For`), sinon tous les étudiants partagent l'IP du proxy. **Seulement** si le port de l'application n'est pas exposé directement.
- [ ] Mettre en place sauvegardes PostgreSQL et restauration testée.
- [ ] Créer les comptes et affecter explicitement les rôles dans `/admin/`.
- [ ] Tester les parcours enseignant et étudiant.
- [ ] Tester les échéances côté serveur et les tentatives simultanées.
- [ ] Tester Windows et macOS avec les versions SEB retenues.
- [ ] Implémenter et vérifier l'authentification SEB réelle (BEK/CK) avant d'exiger SEB.
- [ ] Définir une procédure humaine pour les coupures, pannes et contestations.
- [ ] Faire un test de charge avec l'effectif maximal prévu.

Ne pas utiliser ce MVP tel quel pour un examen à fort enjeu avant audit de sécurité et validation SEB.
