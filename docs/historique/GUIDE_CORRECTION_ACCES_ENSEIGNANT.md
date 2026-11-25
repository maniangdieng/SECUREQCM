# Secure QCM 2.1 — correction de l'accès enseignant

## Correction incluse

- Les comptes Django `is_staff=True` et les superutilisateurs sont reconnus comme administrateurs par l'application et peuvent accéder à l'espace enseignant.
- Les comptes non-staff continuent d'utiliser le rôle de leur profil (`TEACHER`, `STUDENT` ou `ADMIN`).
- La page Profils de l'administration Django affiche maintenant le rôle et permet de le modifier directement.
- L'adresse IP locale `192.168.1.12` est autorisée dans `ALLOWED_HOSTS` et `CSRF_TRUSTED_ORIGINS`.

## Accès enseignant

Depuis le même réseau Wi-Fi que le Mac :
- http://192.168.1.12:8000/dashboard/teacher/

L'utilisateur doit être connecté. Les comptes staff/superutilisateur ont accès automatiquement. Pour un compte enseignant ordinaire, ouvrir l'administration Django, aller dans **Profiles / Profils**, puis sélectionner `TEACHER` dans la colonne Rôle et enregistrer.

## Si le compte affiche encore « Accès réservé aux enseignants »

Dans le Terminal :

```bash
cd ~/Documents/secure_qcm_app
source venv/bin/activate
python manage.py shell
```

Puis, en remplaçant le nom d'utilisateur :

```python
from django.contrib.auth import get_user_model
from qcm.models import Profile

User = get_user_model()
user = User.objects.get(username="IDENTIFIANT")
profile, _ = Profile.objects.get_or_create(user=user)
profile.role = "TEACHER"
profile.save()
exit()
```

Redémarrer ensuite le serveur Django et se reconnecter.

## Installation de cette version

1. Sauvegarder le dossier actuel et `db.sqlite3`.
2. Décompresser cette archive complète.
3. Remplacer les fichiers du projet par ceux de l'archive.
4. Conserver la base `db.sqlite3` actuelle si elle contient les comptes, examens ou résultats à garder.
5. Exécuter :

```bash
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py check
python manage.py test
python manage.py runserver 0.0.0.0:8000
```

Les fonctions de suppression des questions à l'importation et de répartition du temps par question de la version 2.1 sont conservées.
