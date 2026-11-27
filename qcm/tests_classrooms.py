"""Tests des fonctionnalités ajoutées : classes, validation des questions, gestion des comptes, parcours complet."""
from django.contrib.auth.models import User
from django.test import TestCase

from .models import Attempt, Classroom, ClassroomMembership, Exam, ExamEnrollment, Option, Question


def make_user(username, role_value="STUDENT", number="", level=""):
    user = User.objects.create_user(username=username, password="StrongPass123!")
    user.profile.role = role_value
    user.profile.student_number = number
    user.profile.study_level = level
    user.profile.save()
    return user


def make_class_exam(teacher, classroom):
    exam = Exam.objects.create(title="Examen de classe", teacher=teacher, classroom=classroom, audience_mode="CLASS")
    q = Question.objects.create(exam=exam, text="2 + 2 ?")
    Option.objects.create(question=q, text="4", is_correct=True)
    Option.objects.create(question=q, text="5", is_correct=False)
    return exam


class ClassroomTests(TestCase):
    def setUp(self):
        self.teacher = make_user("cls_teacher", "TEACHER")
        self.other_teacher = make_user("cls_teacher2", "TEACHER")
        self.student = make_user("cls_student", number="MAT-100", level="L3")
        self.outsider = make_user("cls_outsider", number="MAT-200", level="L3")

    def _create_class(self):
        self.client.force_login(self.teacher)
        self.client.post("/classes/create/", {"name": "Machine Learning", "section": "Ingénieur 1"})
        return Classroom.objects.get(name="Machine Learning")

    def _publish(self, exam):
        self.client.force_login(self.teacher)
        self.client.post(f"/teacher/exams/{exam.id}/publish/")

    def test_teacher_creates_class_and_becomes_member(self):
        classroom = self._create_class()
        self.assertEqual(classroom.owner, self.teacher)
        self.assertTrue(ClassroomMembership.objects.filter(classroom=classroom, user=self.teacher, role="TEACHER").exists())
        self.assertEqual(len(classroom.join_code), 7)

    def test_student_cannot_create_class(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.post("/classes/create/", {"name": "Pirate"}).status_code, 403)

    def test_student_joins_with_code_and_is_enrolled_in_published_class_exams(self):
        classroom = self._create_class()
        exam = make_class_exam(self.teacher, classroom)
        self._publish(exam)
        self.client.force_login(self.student)
        response = self.client.post("/classes/join/", {"join_code": classroom.join_code.lower()})
        self.assertRedirects(response, f"/classes/{classroom.id}/", fetch_redirect_response=False)
        self.assertTrue(ExamEnrollment.objects.filter(exam=exam, student=self.student, source="CLASS").exists())

    def test_publishing_class_exam_enrolls_only_class_members(self):
        classroom = self._create_class()
        ClassroomMembership.objects.create(classroom=classroom, user=self.student, role="STUDENT")
        exam = make_class_exam(self.teacher, classroom)
        self._publish(exam)
        self.assertTrue(ExamEnrollment.objects.filter(exam=exam, student=self.student).exists())
        self.assertFalse(ExamEnrollment.objects.filter(exam=exam, student=self.outsider).exists())

    def test_class_exam_still_requires_exam_code_before_start(self):
        classroom = self._create_class()
        ClassroomMembership.objects.create(classroom=classroom, user=self.student, role="STUDENT")
        exam = make_class_exam(self.teacher, classroom)
        self._publish(exam)
        self.client.force_login(self.student)
        self.client.post(f"/student/exams/{exam.id}/start/", {"confirm": "on"})
        self.assertFalse(Attempt.objects.filter(exam=exam).exists())
        self.client.post("/student/join-exam/", {"access_code": exam.access_code, "exam_id": exam.id})
        self.client.post(f"/student/exams/{exam.id}/start/", {"confirm": "on"})
        self.assertTrue(Attempt.objects.filter(exam=exam, student=self.student).exists())

    def test_non_member_cannot_join_class_exam_by_code(self):
        classroom = self._create_class()
        exam = make_class_exam(self.teacher, classroom)
        self._publish(exam)
        self.client.force_login(self.outsider)
        self.client.post("/student/join-exam/", {"access_code": exam.access_code, "exam_id": exam.id})
        self.assertFalse(ExamEnrollment.objects.filter(exam=exam, student=self.outsider).exists())

    def test_leaving_class_removes_unstarted_enrollments(self):
        classroom = self._create_class()
        exam = make_class_exam(self.teacher, classroom)
        self._publish(exam)
        self.client.force_login(self.student)
        self.client.post("/classes/join/", {"join_code": classroom.join_code})
        self.client.post(f"/classes/{classroom.id}/leave/")
        self.assertFalse(ExamEnrollment.objects.filter(exam=exam, student=self.student).exists())

    def test_closed_registration_rejects_join(self):
        classroom = self._create_class()
        classroom.join_enabled = False
        classroom.save()
        self.client.force_login(self.student)
        self.client.post("/classes/join/", {"join_code": classroom.join_code})
        self.assertFalse(ClassroomMembership.objects.filter(classroom=classroom, user=self.student).exists())

    def test_coteacher_can_manage_class_exams(self):
        classroom = self._create_class()
        self.client.post(f"/classes/{classroom.id}/teachers/add/", {"identifier": "cls_teacher2"})
        exam = make_class_exam(self.teacher, classroom)
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.get(f"/teacher/exams/{exam.id}/").status_code, 200)

    def test_other_teacher_cannot_see_class_or_exam(self):
        classroom = self._create_class()
        exam = make_class_exam(self.teacher, classroom)
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.get(f"/classes/{classroom.id}/").status_code, 403)
        self.assertEqual(self.client.get(f"/teacher/exams/{exam.id}/").status_code, 403)

    def test_teacher_adds_students_by_student_number(self):
        classroom = self._create_class()
        self.client.post(f"/classes/{classroom.id}/students/add/", {"student_numbers": "MAT-100, INCONNU"})
        self.assertTrue(ClassroomMembership.objects.filter(classroom=classroom, user=self.student, role="STUDENT").exists())

    def test_class_with_exams_cannot_be_deleted(self):
        classroom = self._create_class()
        make_class_exam(self.teacher, classroom)
        self.client.post(f"/classes/{classroom.id}/delete/")
        self.assertTrue(Classroom.objects.filter(pk=classroom.pk).exists())

    def test_pages_render(self):
        classroom = self._create_class()
        make_class_exam(self.teacher, classroom)
        for url in ["/dashboard/teacher/", f"/classes/{classroom.id}/", f"/classes/{classroom.id}/?tab=personnes",
                    f"/classes/{classroom.id}/?tab=parametres", "/teacher/import-qcm/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        ClassroomMembership.objects.create(classroom=classroom, user=self.student, role="STUDENT")
        self.client.force_login(self.student)
        for url in ["/dashboard/student/", f"/classes/{classroom.id}/", f"/classes/{classroom.id}/?tab=personnes"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)


class QuestionValidationTests(TestCase):
    def setUp(self):
        self.teacher = make_user("val_teacher", "TEACHER")
        self.exam = Exam.objects.create(title="Brouillon", teacher=self.teacher)
        self.client.force_login(self.teacher)

    def _post(self, **extra):
        data = {"text": "Q ?", "kind": "SINGLE", "points": "1",
                "option_text": ["A", "B", "", "", "", ""], "correct": ["0"]}
        data.update(extra)
        return self.client.post(f"/teacher/exams/{self.exam.id}/question/add/", data)

    def test_invalid_points_does_not_crash(self):
        self.assertEqual(self._post(points="abc").status_code, 302)
        self.assertFalse(Question.objects.exists())

    def test_single_choice_with_two_correct_answers_is_rejected(self):
        self._post(correct=["0", "1"])
        self.assertFalse(Question.objects.exists())

    def test_valid_question_is_created(self):
        self._post()
        self.assertEqual(Question.objects.get().options.count(), 2)

    def test_exam_with_single_option_question_cannot_be_published(self):
        q = Question.objects.create(exam=self.exam, text="Q")
        Option.objects.create(question=q, text="Seule", is_correct=True)
        self.exam.target_level = "L1"
        self.exam.save()
        self.client.post(f"/teacher/exams/{self.exam.id}/publish/")
        self.exam.refresh_from_db()
        self.assertFalse(self.exam.published)


class AdminUserManagementTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_superuser(username="root", email="root@test.local", password="StrongPass123!")
        self.admin = make_user("simple_admin", "ADMIN")
        self.user = make_user("future_teacher")

    def test_admin_can_promote_student_to_teacher(self):
        self.client.force_login(self.admin)
        self.client.post(f"/dashboard/admin/users/{self.user.id}/role/", {"role": "TEACHER"})
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.role, "TEACHER")

    def test_only_superadmin_can_promote_to_admin(self):
        self.client.force_login(self.admin)
        self.client.post(f"/dashboard/admin/users/{self.user.id}/role/", {"role": "ADMIN"})
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.role, "STUDENT")
        self.client.force_login(self.superadmin)
        self.client.post(f"/dashboard/admin/users/{self.user.id}/role/", {"role": "ADMIN"})
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.role, "ADMIN")

    def test_superadmin_cannot_be_demoted_or_disabled(self):
        self.client.force_login(self.admin)
        self.client.post(f"/dashboard/admin/users/{self.superadmin.id}/toggle-active/")
        self.superadmin.refresh_from_db()
        self.assertTrue(self.superadmin.is_active)

    def test_teacher_cannot_manage_users(self):
        teacher = make_user("t", "TEACHER")
        self.client.force_login(teacher)
        self.assertEqual(self.client.get("/dashboard/admin/users/").status_code, 403)

    def test_admin_pages_render(self):
        self.client.force_login(self.superadmin)
        self.assertEqual(self.client.get("/dashboard/admin/").status_code, 200)
        self.assertEqual(self.client.get("/dashboard/admin/users/?q=root").status_code, 200)


class ExamFlowTests(TestCase):
    """Parcours complet : publication, code, passage, fin, résultats, export."""

    def test_full_flow(self):
        teacher = make_user("flow_teacher", "TEACHER")
        student = make_user("flow_student", number="F-1")
        classroom = Classroom.objects.create(name="Flow", owner=teacher)
        ClassroomMembership.objects.create(classroom=classroom, user=teacher, role="TEACHER")
        ClassroomMembership.objects.create(classroom=classroom, user=student, role="STUDENT")
        exam = make_class_exam(teacher, classroom)
        self.client.force_login(teacher)
        self.client.post(f"/teacher/exams/{exam.id}/publish/")
        self.client.force_login(student)
        self.client.post("/student/join-exam/", {"access_code": exam.access_code, "exam_id": exam.id})
        self.client.post(f"/student/exams/{exam.id}/start/", {"confirm": "on"})
        attempt = Attempt.objects.get(student=student)
        self.assertEqual(self.client.get(f"/attempt/{attempt.id}/").status_code, 200)
        good = Option.objects.get(is_correct=True)
        self.client.post(f"/attempt/{attempt.id}/answer.json", {"option": [good.id], "question_id": good.question_id})
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, Attempt.COMPLETED)
        self.assertContains(self.client.get(f"/attempt/{attempt.id}/"), "Copie remise")
        self.assertEqual(self.client.get("/dashboard/student/").status_code, 200)
        self.client.force_login(teacher)
        self.assertEqual(self.client.get(f"/teacher/exams/{exam.id}/results/").status_code, 200)
        self.assertEqual(self.client.get(f"/teacher/attempts/{attempt.id}/results/").status_code, 200)
        csv_text = self.client.get(f"/teacher/exams/{exam.id}/results/export/").content.decode("utf-8-sig")
        self.assertIn("F-1", csv_text)
        self.assertIn("20.00", csv_text)

    def test_garbage_option_id_returns_400(self):
        teacher = make_user("g_teacher", "TEACHER")
        student = make_user("g_student")
        exam = Exam.objects.create(title="G", teacher=teacher, published=True, audience_mode="LIST")
        q = Question.objects.create(exam=exam, text="Q")
        Option.objects.create(question=q, text="A", is_correct=True)
        Option.objects.create(question=q, text="B")
        ExamEnrollment.objects.create(exam=exam, student=student, code_verified=True)
        self.client.force_login(student)
        self.client.post(f"/student/exams/{exam.id}/start/", {"confirm": "on"})
        attempt = Attempt.objects.get()
        data = {"question_id": q.id, "option": ["abc"]}
        self.assertEqual(self.client.post(f"/attempt/{attempt.id}/answer.json", data).status_code, 400)


class SecurityHardeningTests(TestCase):
    def test_csv_export_neutralises_formulas(self):
        from .views.results import csv_safe
        self.assertEqual(csv_safe("=HYPERLINK(\"http://x\")"), "'=HYPERLINK(\"http://x\")")
        self.assertEqual(csv_safe("+33"), "'+33")
        self.assertEqual(csv_safe("Diop"), "Diop")

    def test_zip_bomb_is_rejected(self):
        import io
        import zipfile
        from django.core.files.uploadedfile import SimpleUploadedFile
        from . import importers
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("xl/huge.xml", b"0" * (importers.MAX_UNCOMPRESSED_BYTES + 1))
        upload = SimpleUploadedFile("bombe.xlsx", buffer.getvalue())
        self.assertLess(len(buffer.getvalue()), 1024 * 1024)  # petit fichier compressé...
        with self.assertRaises(ValueError):                    # ...mais refusé avant décompression
            importers.parse_uploaded_questions(upload)

    def test_real_template_still_imports(self):
        from pathlib import Path
        from django.conf import settings
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .importers import parse_uploaded_questions
        data = (Path(settings.BASE_DIR) / "qcm_data" / "modele_import_qcm.xlsx").read_bytes()
        questions = parse_uploaded_questions(SimpleUploadedFile("modele.xlsx", data))
        self.assertEqual(len(questions), 2)
        self.assertEqual(questions[1]["correct"], ["A", "B", "D"])
