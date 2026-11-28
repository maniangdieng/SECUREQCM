"""Connexion avec Google (#47). Seul l'échange du code avec Google est simulé : le reste du parcours est réel."""
import time
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import jwt
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import AuditLog, Exam, ExamEnrollment, Profile

PASSWORD = "Mot-De-Passe-2026!"
LOGIN = "/accounts/google/login/"
CALLBACK = "/accounts/google/login/callback/"
SIGNUP = "/accounts/google/signup/"
COMPLETE = "/accounts/google/complete/"
LINK = "/accounts/google/link/"
UNLINK = "/accounts/google/unlink/"
SET_PASSWORD = "/accounts/password/set/"

_GOOGLE = settings.SOCIALACCOUNT_PROVIDERS["google"]
WITH_KEYS = {"google": {**_GOOGLE, "APPS": [{"client_id": "client-de-test", "secret": "secret-de-test"}]}}
WITHOUT_KEYS = {"google": {key: value for key, value in _GOOGLE.items() if key != "APPS"}}


def claims(**overrides):
    data = {"iss": "https://accounts.google.com", "aud": "client-de-test", "exp": int(time.time()) + 600,
            "sub": "google-123", "email": "awa@gmail.com", "email_verified": True,
            "given_name": "Awa", "family_name": "Ndiaye", "picture": "https://exemple.invalid/photo.png"}
    data.update(overrides)
    return {key: value for key, value in data.items() if value is not None}


def student_form(**overrides):
    data = {"account_type": "STUDENT", "first_name": "Awa", "last_name": "Ndiaye",
            "student_number": "E-100", "study_level": "L2"}
    data.update(overrides)
    return data


def texts(response):
    return " | ".join(str(message) for message in get_messages(response.wsgi_request))


@override_settings(GOOGLE_LOGIN_ENABLED=True, SOCIALACCOUNT_PROVIDERS=WITH_KEYS)
class GoogleTestCase(TestCase):
    def google(self, start=LOGIN, data=None, **claim_overrides):
        """Départ vers Google puis retour ; renvoie la réponse de l'adresse de retour."""
        response = self.client.post(start, data or {})
        self.assertEqual(response.status_code, 302, response.content[:300])
        state = parse_qs(urlparse(response["Location"]).query)["state"][0]
        token = jwt.encode(claims(**claim_overrides), "x" * 32, algorithm="HS256")
        with patch("allauth.socialaccount.providers.oauth2.client.OAuth2Client.get_access_token",
                   return_value={"access_token": "jeton", "id_token": token}):
            return self.client.get(CALLBACK, {"code": "code", "state": state})

    def make_user(self, username="awa", role="STUDENT", linked=False, password=PASSWORD,
                  student_number="E-100", study_level="L2", **fields):
        user = User.objects.create_user(username=username, password=password, **fields)
        user.profile.role = role
        if role == "STUDENT":
            user.profile.student_number = student_number
            user.profile.study_level = study_level
        user.profile.save()
        if linked:
            SocialAccount.objects.create(user=user, provider="google", uid="google-123")
        return user

    def session_user(self):
        user_id = self.client.session.get("_auth_user_id")
        return User.objects.get(pk=user_id) if user_id else None


@override_settings(GOOGLE_LOGIN_ENABLED=False, SOCIALACCOUNT_PROVIDERS=WITHOUT_KEYS)
class WithoutKeysTests(TestCase):
    """Sans les deux clés, rien ne change."""

    def test_no_button_and_no_google_route(self):
        for url in ("/accounts/login/", "/accounts/register/"):
            self.assertNotContains(self.client.get(url), "Google")
        self.assertEqual(self.client.post(LOGIN).status_code, 404)
        for url in (CALLBACK, SIGNUP):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_profile_is_unchanged(self):
        user = User.objects.create_user("awa", password=PASSWORD)
        self.client.force_login(user)
        self.assertNotContains(self.client.get("/accounts/profile/"), "Google")
        for url in (LINK, UNLINK):
            self.assertEqual(self.client.post(url, {"password": PASSWORD}).status_code, 404, url)


class EntryTests(GoogleTestCase):
    def test_button_on_login_and_register_pages(self):
        for url in ("/accounts/login/", "/accounts/register/"):
            page = self.client.get(url)
            self.assertContains(page, "Continuer avec Google")
            self.assertContains(page, f'action="{LOGIN}"')

    @override_settings(SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"))
    def test_return_address_is_https_behind_the_proxy(self):
        """Google compare l'adresse de retour à la lettre : derrière Caddy elle doit être en https."""
        response = self.client.post(LOGIN, HTTP_HOST="testserver", HTTP_X_FORWARDED_PROTO="https")
        query = parse_qs(urlparse(response["Location"]).query)
        self.assertEqual(query["redirect_uri"], [f"https://testserver{CALLBACK}"])

    def test_departure_asks_only_name_and_email(self):
        response = self.client.post(LOGIN)
        target = urlparse(response["Location"])
        query = parse_qs(target.query)
        self.assertEqual(target.netloc, "accounts.google.com")
        self.assertEqual(sorted(query["scope"][0].split()), ["email", "profile"])
        self.assertEqual(query["prompt"], ["select_account"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["redirect_uri"], [f"http://testserver{CALLBACK}"])

    def test_departure_needs_a_post(self):
        self.assertEqual(self.client.get(LOGIN).status_code, 405)

    def test_library_pages_are_not_reachable(self):
        for url in ("/accounts/signup/", "/accounts/email/", "/accounts/3rdparty/", "/accounts/3rdparty/signup/",
                    "/accounts/google/login/token/", "/accounts/password/change/", "/accounts/confirm-email/",
                    "/accounts/reauthenticate/", "/accounts/social/connections/"):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_signup_page_without_google_goes_to_login(self):
        self.assertRedirects(self.client.get(SIGNUP), "/accounts/login/")

    def test_cancel_on_google_side(self):
        response = self.client.post(LOGIN)
        state = parse_qs(urlparse(response["Location"]).query)["state"][0]
        response = self.client.get(CALLBACK, {"error": "access_denied", "state": state})
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertIn("annulée", texts(response))
        self.assertEqual(User.objects.count(), 0)

    def test_unknown_state_is_refused(self):
        response = self.client.get(CALLBACK, {"code": "code", "state": "inconnu"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertIn("échoué", texts(response))
        self.assertIsNone(self.session_user())

    def test_token_for_another_application_is_refused(self):
        response = self.google(aud="une-autre-application")
        self.assertIn("échoué", texts(response))
        self.assertIsNone(self.session_user())
        self.assertEqual(self.client.get(SIGNUP).status_code, 302)


class FirstSignInTests(GoogleTestCase):
    def test_first_time_shows_the_form_and_creates_nothing(self):
        self.assertRedirects(self.google(), SIGNUP)
        page = self.client.get(SIGNUP)
        self.assertContains(page, "Compléter mon profil")
        self.assertContains(page, 'name="first_name" required value="Awa"')
        self.assertContains(page, 'value="awa@gmail.com"')
        self.assertNotContains(page, 'name="email"')
        self.assertNotContains(page, 'type="password"')
        self.assertNotContains(page, "utilise déjà cette adresse")
        self.assertEqual((User.objects.count(), SocialAccount.objects.count()), (0, 0))
        self.assertIsNone(self.session_user())

    def test_access_token_is_not_kept_while_the_form_is_pending(self):
        self.google()
        self.assertNotIn("jeton", str(dict(self.client.session)))

    def test_student_account(self):
        teacher = self.make_user("prof", role="TEACHER")
        exam = Exam.objects.create(title="Réseaux", teacher=teacher, published=True, target_level="L2")
        self.google()
        response = self.client.post(SIGNUP, student_form(email="autre@exemple.sn", username="pirate",
                                                         role="ADMIN"))
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        user = self.session_user()
        self.assertEqual((user.username, user.first_name, user.last_name, user.email),
                         ("awa.ndiaye", "Awa", "Ndiaye", "awa@gmail.com"))
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertEqual((user.profile.role, user.profile.student_number, user.profile.study_level),
                         ("STUDENT", "E-100", "L2"))
        account = SocialAccount.objects.get()
        self.assertEqual((account.user, account.uid), (user, "google-123"))
        self.assertEqual(account.extra_data, {"email": "awa@gmail.com"})
        self.assertTrue(ExamEnrollment.objects.filter(exam=exam, student=user).exists())
        self.assertEqual(self.client.session["_auth_user_backend"], "django.contrib.auth.backends.ModelBackend")
        self.assertRedirects(self.client.get("/"), "/dashboard/student/")
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(EmailAddress.objects.count(), 0)

    def test_teacher_account_waits_for_validation(self):
        self.google()
        response = self.client.post(SIGNUP, student_form(account_type="TEACHER"))
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        user = self.session_user()
        self.assertEqual((user.profile.role, user.profile.student_number, user.profile.study_level),
                         ("PENDING", "", ""))
        self.assertRedirects(self.client.get("/"), "/accounts/pending/")
        self.assertEqual(self.client.get("/dashboard/teacher/").status_code, 403)
        self.assertTrue(AuditLog.objects.filter(action="Demande de compte enseignant", actor=user).exists())

    def test_username_stays_unique(self):
        User.objects.create_user("Awa.Ndiaye", password=PASSWORD)
        self.google()
        self.client.post(SIGNUP, student_form())
        self.assertEqual(self.session_user().username, "awa.ndiaye2")

    def test_incomplete_or_invalid_form_creates_nothing(self):
        self.google()
        for overrides in ({"first_name": ""}, {"last_name": " "}, {"student_number": ""}, {"study_level": ""},
                          {"study_level": "L9"}, {"account_type": "ADMIN", "student_number": ""},
                          {"first_name": "x" * 151}, {"student_number": "x" * 41}):
            with self.subTest(overrides=overrides):
                response = self.client.post(SIGNUP, student_form(**overrides))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(User.objects.count(), 0)

    def test_student_number_already_taken(self):
        self.make_user("moussa")
        self.google()
        response = self.client.post(SIGNUP, student_form())
        self.assertContains(response, "déjà associé à un compte")
        self.assertContains(response, "liez Google depuis « Mon profil »")
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(SocialAccount.objects.count(), 0)

    def test_same_email_is_never_attached(self):
        existing = self.make_user("ancien", email="awa@gmail.com", student_number="E-1")
        self.assertRedirects(self.google(), SIGNUP)
        self.assertIsNone(self.session_user())
        self.assertContains(self.client.get(SIGNUP), "utilise déjà cette adresse")
        self.client.post(SIGNUP, student_form())
        self.assertNotEqual(self.session_user(), existing)
        self.assertFalse(SocialAccount.objects.filter(user=existing).exists())

    def test_google_without_email_is_refused(self):
        self.google(email=None)
        response = self.client.get(SIGNUP)
        self.assertRedirects(response, "/accounts/login/", fetch_redirect_response=False)
        self.assertIn("adresse e-mail", texts(response))

    def test_second_submission_creates_no_second_account(self):
        self.google()
        pending = self.client.session["socialaccount_sociallogin"]
        self.client.post(SIGNUP, student_form())
        self.client.logout()
        session = self.client.session
        session["socialaccount_sociallogin"] = pending  # double envoi ou second onglet
        session.save()
        response = self.client.post(SIGNUP, student_form(student_number="E-200"))
        self.assertRedirects(response, "/accounts/login/", fetch_redirect_response=False)
        self.assertEqual((User.objects.count(), SocialAccount.objects.count()), (1, 1))

    def test_cancel_forgets_the_google_identity(self):
        self.google()
        self.assertRedirects(self.client.post(SIGNUP, {"cancel": "1"}), "/accounts/login/")
        self.assertRedirects(self.client.get(SIGNUP), "/accounts/login/")
        self.assertEqual(User.objects.count(), 0)

    def test_next_parameter_is_ignored(self):
        self.google(data={"next": "/admin/", "process": "connect"})
        response = self.client.post(SIGNUP + "?next=/admin/", student_form(next="/admin/"))
        self.assertRedirects(response, "/", fetch_redirect_response=False)


class ReturningUserTests(GoogleTestCase):
    def test_each_role_reaches_its_space(self):
        for role, target in (("STUDENT", "/dashboard/student/"), ("TEACHER", "/dashboard/teacher/"),
                             ("PENDING", "/accounts/pending/")):
            with self.subTest(role):
                User.objects.all().delete()
                self.client.logout()
                user = self.make_user(role=role, linked=True)
                response = self.google()
                self.assertRedirects(response, "/", fetch_redirect_response=False)
                self.assertEqual(self.session_user(), user)
                self.assertRedirects(self.client.get("/"), target, fetch_redirect_response=False)
                self.assertEqual(texts(response), "")

    def test_disabled_account_is_refused(self):
        self.make_user(linked=True, is_active=False)
        response = self.google()
        self.assertRedirects(response, "/accounts/login/", fetch_redirect_response=False)
        self.assertIn("désactivé", texts(response))
        self.assertIsNone(self.session_user())

    def test_administrators_cannot_use_google(self):
        for fields, role in (({"is_staff": True}, "STUDENT"), ({"is_superuser": True}, "STUDENT"), ({}, "ADMIN")):
            with self.subTest(fields=fields, role=role):
                User.objects.all().delete()
                self.make_user(role=role, linked=True, **fields)
                response = self.google()
                self.assertRedirects(response, "/accounts/login/", fetch_redirect_response=False)
                self.assertIn("administration", texts(response))
                self.assertIsNone(self.session_user())

    def test_password_login_still_works_and_is_not_gated(self):
        self.make_user(linked=True, student_number="", study_level="")
        self.client.post("/accounts/login/", {"username": "awa", "password": PASSWORD})
        self.assertEqual(self.client.get("/dashboard/student/").status_code, 200)

    def test_student_without_number_must_complete_after_google(self):
        user = self.make_user(linked=True, student_number="", study_level="")
        self.make_user("moussa", student_number="E-1")
        self.google()
        for url in ("/", "/dashboard/student/", "/accounts/profile/", "/student/todo/"):
            self.assertRedirects(self.client.get(url), COMPLETE, fetch_redirect_response=False)
        self.assertContains(self.client.get(COMPLETE), 'action="/accounts/logout/"')
        for data in ({"student_number": "", "study_level": "L2"}, {"student_number": "E-1", "study_level": "L2"},
                     {"student_number": "E-5", "study_level": "L9"}):
            self.assertEqual(self.client.post(COMPLETE, data).status_code, 200, data)
        response = self.client.post(COMPLETE, {"student_number": "E-5", "study_level": "L3", "role": "ADMIN"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        user.profile.refresh_from_db()
        self.assertEqual((user.profile.student_number, user.profile.study_level, user.profile.role),
                         ("E-5", "L3", "STUDENT"))
        self.assertEqual(self.client.get("/dashboard/student/").status_code, 200)
        self.assertRedirects(self.client.get(COMPLETE), "/", fetch_redirect_response=False)

    def test_completion_cannot_change_a_number_already_set(self):
        user = self.make_user(linked=True, study_level="")
        self.google()
        self.client.post(COMPLETE, {"student_number": "E-999", "study_level": "L3"})
        user.profile.refresh_from_db()
        self.assertEqual((user.profile.student_number, user.profile.study_level), ("E-100", "L3"))

    def test_logout_stays_possible_before_completion(self):
        self.make_user(linked=True, student_number="")
        self.google()
        self.client.post("/accounts/logout/")
        self.assertIsNone(self.session_user())

    def test_complete_page_does_not_change_other_accounts(self):
        user = self.make_user(role="TEACHER", linked=True)
        self.google()
        self.client.post(COMPLETE, {"student_number": "E-5", "study_level": "L3"})
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.student_number, "")


class LinkingTests(GoogleTestCase):
    def link(self, password=PASSWORD, **claim_overrides):
        return self.google(start=LINK, data={"password": password}, **claim_overrides)

    def test_profile_offers_linking_with_password(self):
        self.client.force_login(self.make_user())
        page = self.client.get("/accounts/profile/")
        self.assertContains(page, f'action="{LINK}"')
        self.assertNotContains(page, f'action="{UNLINK}"')

    def test_link_requires_current_password(self):
        self.client.force_login(self.make_user())
        for password in ("", "faux"):
            response = self.client.post(LINK, {"password": password})
            self.assertRedirects(response, "/accounts/profile/", fetch_redirect_response=False)
            self.assertIn("incorrect", texts(response))
        self.assertEqual(self.client.get(LINK).status_code, 405)

    def test_public_button_never_links(self):
        user = self.make_user()
        self.client.force_login(user)
        self.google(data={"process": "connect"})
        self.assertFalse(SocialAccount.objects.exists())
        self.assertEqual(self.session_user(), user)

    def test_link_then_sign_in_with_google(self):
        user = self.make_user(email="ancien@exemple.sn")
        self.client.force_login(user)
        response = self.link()
        self.assertRedirects(response, "/accounts/profile/", fetch_redirect_response=False)
        self.assertIn("Votre compte Google est lié", texts(response))
        self.assertEqual(SocialAccount.objects.get().user, user)
        user.refresh_from_db()
        self.assertEqual((user.email, user.has_usable_password()), ("ancien@exemple.sn", True))
        self.assertTrue(AuditLog.objects.filter(action="Compte Google lié", actor=user).exists())
        self.assertContains(self.client.get("/accounts/profile/"), "awa@gmail.com")
        self.client.logout()
        self.google()
        self.assertEqual(self.session_user(), user)

    def test_a_google_account_belongs_to_one_account(self):
        owner = self.make_user("moussa", linked=True, student_number="E-1")
        other = self.make_user()
        self.client.force_login(other)
        response = self.link()
        self.assertIn("déjà lié à un autre compte", texts(response))
        self.assertEqual(SocialAccount.objects.get().user, owner)
        self.assertEqual(self.session_user(), other)

    def test_one_google_account_per_user(self):
        user = self.make_user(linked=True)
        self.client.force_login(user)
        response = self.client.post(LINK, {"password": PASSWORD})
        self.assertRedirects(response, "/accounts/profile/", fetch_redirect_response=False)
        self.assertEqual(SocialAccount.objects.count(), 1)

    def test_administrator_cannot_link(self):
        admin = self.make_user(is_staff=True)
        self.client.force_login(admin)
        self.assertNotContains(self.client.get("/accounts/profile/"), "Google")
        self.assertEqual(self.client.post(LINK, {"password": PASSWORD}).status_code, 403)

    def test_promoted_to_staff_between_departure_and_return(self):
        user = self.make_user()
        self.client.force_login(user)
        response = self.client.post(LINK, {"password": PASSWORD})
        state = parse_qs(urlparse(response["Location"]).query)["state"][0]
        User.objects.filter(pk=user.pk).update(is_staff=True)
        token = jwt.encode(claims(), "x" * 32, algorithm="HS256")
        with patch("allauth.socialaccount.providers.oauth2.client.OAuth2Client.get_access_token",
                   return_value={"access_token": "jeton", "id_token": token}):
            self.client.get(CALLBACK, {"code": "code", "state": state})
        self.assertFalse(SocialAccount.objects.exists())

    def test_unlink_needs_a_password(self):
        user = self.make_user(linked=True, password=None)
        self.client.force_login(user)
        self.assertNotContains(self.client.get("/accounts/profile/"), f'action="{UNLINK}"')
        response = self.client.post(UNLINK)
        self.assertIn("mot de passe", texts(response))
        self.assertTrue(SocialAccount.objects.exists())

    def test_unlink(self):
        user = self.make_user(linked=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(UNLINK).status_code, 405)
        self.assertContains(self.client.get("/accounts/profile/"), f'action="{UNLINK}"')
        self.assertRedirects(self.client.post(UNLINK), "/accounts/profile/", fetch_redirect_response=False)
        self.assertFalse(SocialAccount.objects.exists())
        self.assertTrue(AuditLog.objects.filter(action="Compte Google dissocié", actor=user).exists())


class WithoutPasswordTests(GoogleTestCase):
    def sign_in(self):
        user = self.make_user("awa.ndiaye", linked=True, password=None, email="awa@gmail.com",
                              first_name="Awa", last_name="Ndiaye")
        self.google()
        return user

    def age_google_sign_in(self, seconds):
        session = self.client.session
        records = session["account_authentication_methods"]
        for record in records:
            record["at"] -= seconds
        session["account_authentication_methods"] = records
        session.save()

    def test_email_is_locked(self):
        user = self.sign_in()
        page = self.client.get("/accounts/profile/")
        self.assertNotContains(page, 'name="email"')
        self.assertContains(page, "Définir un mot de passe")
        self.client.post("/accounts/profile/", {"email": "voleur@exemple.sn", "password": ""})
        user.refresh_from_db()
        self.assertEqual(user.email, "awa@gmail.com")

    def test_set_password_right_after_google(self):
        user = self.sign_in()
        self.assertContains(self.client.get("/accounts/profile/"), f'href="{SET_PASSWORD}"')
        self.assertContains(self.client.get(SET_PASSWORD), "Définir un mot de passe")
        response = self.client.post(SET_PASSWORD, {"new_password1": PASSWORD, "new_password2": PASSWORD})
        self.assertRedirects(response, "/accounts/profile/", fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(self.session_user(), user)
        self.assertContains(self.client.get("/accounts/profile/"), 'name="email"')
        self.client.logout()
        self.client.post("/accounts/login/", {"username": "awa.ndiaye", "password": PASSWORD})
        self.assertEqual(self.session_user(), user)

    def test_weak_password_is_refused(self):
        user = self.sign_in()
        self.client.post(SET_PASSWORD, {"new_password1": "123", "new_password2": "123"})
        user.refresh_from_db()
        self.assertFalse(user.has_usable_password())

    def test_set_password_refused_after_five_minutes(self):
        user = self.sign_in()
        self.age_google_sign_in(301)
        page = self.client.get("/accounts/profile/")
        self.assertNotContains(page, f'href="{SET_PASSWORD}"')
        self.assertContains(page, "Confirmer avec Google")
        response = self.client.post(SET_PASSWORD, {"new_password1": PASSWORD, "new_password2": PASSWORD})
        self.assertRedirects(response, "/accounts/profile/", fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertFalse(user.has_usable_password())

    def test_confirming_with_google_reopens_the_window(self):
        user = self.sign_in()
        self.age_google_sign_in(301)
        self.assertRedirects(self.google(), "/accounts/profile/", fetch_redirect_response=False)
        self.assertEqual(self.session_user(), user)
        self.assertContains(self.client.get("/accounts/profile/"), f'href="{SET_PASSWORD}"')

    def test_confirming_with_another_google_account_is_refused(self):
        user = self.sign_in()
        self.age_google_sign_in(301)
        other = self.make_user("moussa", student_number="E-1")
        SocialAccount.objects.create(user=other, provider="google", uid="google-999")
        for uid in ("google-999", "google-inconnu"):
            with self.subTest(uid):
                response = self.google(sub=uid)
                self.assertRedirects(response, "/accounts/profile/", fetch_redirect_response=False)
                self.assertIn("pas celui", texts(response))
                self.assertEqual(self.session_user(), user)
        response = self.client.post(SET_PASSWORD, {"new_password1": PASSWORD, "new_password2": PASSWORD})
        user.refresh_from_db()
        self.assertFalse(user.has_usable_password())

    def test_session_not_opened_by_google_cannot_set_a_password(self):
        user = self.make_user(linked=True, password=None)
        self.client.force_login(user)
        self.client.post(SET_PASSWORD, {"new_password1": PASSWORD, "new_password2": PASSWORD})
        user.refresh_from_db()
        self.assertFalse(user.has_usable_password())

    def test_user_with_password_goes_to_password_change(self):
        self.client.force_login(self.make_user())
        self.assertRedirects(self.client.get(SET_PASSWORD), reverse("password_change"),
                             fetch_redirect_response=False)

    def test_forgotten_password_does_not_open_a_back_door(self):
        self.make_user(linked=True, password=None, email="awa@gmail.com")
        self.client.post(reverse("password_reset"), {"email": "awa@gmail.com"})
        self.assertEqual(len(mail.outbox), 0)


class AdministrationTests(GoogleTestCase):
    def test_account_without_password_cannot_become_administrator(self):
        """Un administrateur ne passe pas par Google : sans mot de passe, il ne pourrait plus se connecter."""
        target = self.make_user(linked=True, password=None)
        self.client.force_login(self.make_user("chef", is_superuser=True, is_staff=True, student_number="E-1"))
        url = reverse("admin_set_role", args=[target.pk])
        response = self.client.post(url, {"role": "ADMIN"})
        self.assertIn("mot de passe", texts(response))
        target.profile.refresh_from_db()
        self.assertEqual(target.profile.role, "STUDENT")
        self.client.post(url, {"role": "TEACHER"})
        target.profile.refresh_from_db()
        self.assertEqual(target.profile.role, "TEACHER")


class TechnicalAdminTests(GoogleTestCase):
    def test_library_settings_are_not_editable_in_django_admin(self):
        """Une application Google ajoutée dans /admin/ entrerait en conflit avec celle des variables."""
        self.client.force_login(self.make_user("racine", is_superuser=True, is_staff=True))
        for url in ("/admin/socialaccount/socialapp/", "/admin/socialaccount/socialtoken/",
                    "/admin/account/emailaddress/"):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        self.assertEqual(self.client.get("/admin/socialaccount/socialaccount/").status_code, 200)


class ProfileLevelTests(GoogleTestCase):
    def test_level_choices_come_from_the_profile(self):
        self.google()
        page = self.client.get(SIGNUP)
        for value, _label in Profile.LEVEL_CHOICES:
            self.assertContains(page, f'value="{value}"')


PRIVACY = "/confidentialite/"


@override_settings(GOOGLE_LOGIN_ENABLED=False, SOCIALACCOUNT_PROVIDERS=WITHOUT_KEYS)
class PrivacyPageTests(TestCase):
    def test_public_page_tells_what_is_asked_from_google(self):
        page = self.client.get(PRIVACY)
        self.assertContains(page, "Connexion avec Google")
        self.assertContains(page, "seulement votre nom et votre adresse e-mail")

    def test_linked_from_login_and_register_pages(self):
        for url in ("/accounts/login/", "/accounts/register/"):
            self.assertContains(self.client.get(url), f'href="{PRIVACY}"')


class PrivacyDuringGoogleTests(GoogleTestCase):
    def test_linked_from_the_form_that_creates_the_account(self):
        self.google()
        self.assertContains(self.client.get(SIGNUP), f'href="{PRIVACY}"')

    def test_readable_before_the_profile_is_completed(self):
        self.make_user(linked=True, student_number="")
        self.google()
        self.assertContains(self.client.get(COMPLETE), f'href="{PRIVACY}"')
        self.assertEqual(self.client.get(PRIVACY).status_code, 200)
