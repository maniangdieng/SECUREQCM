# Secure QCM 2.5.2 — Inscription et accès individualisé aux examens

## 1. Création du compte étudiant

Lien à communiquer : `http://ADRESSE-DU-SERVEUR:8000/accounts/register/`

Chaque étudiant crée son compte avec son prénom, son nom, son matricule, un identifiant et un mot de passe. **Aucun code général d'inscription n'est demandé.** Le compte créé est un compte étudiant.

Après création du compte, l'étudiant se connecte à son espace. Il ne voit que les examens auxquels il a été affecté ou qu'il a rejoints avec un code d'examen valide.

## 2. Deux méthodes pour autoriser l'accès à un examen

### Affectation par fichier CSV

1. L'étudiant doit d'abord avoir créé son compte.
2. Préparez un fichier CSV avec une première ligne contenant l'en-tête `matricule`.
3. Ajoutez une ligne par étudiant, avec le matricule exactement comme dans son compte.
4. Dans l'espace enseignant, ouvrez l'examen, puis importez ce fichier dans « Affecter une liste d'étudiants ».
5. Seuls les comptes dont le matricule correspond sont affectés.

Exemple :

```csv
matricule
UASZ2026001
UASZ2026002
UASZ2026003
```

### Accès par code propre à l'examen

Chaque examen reçoit automatiquement un code unique, affiché dans sa page de gestion. Après publication, l'enseignant communique ce code uniquement aux étudiants concernés. L'étudiant se connecte, saisit le code dans son tableau de bord, puis l'examen apparaît dans sa liste.

## 3. Règles de sécurité

- Il n'existe pas de code général d'inscription.
- Les comptes créés par le formulaire public ont le rôle étudiant.
- Un étudiant ne voit que les examens auxquels il a été affecté par CSV ou qu'il a rejoints avec le code propre à cet examen.
- Le serveur vérifie également l'autorisation au démarrage de l'épreuve.
- Un code d'examen ne fonctionne que pour un examen publié.
- L'affectation par CSV et l'accès par code peuvent être utilisés simultanément pour un même examen.
- Le code d'un examen doit être communiqué uniquement aux étudiants concernés.

## 4. Mise à jour depuis une version précédente

Conservez une copie de votre base `db.sqlite3`. Remplacez les fichiers de l'application sans remplacer cette base. Activez l'environnement virtuel et exécutez :

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py check
python manage.py test
python manage.py runserver 0.0.0.0:8000
```

### Affectation par niveau
À l'inscription, l'étudiant choisit son niveau d'études. Les examens publiés en mode « Tous les étudiants du niveau » apparaissent automatiquement dans son espace. Chaque étudiant doit néanmoins saisir le code propre à l'examen pour pouvoir le démarrer.
