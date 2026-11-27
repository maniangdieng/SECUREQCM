"""
Test de charge Secure QCM (issue #8) : N étudiants passent un examen en même temps.

Parcours simulé, identique à celui du navigateur depuis la PR #22 (examen sans rechargement) :
  connexion → saisie du code d'examen → page de consignes → confirmation (démarrage du chronomètre)
  → pour chaque question : sauvegarde automatique (save.json) puis envoi (answer.json)
  → l'examen est terminé quand le serveur renvoie un statut autre que IN_PROGRESS.

Préparation (base de TEST, jamais la base d'un vrai examen) :
    python manage.py seed_demo --reset --students 200 --force

Lancement (voir loadtest/README.md) :
    locust -f loadtest/locustfile.py --host http://IP_DU_SERVEUR:8000 \
           --users 200 --spawn-rate 10 --run-time 15m --headless --csv loadtest/resultats

Les lignes « FLOW » du rapport résument les copies : « copie COMPLETED » doit être égal au nombre
d'étudiants ; toute autre issue (temps écoulé, échec de démarrage…) apparaît en échec.
"""
import html
import itertools
import json
import os
import random
import re
import threading
import time

from locust import HttpUser, between, events, task
from locust.exception import StopUser

EXAM_CODE = os.getenv("LOADTEST_EXAM_CODE", "DEMOGL01")
EXAM_TITLE = os.getenv("LOADTEST_EXAM_TITLE", "Démo – Génie logiciel")
PASSWORD = os.getenv("LOADTEST_PASSWORD", "Demo-SecureQCM-2026")
# Temps de réflexion par question (secondes) : un vrai étudiant lit la question avant de répondre.
THINK_MIN = float(os.getenv("LOADTEST_THINK_MIN", "5"))
THINK_MAX = float(os.getenv("LOADTEST_THINK_MAX", "20"))

_counter = itertools.count(1)
_lock = threading.Lock()

CSRF_RE = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')
STATE_RE = re.compile(r'<script id="exam-state" type="application/json">(.*?)</script>', re.S)
ATTEMPT_URL_RE = re.compile(r"/attempt/(\d+)/$")


def csrf(page):
    m = CSRF_RE.search(page)
    return m.group(1) if m else ""


def flow(name, error=None):
    """Ligne de synthèse dans le rapport Locust (type FLOW), sans requête HTTP."""
    events.request.fire(request_type="FLOW", name=name, response_time=0, response_length=0,
                        exception=Exception(error) if error else None)


def exam_card(page, title):
    """Bloc HTML de la carte d'examen dont le titre est `title` (tableau de bord étudiant)."""
    marker = f"<strong>{html.escape(title, quote=False)}</strong>"
    for block in page.split('<div class="work">')[1:]:
        if marker in block:
            return block
    return None


class Etudiant(HttpUser):
    wait_time = between(THINK_MIN, THINK_MAX)

    def on_start(self):
        with _lock:
            self.username = f"demo_etu{next(_counter):03d}"
        self.state = None
        self.login()
        self.start_exam()

    def fail(self, name, message):
        flow(name, f"{self.username} : {message}")
        raise StopUser()

    # -------------------------------------------------------------- connexion et démarrage
    def login(self):
        page = self.client.get("/accounts/login/", name="1. page de connexion")
        resp = self.client.post("/accounts/login/", name="2. connexion",
                                data={"username": self.username, "password": PASSWORD,
                                      "csrfmiddlewaretoken": csrf(page.text)},
                                headers={"Referer": self.host + "/accounts/login/"})
        if "/accounts/login/" in resp.url or resp.status_code != 200:
            self.fail("échec de connexion", f"HTTP {resp.status_code}, {resp.url}")
        self.dashboard = resp

    def start_exam(self):
        card = exam_card(self.dashboard.text, EXAM_TITLE)
        if card is None:
            self.fail("examen introuvable", f"pas de carte « {EXAM_TITLE} » sur le tableau de bord")
        exam_id = re.search(r'name="exam_id" value="(\d+)"', card)
        if exam_id:  # code d'accès pas encore saisi
            resp = self.client.post("/student/join-exam/", name="3. saisie du code d'examen",
                                    data={"exam_id": exam_id.group(1), "access_code": EXAM_CODE,
                                          "next": "/dashboard/student/",
                                          "csrfmiddlewaretoken": csrf(self.dashboard.text)},
                                    headers={"Referer": self.dashboard.url})
            card = exam_card(resp.text, EXAM_TITLE) or ""
        start = re.search(r'href="(/student/exams/\d+/start/)"', card)
        if not start:
            self.fail("code refusé", "pas de lien « Commencer » après la saisie du code")
        consignes = self.client.get(start.group(1), name="4. page de consignes")
        if 'name="confirm"' not in consignes.text:
            self.fail("consignes absentes", f"page inattendue : {consignes.url}")
        page = self.client.post(start.group(1), name="5. confirmation et démarrage",
                                data={"confirm": "on", "csrfmiddlewaretoken": csrf(consignes.text)},
                                headers={"Referer": self.host + start.group(1)})
        self.attempt_url = ATTEMPT_URL_RE.search(page.url)
        state = STATE_RE.search(page.text)
        if not self.attempt_url or not state:
            self.fail("démarrage impossible", f"pas de page d'examen ({page.url})")
        self.attempt_url = self.attempt_url.group(0)
        self.token = csrf(page.text)
        self.state = json.loads(state.group(1))
        self.started = time.monotonic()

    # -------------------------------------------------------------- une question par tâche
    @task
    def repondre(self):
        if self.state.get("status") != "IN_PROGRESS":
            return self.finish()
        q = self.state["question"]
        ids = [str(o["id"]) for o in q["options"]]
        choice = random.sample(ids, k=random.randint(1, min(2, len(ids)))) if q["multiple"] else [random.choice(ids)]
        data = {"question_id": str(q["id"]), "option": choice, "csrfmiddlewaretoken": self.token}
        headers = {"Accept": "application/json", "Referer": self.host + self.attempt_url}
        # Le navigateur enregistre la sélection (sauvegarde automatique) avant l'envoi.
        self.client.post(self.attempt_url + "save.json", data=data, headers=headers, name="6. sauvegarde automatique")
        with self.client.post(self.attempt_url + "answer.json", data=data, headers=headers,
                              name="7. réponse à une question", catch_response=True) as resp:
            # 409 = la question avait déjà changé (échéance) : le serveur renvoie l'état courant, c'est normal.
            if resp.status_code not in (200, 409):
                resp.failure(f"HTTP {resp.status_code}")
                return
            try:
                self.state = resp.json()
            except ValueError:
                resp.failure("réponse non JSON")
                return
            resp.success()
        if self.state.get("status") != "IN_PROGRESS":
            self.finish()

    def finish(self):
        status = self.state.get("status")
        self.client.get(self.attempt_url, name="8. page de fin")
        flow(f"copie {status}", None if status == "COMPLETED" else f"{self.username} : statut {status}")
        events.request.fire(request_type="FLOW", name="durée de l'examen (ms)",
                            response_time=(time.monotonic() - self.started) * 1000, response_length=0,
                            exception=None)
        raise StopUser()
