# Checklist avant un examen réel

- [ ] Définir `DJANGO_SECRET_KEY` avec une valeur aléatoire longue, et `DJANGO_DEBUG=0`.
- [ ] Définir un mot de passe PostgreSQL robuste, avant le premier démarrage.
- [ ] Configurer `DJANGO_ALLOWED_HOSTS` avec le domaine réel.
- [ ] Déployer derrière HTTPS (obligatoire) : [HTTPS.md](HTTPS.md).
- [ ] Mettre `DJANGO_SECURE_COOKIES=1` et `DJANGO_CSRF_TRUSTED_ORIGINS=https://…`, puis lancer `check --deploy`.
- [ ] Vérifier `AXES_FAILURE_LIMIT` / `AXES_COOLOFF_MINUTES` (blocage après échecs de connexion). Avec `docker-compose.https.yml`, `AXES_BEHIND_PROXY=1` est déjà réglé ; derrière un autre reverse proxy, le mettre aussi pour que django-axes lise la vraie IP (`X-Forwarded-For`), sinon tous les étudiants partagent l'IP du proxy. **Seulement** si le port de l'application n'est pas exposé directement.
- [ ] Planifier les sauvegardes et **essayer une restauration** : [SAUVEGARDE.md](SAUVEGARDE.md).
- [ ] Créer les comptes et affecter explicitement les rôles (page « Comptes » de l'application).
- [ ] Fixer la durée de session (`DJANGO_SESSION_HOURS`, 8 par défaut, 4 au minimum).
- [ ] Régler le nombre de processus de l'application selon l'effectif.
- [ ] Tester les parcours enseignant et étudiant.
- [ ] Tester les échéances côté serveur et les tentatives simultanées.
- [ ] Planifier chaque minute `python manage.py close_expired_attempts` (cron : `* * * * *`) pour clôturer les tentatives des étudiants qui ne reviennent pas.
- [ ] Faire les essais restants du [rapport de validation](RAPPORT_VALIDATION.md#4-reste-à-essayer) sur les appareils admis.
- [ ] Tester Windows et macOS avec les versions SEB retenues.
- [ ] Implémenter et vérifier l'authentification SEB réelle (BEK/CK) avant d'exiger SEB.
- [ ] Définir une procédure humaine pour les coupures, pannes et contestations.
- [ ] Faire un test de charge avec l'effectif maximal prévu.
- [ ] Fixer les durées de conservation, informer les personnes et accomplir les formalités : [données personnelles](DONNEES_PERSONNELLES.md).

Ne pas utiliser ce MVP tel quel pour un examen à fort enjeu avant audit de sécurité et validation SEB.
