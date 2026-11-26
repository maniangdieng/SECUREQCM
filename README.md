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

## Données de démonstration

Pour tester ou faire une démo sans vraies données :

```bash
python manage.py seed_demo                 # 1 admin, 2 enseignants, 20 étudiants, 2 classes, 3 examens
python manage.py seed_demo --reset         # repartir de zéro
python manage.py seed_demo --reset --students 200   # pour un test de charge
```

Tous les comptes commencent par `demo_` (`demo_admin`, `demo_prof1`, `demo_etu001`…), mot de passe commun
`Demo-SecureQCM-2026`. Examens publiés : codes d'accès `DEMOGL01` et `DEMOBD01`. La commande refuse de s'exécuter
avec `DJANGO_DEBUG=0` sauf `--force`.

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
