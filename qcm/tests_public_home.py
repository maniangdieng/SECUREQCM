"""Page d'accueil publique et identité visuelle (logo, icônes, aperçu de partage)."""
from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.test import TestCase


class PublicHomeTests(TestCase):
    def test_anonymous_visitor_sees_the_public_home(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertTemplateUsed(page, "public/home.html")
        self.assertContains(page, 'href="/accounts/register/"')
        self.assertContains(page, 'href="/accounts/register/?type=teacher"')
        self.assertContains(page, 'href="/accounts/login/"')

    def test_signed_in_user_still_goes_to_their_space(self):
        student = User.objects.create_user("etu_home", password="StrongPass123!")
        self.client.force_login(student)
        self.assertRedirects(self.client.get("/"), "/dashboard/student/")

    def test_pages_carry_the_brand_and_share_preview(self):
        page = self.client.get("/accounts/login/")
        for expected in ("img/favicon.svg", "img/apple-touch-icon.png", "img/logo-mark.svg", "img/logo-secure-qcm.webp",
                         'property="og:image"', "img/og-image.png"):
            self.assertContains(page, expected)
        # Les visiteurs anonymes peuvent créer un compte depuis la barre du haut, sauf sur la page d'inscription.
        self.assertContains(page, "Créer un compte")
        self.assertNotContains(self.client.get("/accounts/register/"), 'class="btn" href="/accounts/register/"')

    def test_brand_files_exist(self):
        for path in ("img/favicon.svg", "img/logo-mark.svg", "img/logo-secure-qcm.webp", "img/logo-embleme.webp",
                     "img/apple-touch-icon.png", "img/og-image.png", "fonts/lexend-latin.woff2", "fonts/lexend-latin-ext.woff2"):
            self.assertIsNotNone(finders.find(path), path)
