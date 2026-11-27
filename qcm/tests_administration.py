"""Tests de l'issue #28 : création de comptes, inscription individuelle, journal, durée de session."""
import os
import subprocess
import sys

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase

from .models import Attempt, AuditLog, Classroom, ClassroomMembership, Exam, ExamEnrollment, Option, Question
from .tests_examen_securite import make_user

PASSWORD = "Mot-De-Passe-Solide-42"


class CreateAccountTests(TestCase):
    url = "/dashboard/admin/users/new/"

    def setUp(self):
        self.admin = make_user("adm_admin", "ADMIN")
        self.client.force_login(self.admin)

    def post(self, **overrides):
        data = {"username": "nouveau", "first_name": "Awa", "last_name": "Diop", "email": "",
                "role": "TEACHER", "student_number": "", "study_level": "",
                "password1": PASSWORD, "password2": PASSWORD}
        data.update(overrides)
        return self.client.post(self.url, data)

    def test_admin_creates_a_teacher_who_can_log_in(self):
        response = self.post()
        self.assertRedirects(response, "/dashboard/admin/users/?q=nouveau")
        user = User.objects.get(username="nouveau")
        self.assertEqual(user.profile.role, "TEACHER")
        self.assertEqual(user.get_full_name(), "Awa Diop")
        self.assertTrue(user.check_password(PASSWORD))

    def test_admin_creates_a_student_with_number_and_level(self):
        self.post(role="STUDENT", student_number="ET-100", study_level="L3")
        profile = User.objects.get(username="nouveau").profile
        self.assertEqual((profile.role, profile.student_number, profile.study_level), ("STUDENT", "ET-100", "L3"))

    def test_new_student_is_enrolled_in_published_exams_of_the_level(self):
        teacher = make_user("adm_teacher", "TEACHER")
        exam = Exam.objects.create(title="Niveau", teacher=teacher, published=True,
                                   audience_mode="LEVEL", target_level="L3")
        self.post(role="STUDENT", student_number="ET-100", study_level="L3")
        self.assertEqual(ExamEnrollment.objects.get(exam=exam).source, "LEVEL")

    def test_student_needs_a_number_and_a_level(self):
        response = self.post(role="STUDENT")
        self.assertContains(response, "Le matricule est obligatoire pour un étudiant.")
        self.assertContains(response, "Le niveau est obligatoire pour un étudiant.")
        self.assertFalse(User.objects.filter(username="nouveau").exists())

    def test_student_number_already_used_is_refused(self):
        other = make_user("adm_other")
        other.profile.student_number = "ET-100"
        other.profile.save()
        response = self.post(role="STUDENT", student_number="ET-100", study_level="L3")
        self.assertContains(response, "Ce matricule est déjà associé à un compte.")
        self.assertFalse(User.objects.filter(username="nouveau").exists())

    def test_username_already_used_is_refused_whatever_the_case(self):
        make_user("Nouveau")
        self.post()
        self.assertEqual(User.objects.filter(username__iexact="nouveau").count(), 1)

    def test_weak_or_mismatched_password_is_refused(self):
        self.post(password1="123", password2="123")
        self.post(password2=PASSWORD + "x")
        self.assertFalse(User.objects.filter(username="nouveau").exists())

    def test_no_superuser_or_staff_account_can_be_created(self):
        self.client.force_login(User.objects.create_superuser("adm_root", password=PASSWORD))
        self.post(role="ADMIN", is_superuser="on", is_staff="on")
        user = User.objects.get(username="nouveau")
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertEqual(user.profile.role, "ADMIN")

    def test_only_the_superadmin_creates_an_administrator(self):
        response = self.post(role="ADMIN")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="nouveau").exists())

    def test_teachers_and_students_cannot_create_accounts(self):
        for role_value in ("TEACHER", "STUDENT"):
            self.client.force_login(make_user(f"adm_{role_value.lower()}2", role_value))
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.post().status_code, 403)
        self.assertFalse(User.objects.filter(username="nouveau").exists())

    def test_visitor_is_sent_to_login(self):
        self.client.logout()
        self.assertEqual(self.post().status_code, 302)
        self.assertFalse(User.objects.filter(username="nouveau").exists())

    def test_creation_is_journaled_without_the_password(self):
        self.post()
        entry = AuditLog.objects.get()
        self.assertEqual((entry.actor, entry.action), (self.admin, "Compte créé"))
        self.assertIn("nouveau", entry.target)
        self.assertNotIn(PASSWORD, entry.target + entry.details)

    def test_users_page_links_to_the_form(self):
        self.assertContains(self.client.get("/dashboard/admin/users/"), f'href="{self.url}"')


class IndividualEnrollmentTests(TestCase):
    def setUp(self):
        self.teacher = make_user("ins_teacher", "TEACHER")
        self.exam = self.make_exam("LIST")
        self.already = self.student("ins_first", "ET-1")
        ExamEnrollment.objects.create(exam=self.exam, student=self.already)
        self.target = self.student("ins_second", "ET-2", level="M1")
        self.client.force_login(self.teacher)

    def make_exam(self, mode, **fields):
        exam = Exam.objects.create(title=f"Inscription {mode}", teacher=self.teacher, published=True,
                                   audience_mode=mode, duration_minutes=10, **fields)
        question = Question.objects.create(exam=exam, text="Q", position=1)
        Option.objects.create(question=question, text="Juste", is_correct=True, position=1)
        Option.objects.create(question=question, text="Faux", position=2)
        return exam

    def student(self, name, number, level="L3"):
        user = make_user(name)
        user.profile.student_number = number
        user.profile.study_level = level
        user.profile.save()
        return user

    def add(self, number="ET-2", exam=None):
        exam = exam or self.exam
        return self.client.post(f"/teacher/exams/{exam.id}/students/add/", {"student_number": number}, follow=True)

    def enrolled(self, exam=None):
        return set((exam or self.exam).enrollments.values_list("student__username", flat=True))

    def test_adds_one_student_and_keeps_the_others(self):
        self.add()
        self.assertEqual(self.enrolled(), {"ins_first", "ins_second"})

    def test_adding_twice_does_not_duplicate(self):
        self.add()
        response = self.add()
        self.assertContains(response, "déjà inscrit")
        self.assertEqual(self.exam.enrollments.count(), 2)

    def test_unknown_number_and_teacher_number_are_refused(self):
        self.teacher.profile.student_number = "PROF-1"
        self.teacher.profile.save()
        for number in ("ABSENT", "PROF-1", ""):
            self.add(number)
        self.assertEqual(self.enrolled(), {"ins_first"})

    def test_number_shared_by_two_accounts_is_refused(self):
        self.student("ins_twin", "ET-2")
        response = self.add()
        self.assertContains(response, "Plusieurs comptes portent ce matricule")
        self.assertEqual(self.enrolled(), {"ins_first"})

    def test_closed_or_archived_exam_is_refused(self):
        for fields in ({"closed_at": "2026-01-01T00:00:00Z"}, {"is_archived": True}):
            exam = self.make_exam("LIST", **fields)
            self.add(exam=exam)
            self.assertEqual(self.enrolled(exam), set())

    def test_only_those_who_manage_the_exam_may_enroll(self):
        for user in (make_user("ins_stranger", "TEACHER"), self.target):
            self.client.force_login(user)
            response = self.client.post(f"/teacher/exams/{self.exam.id}/students/add/", {"student_number": "ET-2"})
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.enrolled(), {"ins_first"})

    def test_admin_may_enroll_and_get_is_refused(self):
        self.client.force_login(make_user("ins_admin", "ADMIN"))
        self.assertEqual(self.client.get(f"/teacher/exams/{self.exam.id}/students/add/").status_code, 405)
        self.add()
        self.assertIn("ins_second", self.enrolled())

    def test_student_outside_the_audience_can_see_join_and_start(self):
        classroom = Classroom.objects.create(name="Classe", owner=self.teacher)
        exams = [self.make_exam("LEVEL", target_level="L3"), self.make_exam("CLASS", classroom=classroom)]
        for exam in exams:
            with self.subTest(mode=exam.audience_mode):
                self.client.force_login(self.teacher)
                self.add(exam=exam)
                self.client.force_login(self.target)
                self.assertIn(exam, self.client.get("/dashboard/student/").context["todo_exams"])
                self.client.post("/student/join-exam/", {"exam_id": exam.id, "access_code": exam.access_code})
                enrollment = exam.enrollments.get(student=self.target)
                self.assertEqual((enrollment.code_verified, enrollment.source), (True, "LIST"))
                self.client.post(f"/student/exams/{exam.id}/start/", {"confirm": "on"})
                self.assertTrue(Attempt.objects.filter(exam=exam, student=self.target).exists())

    def test_individual_enrollment_keeps_the_audience_mode(self):
        exam = self.make_exam("LEVEL", target_level="L3")
        self.add(exam=exam)
        exam.refresh_from_db()
        self.assertEqual(exam.audience_mode, "LEVEL")

    def test_existing_automatic_enrollment_becomes_individual_and_survives_leaving_the_class(self):
        classroom = Classroom.objects.create(name="Classe", owner=self.teacher)
        exam = self.make_exam("CLASS", classroom=classroom)
        membership = ClassroomMembership.objects.create(classroom=classroom, user=self.target, role="STUDENT")
        ExamEnrollment.objects.create(exam=exam, student=self.target, source="CLASS", code_verified=True)
        self.add(exam=exam)
        self.client.post(f"/classes/{classroom.id}/members/{membership.id}/remove/")
        enrollment = exam.enrollments.get(student=self.target)
        self.assertEqual((enrollment.source, enrollment.code_verified), ("LIST", True))

    def test_automatic_enrollment_gives_no_access_outside_the_audience(self):
        exam = self.make_exam("LEVEL", target_level="L3")
        ExamEnrollment.objects.create(exam=exam, student=self.target, source="CODE")
        self.client.force_login(self.target)
        self.assertNotIn(exam, self.client.get("/dashboard/student/").context["todo_exams"])

    def test_enrollment_is_journaled(self):
        self.add()
        entry = AuditLog.objects.get()
        self.assertEqual((entry.actor, entry.action), (self.teacher, "Étudiant inscrit à un examen"))
        self.assertIn("ins_second", entry.details)

    def test_exam_page_offers_the_form(self):
        page = self.client.get(f"/teacher/exams/{self.exam.id}/")
        self.assertContains(page, f'action="/teacher/exams/{self.exam.id}/students/add/"')


class JournalTests(TestCase):
    url = "/dashboard/admin/journal/"

    def setUp(self):
        self.admin = make_user("log_admin", "ADMIN")
        self.teacher = make_user("log_teacher", "TEACHER")
        self.student = make_user("log_student")
        self.student.profile.student_number = "ET-9"
        self.student.profile.save()
        self.client.force_login(self.admin)

    def actions(self):
        return list(AuditLog.objects.order_by("id").values_list("action", flat=True))

    def draft(self, **fields):
        exam = Exam.objects.create(title="Journal", teacher=self.teacher, audience_mode="LIST", **fields)
        question = Question.objects.create(exam=exam, text="Q", position=1)
        Option.objects.create(question=question, text="Juste", is_correct=True, position=1)
        Option.objects.create(question=question, text="Faux", position=2)
        return exam

    def attempt(self, exam, status=Attempt.COMPLETED):
        from django.utils import timezone
        later = timezone.now() + timezone.timedelta(minutes=5)
        return Attempt.objects.create(exam=exam, student=self.student, status=status, global_deadline=later,
                                      question_started_at=timezone.now(), question_deadline=later,
                                      question_order=[exam.questions.get().id])

    def test_role_and_activation_changes_are_journaled(self):
        url = f"/dashboard/admin/users/{self.student.id}"
        self.client.post(f"{url}/role/", {"role": "TEACHER"})
        self.client.post(f"{url}/toggle-active/")
        self.client.post(f"{url}/toggle-active/")
        self.assertEqual(self.actions(), ["Rôle modifié", "Compte désactivé", "Compte réactivé"])
        self.assertIn("Enseignant", AuditLog.objects.order_by("id").first().details)

    def test_refused_operations_are_not_journaled(self):
        self.client.post(f"/dashboard/admin/users/{self.student.id}/role/", {"role": "ADMIN"})
        self.client.post(f"/dashboard/admin/users/{self.admin.id}/toggle-active/")
        self.assertEqual(self.actions(), [])

    def test_exam_lifecycle_is_journaled_with_the_title_even_after_deletion(self):
        exam = self.draft()
        self.client.post(f"/teacher/exams/{exam.id}/publish/")
        self.client.post(f"/teacher/exams/{exam.id}/close/")
        self.attempt(exam)
        self.client.post(f"/dashboard/admin/exams/{exam.id}/archive/")
        exam_id = exam.id
        self.client.post(f"/dashboard/admin/exams/{exam_id}/delete-permanently/",
                         {"confirmation": "SUPPRIMER", "export_confirmed": "yes"})
        self.assertEqual(self.actions(), ["Examen publié", "Examen clôturé", "Examen archivé",
                                          "Examen supprimé définitivement"])
        last = AuditLog.objects.order_by("id").last()
        self.assertEqual(last.target, f"Journal (#{exam_id})")
        self.assertIn("1 copie", last.details)

    def test_both_simple_deletions_are_journaled(self):
        for url in ("/dashboard/admin/exams/{}/delete/", "/teacher/exams/{}/delete/"):
            self.client.post(url.format(self.draft().id))
        self.assertEqual(self.actions(), ["Examen supprimé", "Examen supprimé"])

    def test_list_import_records_how_many_enrollments_were_removed(self):
        exam = self.draft()
        exam.audience_mode = "LEVEL"
        exam.save()
        ExamEnrollment.objects.create(exam=exam, student=make_user("log_other"), source="LEVEL")
        upload = SimpleUploadedFile("liste.csv", b"matricule\nET-9\n", content_type="text/csv")
        self.client.post(f"/teacher/exams/{exam.id}/students/import/", {"student_file": upload})
        entry = AuditLog.objects.get()
        self.assertEqual(entry.action, "Liste d'étudiants importée")
        self.assertEqual(entry.details, "1 ajouté(s), 1 retiré(s)")

    def test_security_resume_is_journaled(self):
        exam = self.draft(published=True)
        attempt = self.attempt(exam, Attempt.TERMINATED_SECURITY)
        self.client.force_login(self.teacher)
        self.client.post(f"/teacher/attempts/{attempt.id}/authorize-resume/", {"reason": "Coupure réseau"})
        entry = AuditLog.objects.get()
        self.assertEqual((entry.action, entry.details), ("Reprise autorisée", "Coupure réseau"))

    def test_classroom_operations_are_journaled(self):
        classroom = Classroom.objects.create(name="Classe", owner=self.teacher)
        base = f"/classes/{classroom.id}"
        for _ in range(2):  # le second ajout ne change rien : il n'est pas journalisé
            self.client.post(f"{base}/teachers/add/", {"identifier": "log_admin"})
        membership = ClassroomMembership.objects.create(classroom=classroom, user=self.student, role="STUDENT")
        self.client.post(f"{base}/members/{membership.id}/remove/")
        self.client.post(f"{base}/archive/")
        self.client.post(f"{base}/archive/")
        self.client.post(f"{base}/delete/")
        self.assertEqual(self.actions(), ["Co-enseignant ajouté", "Membre retiré d'une classe", "Classe archivée",
                                          "Classe restaurée", "Classe supprimée"])

    def test_entry_survives_the_deletion_of_its_author(self):
        author = make_user("log_gone", "ADMIN")
        self.client.force_login(author)
        self.client.post(f"/dashboard/admin/users/{self.student.id}/toggle-active/")
        author.delete()
        entry = AuditLog.objects.get()
        self.assertEqual((entry.actor, entry.actor_name), (None, "log_gone"))

    def test_admin_reads_and_filters_the_journal(self):
        self.client.post(f"/dashboard/admin/users/{self.student.id}/toggle-active/")
        self.client.post(f"/dashboard/admin/users/{self.teacher.id}/role/", {"role": "STUDENT"})
        page = self.client.get(self.url)
        self.assertContains(page, "Compte désactivé")
        self.assertContains(page, "Rôle modifié")
        filtered = self.client.get(self.url, {"q": "désactivé"})
        self.assertEqual([e.action for e in filtered.context["page"]], ["Compte désactivé"])

    def test_journal_is_reserved_to_administrators(self):
        for user in (self.teacher, self.student):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_journal_page_cannot_be_used_to_write(self):
        self.assertEqual(self.client.post(self.url).status_code, 405)

    def test_journal_is_read_only_in_django_admin_even_for_the_superadmin(self):
        request = RequestFactory().get("/admin/")
        request.user = User.objects.create_superuser("log_root", password=PASSWORD)
        model_admin = admin.site._registry[AuditLog]
        self.assertTrue(model_admin.has_view_permission(request))
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))


class SessionDurationTests(TestCase):
    def read_settings(self, **env):
        code = ("import secureqcm.settings as s;"
                "print(s.SESSION_COOKIE_AGE, s.SESSION_SAVE_EVERY_REQUEST)")
        environment = {k: v for k, v in os.environ.items() if k != "DJANGO_SESSION_HOURS"}
        return subprocess.run([sys.executable, "-c", code], cwd=settings.BASE_DIR, env={**environment, **env},
                              capture_output=True, text=True)

    def test_default_is_eight_hours_of_inactivity(self):
        self.assertEqual(self.read_settings().stdout.split(), [str(8 * 3600), "True"])

    def test_duration_is_read_from_the_environment(self):
        self.assertEqual(self.read_settings(DJANGO_SESSION_HOURS="4").stdout.split()[0], str(4 * 3600))

    def test_a_duration_barely_longer_than_an_exam_stops_the_startup(self):
        result = self.read_settings(DJANGO_SESSION_HOURS="3")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SESSION_HOURS", result.stderr)

    def test_unified_login_still_ignores_next(self):
        make_user("ses_student")
        response = self.client.post("/accounts/login/?next=/dashboard/admin/",
                                    {"username": "ses_student", "password": "StrongPass123!"})
        self.assertRedirects(response, "/dashboard/student/", fetch_redirect_response=False)
