from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

OLD_PASSWORD = "Ancien-Mot-2026!"
NEW_PASSWORD = "Nouveau-Mot-2026!"


class ProfileTests(TestCase):
    def make_user(self, username, role_value, **profile):
        user = User.objects.create_user(username=username, password=OLD_PASSWORD,
                                        first_name="Awa", last_name="Ndiaye", email="ancien@example.com")
        user.profile.role = role_value
        for field, value in profile.items():
            setattr(user.profile, field, value)
        user.profile.save()
        self.client.force_login(user)
        return user

    def test_profile_shows_identity_and_links_to_password_change(self):
        self.make_user("etudiant", "STUDENT", student_number="MAT-001")
        response = self.client.get(reverse("profile"))
        self.assertContains(response, "Awa Ndiaye")
        self.assertContains(response, "MAT-001")
        self.assertContains(response, reverse("password_change"))
        self.assertContains(response, f'href="{reverse("profile")}"')  # lien dans le menu

    def test_student_and_teacher_can_change_email(self):
        for role_value in ("STUDENT", "TEACHER"):
            with self.subTest(role_value):
                user = self.make_user(f"mail_{role_value}", role_value)
                response = self.client.post(reverse("profile"), {"email": "nouveau@example.com",
                                                                  "password": OLD_PASSWORD})
                self.assertRedirects(response, reverse("profile"))
                user.refresh_from_db()
                self.assertEqual(user.email, "nouveau@example.com")

    def test_invalid_email_is_refused(self):
        user = self.make_user("etudiant", "STUDENT")
        response = self.client.post(reverse("profile"), {"email": "pas-une-adresse", "password": OLD_PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        user.refresh_from_db()
        self.assertEqual(user.email, "ancien@example.com")

    def test_changing_email_requires_current_password(self):
        # Sinon un poste resté ouvert suffit à détourner le compte (nouvel e-mail puis « mot de passe oublié »).
        user = self.make_user("etudiant", "STUDENT")
        for password in ("", "faux"):
            with self.subTest(password=password):
                response = self.client.post(reverse("profile"), {"email": "voleur@example.com", "password": password})
                self.assertContains(response, 'class="alert error"')
                user.refresh_from_db()
                self.assertEqual(user.email, "ancien@example.com")

    def test_only_email_can_be_modified(self):
        user = self.make_user("etudiant", "STUDENT", student_number="MAT-001")
        self.client.post(reverse("profile"), {
            "email": "nouveau@example.com", "password": OLD_PASSWORD, "first_name": "Autre", "username": "pirate",
            "role": "ADMIN", "student_number": "MAT-999", "is_superuser": "on",
        })
        user.refresh_from_db()
        self.assertEqual((user.first_name, user.username, user.is_superuser), ("Awa", "etudiant", False))
        self.assertEqual((user.profile.role, user.profile.student_number), ("STUDENT", "MAT-001"))

    def test_profile_requires_login(self):
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_student_and_teacher_can_change_password(self):
        for role_value in ("STUDENT", "TEACHER"):
            with self.subTest(role_value):
                user = self.make_user(f"mdp_{role_value}", role_value)
                page = self.client.get(reverse("password_change"))
                self.assertTemplateUsed(page, "registration/password_change_form.html")
                self.assertTemplateUsed(page, "base.html")
                self.assertContains(page, "Secure QCM")
                self.assertNotContains(page, "admin/css/")
                response = self.client.post(reverse("password_change"), {
                    "old_password": OLD_PASSWORD,
                    "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD,
                }, follow=True)
                self.assertTemplateUsed(response, "registration/password_change_done.html")
                self.assertTemplateUsed(response, "base.html")
                user.refresh_from_db()
                self.assertTrue(user.check_password(NEW_PASSWORD))
                self.assertIn("_auth_user_id", self.client.session)  # reste connecté

    def test_wrong_old_password_shows_error(self):
        user = self.make_user("etudiant", "STUDENT")
        response = self.client.post(reverse("password_change"), {
            "old_password": "faux", "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD,
        })
        self.assertContains(response, 'class="alert error"')
        user.refresh_from_db()
        self.assertTrue(user.check_password(OLD_PASSWORD))
