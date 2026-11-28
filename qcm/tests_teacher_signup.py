"""Inscription d'un enseignant (choix à l'inscription, comme Google Classroom) et validation par l'administration."""
from django.contrib.auth.models import User
from django.test import TestCase

from .models import AuditLog, Profile


def signup(client, **overrides):
    data = {"account_type": "TEACHER", "first_name": "Awa", "last_name": "Ndiaye", "email": "awa@example.org",
            "username": "awa.ndiaye", "password": "Tres-Solide-2026", "password2": "Tres-Solide-2026"}
    data.update(overrides)
    return client.post("/accounts/register/", data)


class TeacherSignupTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("chef", password="StrongPass123!")
        self.admin.profile.role = "ADMIN"
        self.admin.profile.save()

    def test_register_page_offers_both_account_types(self):
        page = self.client.get("/accounts/register/?type=teacher")
        self.assertContains(page, 'value="TEACHER" checked')
        self.assertContains(page, 'value="STUDENT"')

    def test_teacher_signup_is_pending_without_teacher_rights(self):
        response = signup(self.client, student_number="IGNORE", study_level="L1")
        self.assertRedirects(response, "/accounts/pending/")
        profile = Profile.objects.get(user__username="awa.ndiaye")
        self.assertEqual((profile.role, profile.student_number, profile.study_level), ("PENDING", "", ""))
        self.assertRedirects(self.client.get("/"), "/accounts/pending/")
        page = self.client.get("/accounts/pending/")
        self.assertContains(page, "en attente")
        self.assertNotContains(page, 'data-dialog="dlg-create-class"')
        self.assertNotContains(page, "Importer un QCM")
        self.assertEqual(self.client.get("/dashboard/teacher/").status_code, 403)
        self.assertEqual(self.client.post("/classes/create/", {"name": "Pirate"}).status_code, 403)
        self.assertEqual(self.client.get("/dashboard/student/").status_code, 403)
        self.assertTrue(AuditLog.objects.filter(action="Demande de compte enseignant").exists())

    def test_teacher_signup_requires_email(self):
        signup(self.client, email="")
        self.assertFalse(User.objects.filter(username="awa.ndiaye").exists())

    def test_student_signup_unchanged(self):
        response = self.client.post("/accounts/register/", {
            "account_type": "STUDENT", "first_name": "Moussa", "last_name": "Fall", "student_number": "E-1",
            "study_level": "L2", "username": "moussa", "password": "Tres-Solide-2026", "password2": "Tres-Solide-2026"})
        self.assertRedirects(response, "/dashboard/student/")
        self.assertEqual(Profile.objects.get(user__username="moussa").role, "STUDENT")

    def test_student_still_needs_number_and_level(self):
        signup(self.client, account_type="STUDENT", username="sans.matricule")
        self.assertFalse(User.objects.filter(username="sans.matricule").exists())

    def test_admin_sees_and_approves_request(self):
        signup(self.client)
        user = User.objects.get(username="awa.ndiaye")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get("/dashboard/admin/users/"), "Demandes de compte enseignant")
        self.assertContains(self.client.get("/dashboard/admin/"), "enseignant à valider")
        self.client.post(f"/dashboard/admin/users/{user.id}/teacher-request/", {"decision": "approve"})
        self.assertEqual(Profile.objects.get(user=user).role, "TEACHER")
        self.assertTrue(AuditLog.objects.filter(action="Demande enseignant acceptée").exists())
        self.client.force_login(user)
        self.assertRedirects(self.client.get("/"), "/dashboard/teacher/")
        self.assertRedirects(self.client.get("/accounts/pending/"), "/", fetch_redirect_response=False)

    def test_admin_rejects_request(self):
        signup(self.client)
        user = User.objects.get(username="awa.ndiaye")
        self.client.force_login(self.admin)
        self.client.post(f"/dashboard/admin/users/{user.id}/teacher-request/", {"decision": "reject"})
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertEqual(user.profile.role, "STUDENT")
        self.assertTrue(AuditLog.objects.filter(action="Demande enseignant refusée").exists())

    def test_only_admin_decides_and_only_pending_requests(self):
        signup(self.client)
        user = User.objects.get(username="awa.ndiaye")
        self.assertEqual(self.client.post(f"/dashboard/admin/users/{user.id}/teacher-request/",
                                          {"decision": "approve"}).status_code, 403)  # le demandeur lui-même
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(f"/dashboard/admin/users/{self.admin.id}/teacher-request/",
                                          {"decision": "approve"}).status_code, 404)
        self.assertEqual(Profile.objects.get(user=user).role, "PENDING")

    def test_pending_is_not_a_role_the_admin_can_assign(self):
        student = User.objects.create_user("etu", password="StrongPass123!")
        self.client.force_login(self.admin)
        self.client.post(f"/dashboard/admin/users/{student.id}/role/", {"role": "PENDING"})
        self.assertEqual(Profile.objects.get(user=student).role, "STUDENT")
        page = self.client.get("/dashboard/admin/users/new/?role=TEACHER")
        self.assertContains(page, '<option value="TEACHER" selected>')
        self.assertNotContains(page, 'value="PENDING"')
