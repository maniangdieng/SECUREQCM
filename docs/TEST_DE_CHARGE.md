# Rapport de test de charge

## Test du 26/11/2026 — environnement de développement (indicatif)

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
