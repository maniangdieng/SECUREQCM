# Documentation technique

Contexte, règles métier et reste à faire : [PROJET_ET_PERSPECTIVES.md](PROJET_ET_PERSPECTIVES.md).

## Pile

Django 5 (rendu côté serveur, un peu de JavaScript sans bibliothèque), SQLite en développement, PostgreSQL 16 et
Gunicorn en production (Docker Compose), fichiers statiques servis par WhiteNoise, Caddy pour [HTTPS](HTTPS.md).
Import et export : `pypdf`, `python-docx`, `openpyxl`. Dépendances : [`requirements.txt`](../requirements.txt).

## Organisation du code

```text
secureqcm/            réglages et URL du projet
qcm/
  models.py           données
  permissions.py      toutes les règles d'accès
  services.py         logique partagée : inscriptions, échéances, notation, résultats, journal
  forms.py            création de compte
  importers.py        lecture des sujets (PDF, Word, Excel)
  views/              admin, auth, classrooms, teacher, imports, student, attempts, results, common
  management/commands close_expired_attempts, import_qcm
  migrations/
  tests*.py
templates/            pages HTML ; le script de passation est dans qcm/take_exam.html
static/               css/app.css, js/app.js
deploy/               Caddyfile, sauvegarde.sh
```

Deux règles d'équipe : les contrôles d'accès vont dans `permissions.py`, la logique partagée dans `services.py`.

## Modèle de données

```text
User ─ Profile (rôle, matricule, niveau)
Classroom (propriétaire) ─ ClassroomMembership (enseignant | étudiant)
Exam (enseignant, classe facultative) ─ Question ─ Option
Exam ─ ExamEnrollment (étudiant, origine, code validé)
Exam ─ Attempt (étudiant) ─ Response
                          └ SecurityEvent
AuditLog (qui, quoi, sur quel objet)
```

- Suppressions protégées (`PROTECT`) : un enseignant ou un propriétaire de classe avec des objets, une classe avec des
  examens, un examen ou un étudiant avec des copies, une question avec des réponses.
- Une seule tentative **en cours** par étudiant et par examen (contrainte `uniq_attempt_in_progress`).
- `Attempt.grading_snapshot` fige le barème au démarrage : une copie est toujours notée avec les règles de son départ.
- `Response` est unique par tentative et par question ; les choix sont stockés en JSON.

## Rôles et accès

| Rôle | Détermination |
|---|---|
| Super-administrateur | `is_superuser` |
| Administrateur | `is_staff` ou rôle `ADMIN` du profil |
| Enseignant | rôle `TEACHER` |
| Étudiant | rôle `STUDENT` (par défaut) |

Un examen est géré par l'administration, son auteur, ou le propriétaire et les enseignants de sa classe
(`can_manage_exam`) ; les mêmes personnes peuvent autoriser une reprise. La connexion est unique pour tous les rôles
et ignore le paramètre `?next=` : après connexion, chacun arrive sur son tableau de bord.

## Passation d'un examen

1. `start_exam` : consignes, puis création de la tentative (ordre des questions et réponses, barème, échéances).
2. `take_exam` : la page reçoit l'état en JSON ; les échanges suivants passent par `fetch()` sans rechargement.

| Route (`/attempt/<id>/…`) | Rôle | Réponses particulières |
|---|---|---|
| `answer.json` | valide la question et avance | 409 si la copie est close |
| `save.json` | sauvegarde la sélection sans avancer | 409 si la question a changé |
| `event/` | violation ou information | doublon ignoré sous 3 s |

Ces trois routes répondent 401 si la session a expiré. Elles exigent le jeton CSRF et le propriétaire de la copie.

Principes à conserver :

- **Le serveur seul compte le temps.** Échéance globale et échéance par question ; `apply_deadlines` les applique.
- **Toute modification d'une tentative se fait sous verrou** (`services.locked_attempts`, `select_for_update`).
  SQLite ignore ce verrou et utilise des transactions `IMMEDIATE` : tester la concurrence sur PostgreSQL.
- Une réponse visant une autre question que la question courante est ignorée.
- Statuts : en cours, terminée, temps écoulé, clôturée pour sécurité, interrompue.
- Violations comptées : changement d'onglet, sortie du plein écran, perte de focus de plus de 2 secondes ; la 2e
  clôture. Pertes de focus plus brèves et redimensionnements sont seulement journalisés. Tout cela vient du navigateur et peut être contourné.

## Notation et résultats

`calculate_score` (par question), `grade_summary` (par copie, note sur 20), `result_rows` (21 colonnes communes aux
exports), `question_stats` (analyse par question). Les statistiques portent sur les copies terminées, au temps écoulé
ou clôturées pour sécurité. Seuil de réussite : 10/20.

## Configuration

Variables d'environnement (voir [`.env.example`](../.env.example)) :

| Variable | Effet | Défaut |
|---|---|---|
| `DJANGO_DEBUG` | `0` en production | `1` |
| `DJANGO_SECRET_KEY` | obligatoire si `DJANGO_DEBUG=0` | aucun |
| `DJANGO_ALLOWED_HOSTS` | noms et adresses acceptés, séparés par des virgules | `localhost,127.0.0.1` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | origines `https://…` de confiance | vide |
| `DJANGO_SECURE_COOKIES` | `1` derrière HTTPS | `0` |
| `DJANGO_SESSION_HOURS` | inactivité avant déconnexion (minimum 4) | `8` |
| `POSTGRES_HOST` | présent : PostgreSQL ; absent : SQLite | absent |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT` | connexion PostgreSQL | port `5432` |
| `COMPOSE_FILE`, `SITE_ADDRESS`, `HTTPS_PORT`, `HTTP_PORT` | HTTPS, voir [HTTPS.md](HTTPS.md) | |
| `GUNICORN_WORKERS` | nombre de processus Gunicorn (≈ 2 × cœurs + 1) | `3` |
| `GUNICORN_CMD_ARGS` | autres options Gunicorn ; `--workers` y est ignoré (la commande l'emporte) | |

Après fusion de la PR #31, pour l'envoi d'e-mails : `DJANGO_EMAIL_BACKEND` (par défaut la console, qui écrit le lien
de réinitialisation dans les journaux : **développement uniquement**), `DJANGO_EMAIL_HOST`, `DJANGO_EMAIL_PORT`,
`DJANGO_EMAIL_HOST_USER`, `DJANGO_EMAIL_HOST_PASSWORD`, `DJANGO_EMAIL_USE_TLS`, `DJANGO_DEFAULT_FROM_EMAIL`.

## Commandes

```bash
python manage.py close_expired_attempts      # à planifier chaque minute
python manage.py import_qcm --help           # import d'un sujet JSON en ligne de commande
```

`import_qcm` a son **propre format JSON**, différent de celui de l'import web de la PR #36 : chaque question a un
`number`, un `text` et exactement 4 propositions dont une seule correcte. Son option `--seconds` est enregistrée mais
le temps réel reste la durée totale partagée. Cette commande n'écrit rien au journal des opérations.

## Journaux

`AuditLog` enregistre les opérations sensibles (appeler `services.audit(acteur, action, objet, détail)` pour toute
nouvelle action de ce type). `SecurityEvent` enregistre les événements de passation. L'application ne configure pas de
journalisation applicative propre : conserver les journaux des conteneurs (`docker compose logs`).

## Développer

```bash
python manage.py test qcm
python manage.py makemigrations --check --dry-run
```

Règles d'équipe (voir les perspectives, §4) : une branche par issue, PR avec `Closes #N`, relecture par un autre
membre, tests verts avant fusion, tests pour tout nouveau comportement, prévenir avant de modifier `models.py`,
**aucune vraie donnée dans le dépôt**.

Les verrous et la concurrence se vérifient sur PostgreSQL : définir les variables `POSTGRES_*` vers une base jetable,
puis lancer les mêmes tests.

## Mettre à jour une installation

1. [Sauvegarder](SAUVEGARDE.md).
2. Récupérer le code, puis `docker compose up -d --build` (les migrations s'appliquent au démarrage).
3. Se connecter et vérifier les résultats d'un examen passé.

Retour arrière : revenir à l'ancien code **et** restaurer la sauvegarde. Ne jamais mettre à jour pendant un examen.
