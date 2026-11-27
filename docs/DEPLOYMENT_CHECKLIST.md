# Checklist avant un examen réel

- [ ] Définir `DJANGO_SECRET_KEY` avec une valeur aléatoire longue.
- [ ] Définir un mot de passe PostgreSQL robuste.
- [ ] Configurer `DJANGO_ALLOWED_HOSTS` avec le domaine réel.
- [ ] Déployer derrière HTTPS (obligatoire).
- [ ] Configurer les cookies sécurisés et les paramètres proxy HTTPS dans Django.
- [ ] Mettre en place sauvegardes PostgreSQL et restauration testée.
- [ ] Créer les comptes et affecter explicitement les rôles (page « Comptes » de l'application).
- [ ] Fixer la durée de session (`DJANGO_SESSION_HOURS`, 8 par défaut, 4 au minimum).
- [ ] Tester les parcours enseignant et étudiant.
- [ ] Tester les échéances côté serveur et les tentatives simultanées.
- [ ] Planifier chaque minute `python manage.py close_expired_attempts` (cron : `* * * * *`) pour clôturer les tentatives des étudiants qui ne reviennent pas.
- [ ] Tester Windows et macOS avec les versions SEB retenues.
- [ ] Implémenter et vérifier l'authentification SEB réelle (BEK/CK) avant d'exiger SEB.
- [ ] Définir une procédure humaine pour les coupures, pannes et contestations.
- [ ] Faire un test de charge avec l'effectif maximal prévu.

Ne pas utiliser ce MVP tel quel pour un examen à fort enjeu avant audit de sécurité et validation SEB.
