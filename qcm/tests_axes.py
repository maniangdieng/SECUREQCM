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
