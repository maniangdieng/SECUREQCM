# Secure QCM : description du projet et perspectives

*Document de travail de l'équipe. Mis à jour le 25/11/2026, après la reprise du projet transmis par le professeur.*

---

## 1. Description

Secure QCM est une application web (Django 5, Python 3.12) qui sert à organiser des **examens QCM surveillés**.
Elle tourne sur un serveur du réseau local de l'établissement (SQLite en développement) ou sous Docker
(PostgreSQL + Gunicorn).

### 1.1 Organisation façon Google Classroom

```
Super-administrateur
   └── Administrateurs ── gèrent les comptes, les classes, l'archivage des examens
          └── Enseignants ── possèdent des Classes (+ co-enseignants)
                 └── Classe ── code de classe ── Étudiants membres
                        └── Examens (brouillon → publié → archivé)
                               └── Questions → Propositions
                                      └── Tentatives d'étudiants → Réponses, Événements de sécurité
```

| Rôle | Comment on l'obtient | Droits |
|---|---|---|
| **Super-admin** | `python manage.py createsuperuser` | Tout. C'est le seul à pouvoir nommer ou révoquer un administrateur. Il ne peut pas être rétrogradé ni désactivé depuis l'application. |
| **Admin** | Nommé par le super-admin (ou compte `is_staff`) | Gestion des rôles enseignant/étudiant, activation et désactivation des comptes, archivage des classes, cycle de vie des examens |
| **Enseignant** | Un admin lui attribue le rôle depuis *Comptes* | Crée ses classes, ajoute des co-enseignants et des étudiants (par matricule), crée ou importe des examens, publie, consulte les résultats |
| **Étudiant** | Inscription libre (`/accounts/register/`) | Rejoint des classes par code, passe les examens auxquels il est affecté |

### 1.2 Règles métier conservées de la version du professeur

Ces règles sont couvertes par des tests automatisés. **Ne pas les modifier sans en discuter avec toute l'équipe.**

1. **Connexion unifiée** : chaque rôle est redirigé vers son espace, et le paramètre `?next=` est ignoré.
2. **Code d'accès par examen** : même affecté, un étudiant doit saisir le code de l'examen avant de le démarrer.
3. **Ciblage** : on peut viser *toute la classe* (nouveau mode), *tout un niveau* (L1…Doctorat) ou une *liste CSV de matricules*.
4. **Temps** : il est contrôlé côté serveur. Le temps par question vaut durée totale ÷ nombre de questions, avec les secondes réparties exactement. À expiration, la réponse est enregistrée blanche. Pas de retour en arrière.
5. **Sécurité** : la 1re violation (sortie du plein écran ou changement d'onglet) donne un avertissement, la 2e clôture l'examen (`TERMINATED_SECURITY`). Cette clôture est **définitive** : impossible de reprendre ou de recommencer.
6. **Notation** : en réponse unique, c'est tout ou rien. En réponses multiples, la note est partielle (bonnes − mauvaises) / nombre de bonnes, bornée entre 0 et 1. Les questions sans réponse valent 0 et la note est ramenée sur 20.
7. **Cycle de vie d'un examen** : sans tentative, suppression normale. Avec tentatives, archivage obligatoire. La suppression définitive d'un examen archivé exige l'export CSV et la saisie de `SUPPRIMER` (admin uniquement).
8. **Durée et questions** sont verrouillées dès qu'une tentative existe ; les questions le sont aussi dès la publication.
9. **Import** de sujets PDF, DOCX ou XLSX, avec corrigé intégré, séparé ou manuel, puis prévisualisation et création en brouillon.

### 1.3 Architecture du code

```
secureqcm/            configuration Django (settings lus dans les variables d'environnement)
qcm/
  models.py           Profile, Classroom, ClassroomMembership, Exam, ExamEnrollment,
                      Question, Option, Attempt, Response, SecurityEvent
  permissions.py      TOUTES les règles d'accès (role, can_manage_exam, can_manage_classroom…)
  services.py         logique métier partagée : affectations, calcul des notes
  importers.py        lecture PDF / Word / Excel
  urls.py             routes de l'application
  views/              une vue par espace fonctionnel (voir la répartition de l'équipe plus bas)
    auth.py  admin.py  classrooms.py  teacher.py  imports.py  student.py  attempts.py  results.py
  tests.py            tests d'origine (rôles, temps, ciblage, archivage, verrouillage sécurité)
  tests_classrooms.py tests des classes, validations, gestion des comptes, parcours complet
templates/            pages HTML (base.html + qcm/* + registration/*)
static/css/app.css    charte graphique (variables CSS en tête de fichier)
static/js/app.js      confirmations, copie des codes, boîtes de dialogue
docs/                 ce document, la checklist de déploiement, l'historique des versions du professeur
```

---

## 2. Ce qui a été fait lors de la reprise

### 2.1 Nettoyage
- **Données retirées du projet** : `db.sqlite3` contenait 25 vrais comptes (avec des e-mails d'étudiants), 18 tentatives et 1010 réponses, et `qcm_data/qcm_machine_learning_100.json` contenait un sujet complet. Ces fichiers sont **sauvegardés hors du projet** dans `Desktop/secure_qcm_sauvegarde_donnees_2026-11-25/`. Ce sont des données personnelles : **ne jamais les pousser sur Git**.
- Le formulaire de création d'examen pré-remplissait « Examen de Machine Learning » : ce titre par défaut est supprimé.
- Les notes de version successives (`GUIDE_*`, `MISE_A_JOUR_*`) sont déplacées dans `docs/historique/`, et le README a été réécrit (l'ancien contredisait le code sur la reprise après clôture de sécurité).
- Ajout de `.gitignore` et de `.dockerignore`. Fichiers `.DS_Store`, `__pycache__` et le fichier fantôme `templates_placeholder.txt` supprimés.

### 2.2 Corrections
| Problème | Correction |
|---|---|
| `DJANGO_ALLOWED_HOSTS` présent dans `.env.example` mais **ignoré** par `settings.py`, avec des IP codées en dur | Hôtes et origines CSRF lus dans l'environnement. `SECRET_KEY` obligatoire en production. Option de cookies sécurisés. |
| `docker-compose` lançait `makemigrations` au démarrage, ce qui pouvait générer des migrations non versionnées | Supprimé : on ne lance que `migrate` |
| Question à **réponse unique avec 2 bonnes réponses** acceptée : l'étudiant (boutons radio) ne pouvait jamais avoir les points | Refusée à la création |
| Points ou durée non numériques : **erreur 500** (`add_question`, `submit_answer`) | Validation des entrées, erreur 400 ou message clair |
| Publication possible avec une question à une seule proposition | Il faut au moins 2 propositions et 1 bonne réponse |
| Un examen **archivé** pouvait encore être rejoint par son code | Vérification de `is_archived` |
| Soumission d'une réponse depuis un ancien onglet : elle était appliquée à la question courante | Champ `question_id` contrôlé |
| Le tableau de bord étudiant affichait « Démarrer » même après la fin de l'examen | Séparation entre « À faire » et « Terminés », avec le statut |
| Requêtes N+1 sur les tableaux de bord | Agrégations `annotate(Count…)` |
| Ordre des questions et options non garanti | `Meta.ordering` sur `position` |
| Export CSV sans matricule | Colonne *Matricule* ajoutée |

### 2.3 Améliorations
- **Classes** façon Google Classroom : création, code de classe (sans caractères ambigus), couleur, co-enseignants, ajout d'étudiants par matricule, fermeture des inscriptions, régénération du code, archivage, départ d'un étudiant.
- **Espace admin** : statistiques, gestion des rôles et des comptes (recherche, filtre, pagination), vue des classes.
- **Résultats** : moyenne sur 20, nombre de violations par copie, journal de sécurité dans chaque copie.
- **Nouveau design** : charte cohérente, cartes de classes, onglets, page d'examen épurée avec chronomètres lisibles, interface adaptée au mobile, sans aucune dépendance externe (fonctionne hors Internet).
- Code découpé en modules (`views/`, `permissions.py`, `services.py`) pour **travailler à plusieurs sans conflits**.
- Tests : on passe de 18 à **45**.

---

## 3. Perspectives : ce qui reste à faire

Priorités : **P1** = à faire avant un vrai examen ; **P2** = fonctionnalité importante ; **P3** = confort ou bonus.

### 3.1 Sécurité et fiabilité de l'examen

- [ ] **P1 : passage d'examen sans rechargement de page.** Aujourd'hui chaque question recharge la page. Or le navigateur quitte le plein écran à chaque navigation, et l'étudiant doit recliquer sur « Continuer en plein écran » à chaque question. Il faut soumettre les réponses en `fetch()` et charger la question suivante en JSON. *(fichiers : `views/attempts.py`, `take_exam.html`)*
- [ ] **P1 : vérifier les faux positifs en conditions réelles.** Un `alert()` d'avertissement ou un changement d'onglet peut faire sortir du plein écran et générer **deux événements pour une seule action**. Le verrou `reporting` du JavaScript ne le couvre qu'en partie. À tester sur Chrome, Firefox et Edge, puis à remplacer par une modale HTML et un délai anti-doublon côté serveur.
- [ ] **P1 : limiter les tentatives de connexion** (bruteforce), par exemple avec `django-axes`.
- [ ] **P1 : test de charge** avec l'effectif maximal (ex. 200 étudiants simultanés) sur la machine cible.
- [ ] **P2 : intégration Safe Exam Browser** (fichier `.seb`, vérification des en-têtes BEK/CK).
- [ ] **P2 : fenêtre d'ouverture de l'examen** (date et heure de début et de fin) : aujourd'hui un examen publié reste ouvert indéfiniment.
- [ ] **P2 : action enseignant « autoriser une reprise »** après une clôture de sécurité contestée (avec trace dans le journal), puisque la clôture est définitive par conception.
- [ ] **P2 : supprimer un enseignant** qui possède des examens avec tentatives provoque une erreur (`Exam.teacher` en CASCADE mais `Attempt.exam` en PROTECT). Décider : `PROTECT` ou transfert des examens à un autre enseignant.
- [x] **P3 : journal d'audit** des opérations administratives (comptes, rôles, examens, inscriptions, classes), en lecture seule.

### 3.2 Fonctionnalités façon Google Classroom
- [ ] **P2 : flux de la classe (annonces)** : l'enseignant publie un message et les étudiants le voient dans la classe.
- [ ] **P2 : publication des notes** : l'enseignant choisit quand les étudiants voient leur note (aujourd'hui le score s'affiche immédiatement en fin d'examen).
- [ ] **P2 : page « Notes » de la classe** : tableau étudiants × examens, avec export.
- [ ] **P2 : invitation par e-mail** (étudiants et co-enseignants) et **réinitialisation du mot de passe** par e-mail. Il faut configurer `EMAIL_BACKEND` et ajouter les templates `registration/password_reset_*`.
- [ ] **P2 : page « Mon profil »** : changer son mot de passe ou son e-mail. Les templates `registration/password_change_*` manquent : Django affiche pour l'instant ceux de l'admin.
- [ ] **P3 : thèmes et sujets** dans une classe (regrouper les examens par chapitre).
- [ ] **P3 : archiver un examen depuis l'espace enseignant** (aujourd'hui réservé à l'admin).

### 3.3 Gestion des examens et questions
- [ ] **P2 : modifier une question** d'un brouillon (aujourd'hui : supprimer puis recréer) et **réordonner** les questions.
- [ ] **P2 : dupliquer un examen** (vers la même classe ou une autre), pour réutiliser un sujet d'une année sur l'autre.
- [ ] **P2 : banque de questions** réutilisable par enseignant, et tirage aléatoire de N questions parmi M.
- [ ] **P3 : images dans les questions** (`ImageField` + `MEDIA_ROOT`).
- [ ] **P3 : OCR** pour les PDF scannés (Tesseract).
- [ ] **P3 : barème négatif** optionnel pour les mauvaises réponses.

### 3.4 Résultats et statistiques
- [x] **P2 : export Excel natif** (`.xlsx` avec `openpyxl`, déjà en dépendance) en plus du CSV.
- [x] **P2 : analyse par question** : taux de réussite, propositions les plus choisies, questions trop faciles ou trop difficiles.
- [x] **P2 : résultats complets** : effectifs par statut, taux de réussite (note ≥ 10/20), réponses justes, fausses et blanches par copie, durée effective, page imprimable pour l'export PDF.
- [ ] **P3 : graphiques** (répartition des notes) dans la page de résultats.

### 3.5 Administration
- [ ] **P2 : création de comptes en masse** par l'admin (import CSV nom, prénom, matricule, niveau).
- [x] **P2 : créer un compte depuis l'application** (page « Comptes » ; aucun compte super-administrateur ne peut être créé).
- [x] **P2 : inscrire un étudiant à un examen** par son matricule, sans retirer les autres inscrits.
- [x] **P2 : durée de session réglable** (`DJANGO_SESSION_HOURS`, 8 heures d'inactivité par défaut).
- [ ] **P3 : tableau de bord admin** avec activité récente et examens en cours en temps réel.

### 3.6 Qualité et outillage de l'équipe
- [ ] **P1 : initialiser le dépôt Git** et le pousser sur GitHub ou GitLab (le dossier reçu n'est pas un dépôt).
- [ ] **P2 : intégration continue** (GitHub Actions) : `python manage.py check` et `python manage.py test` à chaque pull request.
- [ ] **P2 : linter et formateur** : `ruff` + `ruff format`, avec un hook `pre-commit`.
- [ ] **P3 : fixtures de démonstration** (`python manage.py loaddata demo.json`) avec des comptes **fictifs**, pour les démonstrations sans vraies données.
- [ ] **P3 : accessibilité** (contrastes, navigation au clavier, lecteurs d'écran) et **mode sombre** (les variables CSS sont prêtes).

---

## 4. Organisation du travail en équipe

### 4.1 Répartition suggérée (un domaine = un fichier de vues)

| Domaine | Fichiers principaux | Perspectives associées |
|---|---|---|
| Passage d'examen et sécurité | `views/attempts.py`, `take_exam.html`, `static/js/` | 3.1 |
| Classes et flux | `views/classrooms.py`, `classroom_*.html` | 3.2 |
| Examens, questions, import | `views/teacher.py`, `views/imports.py`, `importers.py` | 3.3 |
| Résultats et statistiques | `views/results.py`, `services.py` | 3.4 |
| Administration et comptes | `views/admin.py`, `views/auth.py`, `permissions.py` | 3.5 |
| Design et outillage | `static/css/app.css`, `templates/base.html`, CI | 3.6 |

### 4.2 Règles communes
1. **Une branche par tâche** (`feature/flux-classe`, `fix/plein-ecran`…), puis une pull request relue par au moins un autre membre.
2. **Pas de push sans tests verts** : `python manage.py test qcm`.
3. **Toute nouvelle règle d'accès** va dans `permissions.py`, **toute logique partagée** dans `services.py`.
4. **Modèles** : prévenir l'équipe avant de modifier `models.py`, et versionner les migrations générées (`makemigrations`). Une seule personne fusionne les migrations conflictuelles.
5. **Jamais de vraies données** dans le dépôt : ni `db.sqlite3`, ni `.env`, ni exports de résultats.
6. **Design** : réutiliser les classes CSS existantes (`card`, `btn`, `badge`, `work`, `tabs`…) plutôt que des styles en ligne.

### 4.3 Comptes de test en local
```bash
python manage.py createsuperuser          # super-admin
# puis, dans l'appli : créer un compte étudiant via /accounts/register/,
# et le passer en Enseignant depuis Administration → Comptes.
```
