import re

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

OLD_PASSWORD = "Ancien-Mot-2026!"
NEW_PASSWORD = "Nouveau-Mot-2026!"


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="awa", password=OLD_PASSWORD, email="awa@example.com")

    def request_reset(self, email):
        return self.client.post(reverse("password_reset"), {"email": email}, follow=True)

    def assert_app_page(self, response, template):
        self.assertTemplateUsed(response, template)
        self.assertTemplateUsed(response, "base.html")

    def test_login_page_links_to_password_reset(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Mot de passe oublié ?")
        self.assertContains(response, reverse("password_reset"))

    def test_full_reset_journey(self):
        self.assert_app_page(self.client.get(reverse("password_reset")), "registration/password_reset_form.html")
        self.assert_app_page(self.request_reset("awa@example.com"), "registration/password_reset_done.html")

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["awa@example.com"])
        self.assertIn("Secure QCM", message.subject)
        self.assertIn("awa", message.body)  # identifiant rappelé
        link = re.search(r"http://testserver(/accounts/reset/\S+)", message.body).group(1)

        page = self.client.get(link, follow=True)
        self.assert_app_page(page, "registration/password_reset_confirm.html")
        self.assertTrue(page.context["validlink"])
        done = self.client.post(page.redirect_chain[-1][0],
                                {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD}, follow=True)
        self.assert_app_page(done, "registration/password_reset_complete.html")
        self.assertContains(done, reverse("login"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))

        # Le lien ne sert qu'une fois.
        again = self.client.get(link, follow=True)
        self.assertFalse(again.context["validlink"])
        self.assertContains(again, "n’est plus valide")

    def test_weak_password_is_refused_with_a_message(self):
        self.request_reset("awa@example.com")
        link = re.search(r"http://testserver(/accounts/reset/\S+)", mail.outbox[0].body).group(1)
        page = self.client.get(link, follow=True)
        response = self.client.post(page.redirect_chain[-1][0], {"new_password1": "123", "new_password2": "123"})
        self.assertContains(response, 'class="alert error"')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD_PASSWORD))

    def test_unknown_address_gets_the_same_page_and_no_mail(self):
        response = self.request_reset("inconnu@example.com")
        self.assert_app_page(response, "registration/password_reset_done.html")
        self.assertEqual(mail.outbox, [])

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
                       EMAIL_HOST="127.0.0.1", EMAIL_PORT=1, EMAIL_TIMEOUT=2)
    def test_mail_server_failure_does_not_reveal_the_account(self):
        with self.assertLogs("django.contrib.auth", level="ERROR"):
            response = self.request_reset("awa@example.com")
        self.assertEqual(response.status_code, 200)
        self.assert_app_page(response, "registration/password_reset_done.html")
