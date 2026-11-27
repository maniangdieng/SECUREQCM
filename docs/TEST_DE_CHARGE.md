# Rapport de test de charge

## Test du 27/11/2026 — code de la chaîne #22 → #43 (passage d'examen sans rechargement)

**Code testé** : branche `feature/perte-focus-violation` (#43), c'est-à-dire l'application telle qu'elle sera après la
fusion de la chaîne. Parcours simulé : connexion, code d'examen, **page de consignes**, confirmation, puis pour chaque
question **sauvegarde automatique (`save.json`) et envoi (`answer.json`)**. L'examen est compté comme terminé
d'après le **statut renvoyé par le serveur**, et le résultat est vérifié directement dans la base.

**Configuration** : Gunicorn 3 workers + PostgreSQL 16, Locust sur la même machine (**2 cœurs** pour le tout).
`seed_demo --students 200`, examen `DEMOGL01` (8 questions, 10 min), arrivée de 10 étudiants par seconde,
5 à 20 s de réflexion par question.

| Étape | Requêtes | Échecs | Médiane | 90e centile | 95e centile |
|---|---|---|---|---|---|
| Connexion | 200 | 0 | 5,7 s | 8,4 s | 8,6 s |
| Saisie du code | 200 | 0 | 4,8 s | 8,5 s | 8,6 s |
| Page de consignes | 200 | 0 | 2,1 s | 4,1 s | 4,6 s |
| Confirmation et démarrage | 200 | 0 | 3,6 s | 7,2 s | 7,8 s |
| Sauvegarde automatique | 1 600 | 0 | 24 ms | 1,3 s | 1,9 s |
| **Réponse à une question** | 1 600 | 0 | **30 ms** | 1,2 s | 1,8 s |
| Page de fin | 200 | 0 | 21 ms | 31 ms | 38 ms |

**Vérification en base** : 200 tentatives `COMPLETED`, **1 600 réponses enregistrées** (8 × 200), 0 erreur serveur.
Durée médiane d'un examen : 91 s (temps de réflexion compris).

**Analyse** : même constat qu'avant. Pendant l'examen, les réponses sont traitées en ~30 ms. Les temps de plusieurs
secondes se concentrent sur le pic d'arrivée (200 connexions en 20 s, hachage des mots de passe), sur une machine de
2 cœurs partagée avec Locust. Ils sont à mesurer sur la machine cible.

> Les chiffres du 26/11 ci-dessous ont été obtenus avec l'ancien passage d'examen (une page par question) et
> l'ancien script. Ils sont conservés pour mémoire mais ne décrivent plus l'application.


## [Obsolète] Test du 26/11/2026 — ancien passage d'examen

**Configuration** : Gunicorn (4 puis 9 workers) + PostgreSQL 16, Locust sur la même machine,
qui ne dispose que de **2 cœurs** pour le tout. Données : `seed_demo --students 200`, examen `DEMOGL01`
(8 questions, 10 min), 200 étudiants arrivant à 10 par seconde, 5 à 20 s de réflexion par question.

| Étape | Requêtes | Échecs | Médiane | 95e centile |
|---|---|---|---|---|
| Page de connexion | 200 | 0 | 2,0 s | 5,0 s |
| Connexion | 200 | 0 | 5,7 s | 9,0 s |
| Saisie du code d'examen | 200 | 0 | 4,3 s | 8,9 s |
| Démarrage de l'examen | 200 | 0 | 3,0 s | 8,8 s |
| **Réponse à une question** | 1 600 | 0 | **51 ms** | 4,2 s |

**Résultat** : les **200 tentatives se terminent toutes (statut `COMPLETED`), 0 erreur serveur**.

**Analyse**
- Hors pic d'arrivée, une réponse est traitée en ~50 ms.
- Les temps élevés viennent du **pic de connexion** : 200 connexions en 20 s, chacune avec un hachage
  de mot de passe (~0,2 s de CPU), sur 2 cœurs partagés avec Locust et PostgreSQL. Passer de 4 à 9 workers
  n'a rien changé : la limite est le CPU de la machine de test, pas Gunicorn.
- Avec **SQLite**, le même test donne des erreurs 500 « database is locked » : SQLite est réservé au développement.

**À faire** : refaire le test sur la **machine cible**, Locust lancé depuis un autre PC (voir `loadtest/README.md`),
et compléter le tableau ci-dessous.

## Test sur la machine cible

| Date | Machine (CPU / RAM) | Workers | Étudiants | Échecs | Réponse médiane | Réponse 95e c. | Connexion médiane |
|---|---|---|---|---|---|---|---|
| | | | 200 | | | | |
