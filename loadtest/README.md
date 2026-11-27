# Test de charge (issue #8)

Simule N étudiants qui passent le même examen en même temps : connexion → code d'examen → page de consignes →
confirmation → pour chaque question, sauvegarde automatique (`save.json`) puis envoi (`answer.json`), avec 5 à 20 s
de réflexion → page de fin.

> Le script suit le passage d'examen **sans rechargement** (PR #22 et suivantes). Il ne fonctionne pas avec l'ancien
> passage d'examen (une page HTML par question).

## 1. Préparer le serveur cible (base de TEST, jamais la base d'un vrai examen)

```bash
cp .env.example .env                    # renseigner les valeurs, GUNICORN_WORKERS = 2 × nb de cœurs + 1
docker compose up -d --build
docker compose exec web python manage.py seed_demo --reset --students 200 --force
```

## 2. Lancer le test depuis UN AUTRE PC du réseau

Lancer Locust sur le serveur lui-même fausse les résultats (il consomme du CPU).

```bash
pip install -r loadtest/requirements.txt
locust -f loadtest/locustfile.py --host http://IP_DU_SERVEUR:8000 \
       --users 200 --spawn-rate 10 --run-time 6m --headless --csv loadtest/resultats
```

Sans `--headless`, Locust ouvre une interface web sur http://localhost:8089 avec des graphiques en direct.

Variables optionnelles : `LOADTEST_EXAM_CODE` (défaut `DEMOGL01`), `LOADTEST_EXAM_TITLE`
(défaut `Démo – Génie logiciel`, titre de la carte d'examen sur le tableau de bord), `LOADTEST_PASSWORD`,
`LOADTEST_THINK_MIN` / `LOADTEST_THINK_MAX` (temps de réflexion en secondes).

Pour relancer : refaire `seed_demo --reset --students 200 --force` (chaque compte ne peut passer l'examen qu'une fois).

## 3. Lire les résultats

- **0 % d'échecs** : condition obligatoire.
- **« copie COMPLETED »** (ligne FLOW) doit être égal au nombre d'étudiants. Une copie qui finit autrement
  (temps écoulé, démarrage impossible…) apparaît en échec avec son statut.
- **Vérifier aussi dans la base** que toutes les réponses sont là :
  `docker compose exec web python manage.py shell -c "from qcm.models import Attempt, Response; print(Attempt.objects.filter(status='COMPLETED').count(), Response.objects.count())"`
  (attendu pour `DEMOGL01` : 200 et 1600).
- **« 7. réponse à une question »** : c'est ce que vivent les étudiants pendant tout l'examen. Viser une médiane < 300 ms
  et un 95e centile < 1 s.
- **Connexion / démarrage** : c'est le pic du début (tout le monde arrive en même temps). Quelques secondes restent
  acceptables. En pratique, faire connecter les étudiants et saisir le code **avant** de donner le top départ.
- Noter les résultats dans `docs/TEST_DE_CHARGE.md`.

> Ne jamais lancer ce test avec SQLite : les écritures simultanées provoquent des erreurs « database is locked ».
