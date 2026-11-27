# Secure QCM

Application web Django d'examens QCM surveillés, organisée en **classes** comme Google Classroom :
un super-administrateur, des enseignants qui créent leurs classes, des étudiants qui les rejoignent avec un code.

> Description complète, architecture, règles métier et **ce qui reste à faire** : [`docs/PROJET_ET_PERSPECTIVES.md`](docs/PROJET_ET_PERSPECTIVES.md)

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

## Tests

```bash
python manage.py test qcm
```

## Déploiement (Docker + PostgreSQL)

1. `cp .env.example .env` puis renseigner `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`.
2. `docker compose up --build`
3. `docker compose exec web python manage.py createsuperuser`

Avant un examen réel : [`docs/DEPLOYMENT_CHECKLIST.md`](docs/DEPLOYMENT_CHECKLIST.md).

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
