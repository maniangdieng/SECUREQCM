"""
Test de charge Secure QCM (issue #8) : N étudiants passent un examen en même temps.

Préparation (base de test, jamais la base de production) :
    python manage.py seed_demo --reset --students 200

Lancement (voir loadtest/README.md) :
    locust -f loadtest/locustfile.py --host http://IP_DU_SERVEUR:8000 \
           --users 200 --spawn-rate 10 --run-time 15m --headless --csv loadtest/resultats

Chaque utilisateur virtuel = un compte demo_etuNNN différent qui :
connexion → saisie du code d'examen → démarrage → réponses question par question → page de fin.
"""
import itertools
import os
import random
import re
import threading

from locust import HttpUser, between, events, task
from locust.exception import StopUser

EXAM_CODE = os.getenv("LOADTEST_EXAM_CODE", "DEMOGL01")
PASSWORD = os.getenv("LOADTEST_PASSWORD", "Demo-SecureQCM-2026")
# Temps de réflexion par question (secondes) : un vrai étudiant lit la question avant de répondre.
THINK_MIN = float(os.getenv("LOADTEST_THINK_MIN", "5"))
THINK_MAX = float(os.getenv("LOADTEST_THINK_MAX", "20"))

_counter = itertools.count(1)
_lock = threading.Lock()

CSRF_RE = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')
EXAM_ID_RE = re.compile(r'name="exam_id" value="(\d+)"')
START_RE = re.compile(r'action="/student/exams/(\d+)/start/"')
QUESTION_RE = re.compile(r'name="question_id" value="(\d+)"')
OPTION_RE = re.compile(r'type="(radio|checkbox)" name="option" value="(\d+)"')
ANSWER_URL_RE = re.compile(r'action="(/attempt/\d+/answer/)"')


def csrf(html):
    m = CSRF_RE.search(html)
    return m.group(1) if m else ""


class Etudiant(HttpUser):
    wait_time = between(THINK_MIN, THINK_MAX)

    def on_start(self):
        with _lock:
            self.username = f"demo_etu{next(_counter):03d}"
        self.finished = False
        self.login()
        self.start_exam()

    # -------------------------------------------------------------- #
    def login(self):
        page = self.client.get("/accounts/login/", name="1. page de connexion")
        resp = self.client.post("/accounts/login/", name="2. connexion",
                                data={"username": self.username, "password": PASSWORD,
                                      "csrfmiddlewaretoken": csrf(page.text)},
                                headers={"Referer": self.host + "/accounts/login/"})
        if "/dashboard/student/" not in resp.url:
            events.request.fire(request_type="FLOW", name="échec connexion", response_time=0,
                                response_length=0, exception=Exception(f"{self.username} : connexion refusée"))
            raise StopUser()
        self.dashboard = resp.text

    def start_exam(self):
        html = self.dashboard
        exam_id = None
        # Formulaire de saisie du code d'accès (si le code n'a pas encore été validé).
        m = EXAM_ID_RE.search(html)
        if m:
            exam_id = m.group(1)
            resp = self.client.post("/student/join-exam/", name="3. saisie du code d'examen",
                                    data={"exam_id": exam_id, "access_code": EXAM_CODE,
                                          "csrfmiddlewaretoken": csrf(html)},
                                    headers={"Referer": self.host + "/dashboard/student/"})
            html = resp.text
        m = START_RE.search(html)
        if not m:
            events.request.fire(request_type="FLOW", name="examen introuvable", response_time=0,
                                response_length=0, exception=Exception(f"{self.username} : pas de bouton Démarrer"))
            raise StopUser()
        resp = self.client.post(f"/student/exams/{m.group(1)}/start/", name="4. démarrage de l'examen",
                                data={"csrfmiddlewaretoken": csrf(html)},
                                headers={"Referer": self.host + "/dashboard/student/"})
        self.page = resp

    @task
    def repondre(self):
        if self.finished:
            raise StopUser()
        html = self.page.text
        q = QUESTION_RE.search(html)
        action = ANSWER_URL_RE.search(html)
        if not q or not action:
            # Page de fin (copie remise / temps écoulé) : l'étudiant a terminé.
            self.finished = True
            events.request.fire(request_type="FLOW", name="examen terminé", response_time=0,
                                response_length=0, exception=None)
            raise StopUser()
        options = OPTION_RE.findall(html)
        data = {"question_id": q.group(1), "csrfmiddlewaretoken": csrf(html)}
        if options:
            kind = options[0][0]
            ids = [o[1] for o in options]
            data["option"] = [random.choice(ids)] if kind == "radio" else random.sample(ids, k=random.randint(1, 2))
        self.page = self.client.post(action.group(1), data=data, name="5. réponse à une question",
                                     headers={"Referer": self.page.url})
