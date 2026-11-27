# Secure QCM

Application web Django d'examens QCM surveillés, organisée en **classes** comme Google Classroom :
un super-administrateur, des enseignants qui créent leurs classes, des étudiants qui les rejoignent avec un code.

> Description complète, architecture, règles métier et **ce qui reste à faire** : [`docs/PROJET_ET_PERSPECTIVES.md`](docs/PROJET_ET_PERSPECTIVES.md)

## Ajouts — Ablaye Faye

- **Publication des notes** : champ `Exam.results_published`, page de fin « Copie remise » sans note tant que non publié, bouton « Publier les notes » côté enseignant.
- **Duplication d'examen** : action « Dupliquer », copie examen + questions + propositions en brouillon, même classe ou autre classe, nouveau code d'accès, aucune tentative ni affectation copiée.
- **Édition des questions** : énoncé, type, propositions, bonnes réponses, points ; réordonnancement monter/descendre ; verrous sur examen publié/tentative ; validations conservées.
- **Fenêtre d'examen** : `opens_at` / `closes_at`, saisie création/édition, message clair hors fenêtre, affichage étudiant, tentative déjà commencée poursuivie jusqu'à sa durée.
- **Migration** : `qcm/migrations/0006_exam_closes_at_exam_opens_at_exam_results_published.py`.
- **Fichier de test QCM** : `qcm_data/test_10_questions_redondance.xlsx`, 10 questions + redondance.
- **Interface professionnelle** : charte verte sobre, navbar/footer, dashboards admin/enseignant/étudiant, responsive, accessibilité, `static/css/app.css`, `static/js/app.js`, `templates/base.html`.
- **Bouton local « Règles & avertissements »** : règles de violation et avertissements, sans discussion ni envoi de données.
- **Tests** : `qcm/tests_exam_lifecycle.py`, suite `python manage.py test qcm` à 65 tests verts.

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
