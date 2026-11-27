"""Tests de la limitation des tentatives de connexion (django-axes, issue #6)."""
from axes.models import AccessAttempt
from axes.utils import reset
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(AXES_FAILURE_LIMIT=5)
class LoginRateLimitTests(TestCase):
    def setUp(self):
        reset()
        self.user = User.objects.create_user(username="awa", password="VeryStrongPass!2026")
        self.url = reverse("login")

    def post(self, password, username="awa", ip="10.0.0.1"):
        return self.client.post(self.url, {"username": username, "password": password}, REMOTE_ADDR=ip)

    def test_quelques_echecs_ne_bloquent_pas(self):
        for _ in range(4):
            self.assertEqual(self.post("mauvais").status_code, 200)
        response = self.post("VeryStrongPass!2026")
        self.assertEqual(response.status_code, 302)

    def test_cinq_echecs_bloquent_meme_avec_le_bon_mot_de_passe(self):
        for _ in range(5):
            self.post("mauvais")
        response = self.post("VeryStrongPass!2026")
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "Trop de tentatives", status_code=429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_blocage_limite_au_couple_identifiant_ip(self):
        for _ in range(5):
            self.post("mauvais")
        # Un camarade sur le même poste/la même IP peut toujours se connecter.
        User.objects.create_user(username="moussa", password="VeryStrongPass!2026")
        self.assertEqual(self.post("VeryStrongPass!2026", username="moussa").status_code, 302)
        self.client.logout()
        # Le même compte depuis un autre poste n'est pas bloqué non plus.
        self.assertEqual(self.post("VeryStrongPass!2026", ip="10.0.0.2").status_code, 302)

    def test_succes_remet_le_compteur_a_zero(self):
        for _ in range(4):
            self.post("mauvais")
        self.assertEqual(self.post("VeryStrongPass!2026").status_code, 302)
        self.assertFalse(AccessAttempt.objects.filter(username="awa", failures_since_start__gt=0).exists())

    def test_reset_par_un_admin_debloque(self):
        for _ in range(5):
            self.post("mauvais")
        reset(username="awa")
        self.assertEqual(self.post("VeryStrongPass!2026").status_code, 302)


@override_settings(AXES_FAILURE_LIMIT=5, AXES_COOLOFF_TIME=0.25)
class LockoutDurationTests(TestCase):
    """Relecture PR #19 : un essai pendant le blocage ne doit pas relancer le délai."""

    def setUp(self):
        reset()
        User.objects.create_user(username="awa", password="VeryStrongPass!2026")

    def post(self, password):
        return self.client.post(reverse("login"), {"username": "awa", "password": password}, REMOTE_ADDR="10.0.0.1")

    def test_essai_pendant_le_blocage_ne_relance_pas_le_delai(self):
        from contextlib import ExitStack
        from datetime import timedelta
        from unittest import mock

        from django.utils import timezone

        def at(moment):
            # axes lit l'heure à plusieurs endroits (import direct de `now` et `timezone.now`).
            stack = ExitStack()
            for target in ("django.utils.timezone.now", "axes.attempts.now", "axes.handlers.proxy.now"):
                stack.enter_context(mock.patch(target, return_value=moment))
            return stack

        t0 = timezone.now()
        with at(t0):
            for _ in range(5):
                self.post("mauvais")
        with at(t0 + timedelta(minutes=14)):
            response = self.post("VeryStrongPass!2026")
            self.assertEqual(response.status_code, 429)
            self.assertContains(response, "15 minutes", status_code=429)
        with at(t0 + timedelta(minutes=16)):
            self.assertEqual(self.post("VeryStrongPass!2026").status_code, 302)


@override_settings(AXES_FAILURE_LIMIT=5, AXES_CLIENT_IP_CALLABLE="qcm.client_ip.client_ip_behind_proxy")
class BehindProxyTests(TestCase):
    """Relecture PR #19 : derrière Caddy, toutes les requêtes ont la même REMOTE_ADDR."""

    PROXY = "172.18.0.5"

    def setUp(self):
        reset()
        User.objects.create_user(username="awa", password="VeryStrongPass!2026")

    def post(self, password, client_ip, spoofed=None):
        xff = f"{spoofed}, {client_ip}" if spoofed else client_ip
        return self.client.post(reverse("login"), {"username": "awa", "password": password},
                                REMOTE_ADDR=self.PROXY, HTTP_X_FORWARDED_FOR=xff)

    def test_un_attaquant_ne_bloque_pas_la_victime_sur_un_autre_poste(self):
        for _ in range(5):
            self.post("mauvais", client_ip="10.0.0.66")
        self.assertEqual(self.post("mauvais", client_ip="10.0.0.66").status_code, 429)
        # La vraie Awa, depuis son poste, passe.
        self.assertEqual(self.post("VeryStrongPass!2026", client_ip="10.0.0.12").status_code, 302)

    def test_x_forwarded_for_falsifie_par_le_navigateur_ignore(self):
        # L'attaquant change la valeur qu'il ajoute lui-même : seule la dernière (celle de Caddy) compte.
        for i in range(5):
            self.post("mauvais", client_ip="10.0.0.66", spoofed=f"1.2.3.{i}")
        self.assertEqual(self.post("VeryStrongPass!2026", client_ip="10.0.0.66", spoofed="9.9.9.9").status_code, 429)

    def test_sans_en_tete_retombe_sur_remote_addr(self):
        from django.test import RequestFactory

        from qcm.client_ip import client_ip_behind_proxy
        request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.3")
        self.assertEqual(client_ip_behind_proxy(request), "10.0.0.3")
