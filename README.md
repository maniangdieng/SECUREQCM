# Secure QCM

Application web Django d'examens QCM surveillés, organisée en **classes** comme Google Classroom :
un super-administrateur, des enseignants qui créent leurs classes, des étudiants qui les rejoignent avec un code.

> Description complète, architecture, règles métier et **ce qui reste à faire** : [`docs/PROJET_ET_PERSPECTIVES.md`](docs/PROJET_ET_PERSPECTIVES.md)

## Ajouts — Ablaye Faye

- **Publication des notes** : champ `Exam.results_published`, page de fin « Copie remise » sans note tant que non publié, bouton « Publier les notes » côté enseignant.
- **Duplication d'examen** : action « Dupliquer », copie examen + questions + propositions en brouillon, même classe ou autre classe, nouveau code d'accès, aucune tentative ni affectation copiée.
- **Édition des questions** : énoncé, type, propositions, bonnes réponses, points ; réordonnancement monter/descendre ; verrous sur examen publié/tentative ; validations conservées.
- **Fenêtre d'examen** : `opens_at` / `closes_at`, saisie création/édition, message clair hors fenêtre, affichage étudiant, tentative déjà commencée poursuivie jusqu'à sa durée. Une seule règle (`Exam.window_state`) pour la fenêtre et la clôture manuelle (`closed_at`) ; le code d'accès peut être validé avant l'ouverture.
- **Migration** : `qcm/migrations/0010_exam_window_results.py` (les examens existants gardent leurs notes visibles).
- **Fichier de test QCM** : `qcm_data/test_10_questions_redondance.xlsx`, 10 questions + redondance.
- **Tests** : `qcm/tests_exam_lifecycle.py`.

## Démarrage rapide (développement)

```bash
python -m venv venv
# Windows : venv\Scripts\activate    —    macOS/Linux : source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser      # devient le super-administrateur
python manage.py runserver
```

Ouvrir http://127.0.0.1:8000/. La base `db.sqlite3` est créée localement et **n'est jamais versionnée** (voir `.gitignore`).

Accès depuis d'autres machines du réseau local :

```bash
# Windows PowerShell : $env:DJANGO_ALLOWED_HOSTS="192.168.1.12,localhost"; $env:DJANGO_CSRF_TRUSTED_ORIGINS="http://192.168.1.12:8000"
export DJANGO_ALLOWED_HOSTS=192.168.1.12,localhost
export DJANGO_CSRF_TRUSTED_ORIGINS=http://192.168.1.12:8000
python manage.py runserver 0.0.0.0:8000
```

## Données de démonstration

Pour tester ou faire une démo sans vraies données :

```bash
python manage.py seed_demo                 # 1 admin, 2 enseignants, 20 étudiants, 2 classes, 3 examens
python manage.py seed_demo --reset         # repartir de zéro
python manage.py seed_demo --reset --students 200   # pour un test de charge
```

Tous les comptes commencent par `demo_` (`demo_admin`, `demo_prof1`, `demo_etu001`…), mot de passe commun
`Demo-SecureQCM-2026`. Examens publiés : codes d'accès `DEMOGL01` et `DEMOBD01`. La commande refuse de s'exécuter
avec `DJANGO_DEBUG=0` sauf `--force`. `--reset` ne supprime que les comptes créés par la commande
(identifiant `demo_…` **et** e-mail `<identifiant>@demo.invalid`) : un vrai compte dont l'identifiant commence par
`demo_` n'est jamais touché.

> ⚠️ `demo_admin` est administrateur avec un mot de passe connu : ne jamais laisser les données de démo sur le
> serveur d'un vrai examen.

## Tests

```bash
python manage.py test qcm
```

## Qualité du code

La CI (GitHub Actions) lance à chaque push et pull request : `ruff check .`, `python manage.py check`,
la vérification des migrations oubliées et `python manage.py test qcm`. Une PR ne doit pas être fusionnée si la CI est rouge.

En local, avant de pousser :

```bash
pip install ruff pre-commit
pre-commit install        # une seule fois : ruff tournera à chaque commit
ruff check .              # ou à la main
```

Si vous modifiez `models.py`, versionnez la migration générée (`python manage.py makemigrations`), sinon la CI échoue.

## Déploiement (Docker + PostgreSQL)

1. `cp .env.example .env` puis renseigner `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`.
2. `docker compose up --build`
3. `docker compose exec web python manage.py createsuperuser`

Ces étapes servent la page en HTTP sur le port 8000 : pour de vrais utilisateurs, ajouter [HTTPS](docs/HTTPS.md).

Avant un examen réel : [`docs/DEPLOYMENT_CHECKLIST.md`](docs/DEPLOYMENT_CHECKLIST.md).

## Documentation

| Pour qui | Document |
|---|---|
| Administrateur | [Guide](docs/GUIDE_ADMINISTRATEUR.md) · [HTTPS](docs/HTTPS.md) · [Sauvegarde et restauration](docs/SAUVEGARDE.md) |
| Enseignant | [Guide](docs/GUIDE_ENSEIGNANT.md) |
| Étudiant | [Guide](docs/GUIDE_ETUDIANT.md) |
| Équipe technique | [Documentation technique](docs/DOCUMENTATION_TECHNIQUE.md) · [Rapport de validation](docs/RAPPORT_VALIDATION.md) |
| Établissement | [Données personnelles](docs/DONNEES_PERSONNELLES.md) |

## Parcours en bref

| Rôle | Ce qu'il fait |
|---|---|
| **Super-admin** (`createsuperuser`) | Tout, y compris nommer des administrateurs |
| **Admin** | Attribue le rôle enseignant, gère classes et cycle de vie des examens (archivage / suppression) |
| **Enseignant** | Crée ses classes, invite des co-enseignants, crée/importe des QCM, publie, consulte les résultats |
| **Étudiant** | S'inscrit, rejoint ses classes par code, saisit le code d'examen, passe l'épreuve |

## Limites de sécurité

Un navigateur ordinaire ne peut pas verrouiller le poste. La détection (plein écran, changement d'onglet) est
indicative et peut produire des faux positifs. Pour un examen à fort enjeu, intégrer Safe Exam Browser (voir perspectives).

## Règles de contribution

- Une branche par issue, puis une PR vers `main` (« Closes #N ») ; `main` est protégée : **PR et approbation d'un autre membre obligatoires**.
- **Chaque commit est signé de son auteur humain** : configurez `git config user.name` et `git config user.email` avec votre compte GitHub.
  Aucun outil (assistant de code, générateur…) ne doit apparaître comme auteur, committer ou co-auteur :
  pas de ligne `Co-Authored-By` ni de mention d'outil dans les commits et les PR. La CI le vérifie (`attribution.yml`)
  et le réglage partagé `.claude/settings.json` désactive ces mentions pour ceux qui utilisent Claude Code.
- Jamais de vraies données dans le dépôt (`db.sqlite3`, `.env`, exports).
