
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from .models import Profile, Exam, ExamEnrollment, Question, Option
class BasicRoleTests(TestCase):
    def test_profile_created(self):
        u=User.objects.create_user(username="student",password="StrongPass123!")
        self.assertEqual(u.profile.role,"STUDENT")
    def test_exam_model(self):
        u=User.objects.create_user(username="teacher",password="StrongPass123!")
        e=Exam.objects.create(title="Test",teacher=u)
        self.assertEqual(e.duration_minutes,60)

from datetime import timedelta
from django.utils import timezone
from .models import Attempt
from .views import question_time_seconds

class QuestionTimingTests(TestCase):
    def test_question_time_is_total_duration_divided_by_question_count(self):
        teacher = User.objects.create_user(username="teacher_timer", password="StrongPass123!")
        student = User.objects.create_user(username="student_timer", password="StrongPass123!")
        exam = Exam.objects.create(title="Timer", teacher=teacher, duration_minutes=60)
        attempt = Attempt.objects.create(
            exam=exam, student=student, question_order=[1] * 30,
            global_deadline=timezone.now() + timedelta(minutes=60),
            question_started_at=timezone.now(),
            question_deadline=timezone.now() + timedelta(minutes=2),
        )
        self.assertEqual(question_time_seconds(attempt), 120)

class DeleteQuestionTests(TestCase):
    def test_teacher_can_delete_question_from_unpublished_exam(self):
        teacher = User.objects.create_user(username="teacher_delete", password="StrongPass123!")
        teacher.profile.role = "TEACHER"
        teacher.profile.save()
        exam = Exam.objects.create(title="Brouillon", teacher=teacher)
        question = Question.objects.create(exam=exam, text="Question à supprimer")
        self.client.force_login(teacher)
        response = self.client.post(f"/teacher/exams/{exam.id}/question/{question.id}/delete/")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Question.objects.filter(pk=question.pk).exists())


class QuestionTimingRemainderTests(TestCase):
    def test_integer_question_times_sum_to_total_duration(self):
        teacher = User.objects.create_user(username="teacher_remainder", password="StrongPass123!")
        student = User.objects.create_user(username="student_remainder", password="StrongPass123!")
        exam = Exam.objects.create(title="Timer remainder", teacher=teacher, duration_minutes=60)
        attempt = Attempt.objects.create(
            exam=exam, student=student, question_order=[1] * 7,
            global_deadline=timezone.now() + timedelta(minutes=60),
            question_started_at=timezone.now(),
            question_deadline=timezone.now() + timedelta(seconds=515),
        )
        allocations = [question_time_seconds(attempt, i) for i in range(7)]
        self.assertEqual(allocations, [515, 515, 514, 514, 514, 514, 514])
        self.assertEqual(sum(allocations), 3600)


class LevelTargetingTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(username="level_teacher", password="StrongPass123!")
        self.teacher.profile.role = "TEACHER"
        self.teacher.profile.save()
        self.l3_student = User.objects.create_user(username="level_l3", password="StrongPass123!")
        self.l3_student.profile.study_level = "L3"
        self.l3_student.profile.save()
        self.m1_student = User.objects.create_user(username="level_m1", password="StrongPass123!")
        self.m1_student.profile.study_level = "M1"
        self.m1_student.profile.save()

    def test_publishing_level_exam_enrolls_only_matching_students(self):
        exam = Exam.objects.create(title="IA L3", teacher=self.teacher, target_level="L3")
        question = Question.objects.create(exam=exam, text="Question")
        Option.objects.create(question=question, text="Bonne réponse", is_correct=True)
        Option.objects.create(question=question, text="Mauvaise réponse", is_correct=False)
        self.client.force_login(self.teacher)
        response = self.client.post(f"/teacher/exams/{exam.id}/publish/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ExamEnrollment.objects.filter(exam=exam, student=self.l3_student, source="LEVEL").exists())
        self.assertFalse(ExamEnrollment.objects.filter(exam=exam, student=self.m1_student).exists())

    def test_level_student_must_enter_exam_code_before_start(self):
        exam = Exam.objects.create(title="IA L3 code", teacher=self.teacher, target_level="L3", published=True)
        ExamEnrollment.objects.create(exam=exam, student=self.l3_student, source="LEVEL")
        self.client.force_login(self.l3_student)
        response = self.client.post(f"/student/exams/{exam.id}/start/")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Attempt.objects.filter(exam=exam, student=self.l3_student).exists())
        response = self.client.post("/student/join-exam/", {"access_code": exam.access_code, "exam_id": exam.id})
        self.assertEqual(response.status_code, 302)
        enrollment = ExamEnrollment.objects.get(exam=exam, student=self.l3_student)
        self.assertTrue(enrollment.code_verified)

    def test_student_from_another_level_cannot_join_by_code(self):
        exam = Exam.objects.create(title="IA L3 private", teacher=self.teacher, target_level="L3", published=True)
        self.client.force_login(self.m1_student)
        response = self.client.post("/student/join-exam/", {"access_code": exam.access_code, "exam_id": exam.id})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ExamEnrollment.objects.filter(exam=exam, student=self.m1_student).exists())

    def test_registration_saves_level_and_enrolls_in_published_level_exam(self):
        exam = Exam.objects.create(title="L2 published", teacher=self.teacher, target_level="L2", published=True)
        response = self.client.post("/accounts/register/", {
            "first_name": "Awa", "last_name": "Diop", "student_number": "MAT-001",
            "study_level": "L2", "username": "awa_diop", "password": "VeryStrongPass!2026",
            "password2": "VeryStrongPass!2026",
        })
        self.assertEqual(response.status_code, 302)
        student = User.objects.get(username="awa_diop")
        self.assertEqual(student.profile.study_level, "L2")
        self.assertTrue(ExamEnrollment.objects.filter(exam=exam, student=student, source="LEVEL").exists())


class UnifiedLoginTests(TestCase):
    def _user(self, username, role_value, staff=False):
        user = User.objects.create_user(username=username, password="StrongPass123!", is_staff=staff)
        user.profile.role = role_value
        user.profile.save()
        return user

    def test_student_is_redirected_to_student_dashboard(self):
        self._user("login_student", "STUDENT")
        response = self.client.post("/accounts/login/", {"username": "login_student", "password": "StrongPass123!"})
        self.assertRedirects(response, "/dashboard/student/", fetch_redirect_response=False)

    def test_teacher_is_redirected_to_teacher_dashboard(self):
        self._user("login_teacher", "TEACHER")
        response = self.client.post("/accounts/login/", {"username": "login_teacher", "password": "StrongPass123!"})
        self.assertRedirects(response, "/dashboard/teacher/", fetch_redirect_response=False)

    def test_superuser_is_redirected_to_admin_dashboard(self):
        User.objects.create_superuser(username="login_admin", email="admin@example.test", password="StrongPass123!")
        response = self.client.post("/accounts/login/", {"username": "login_admin", "password": "StrongPass123!"})
        self.assertRedirects(response, "/dashboard/admin/", fetch_redirect_response=False)

    def test_next_parameter_cannot_send_user_to_another_role_dashboard(self):
        self._user("login_student_next", "STUDENT")
        response = self.client.post("/accounts/login/?next=/dashboard/admin/", {
            "username": "login_student_next", "password": "StrongPass123!", "next": "/dashboard/admin/"
        })
        self.assertRedirects(response, "/dashboard/student/", fetch_redirect_response=False)


class AdminExamLifecycleTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="lifecycle_admin", email="admin@test.local", password="StrongPass123!")
        self.teacher = User.objects.create_user(username="lifecycle_teacher", password="StrongPass123!")
        self.exam = Exam.objects.create(title="Examen à gérer", teacher=self.teacher)
        self.client.force_login(self.admin)

    def test_admin_can_normally_delete_exam_without_attempts(self):
        response = self.client.post(f"/dashboard/admin/exams/{self.exam.id}/delete/")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Exam.objects.filter(pk=self.exam.pk).exists())

    def test_admin_can_archive_exam_with_attempts(self):
        from django.utils import timezone
        from datetime import timedelta
        student = User.objects.create_user(username="lifecycle_student", password="StrongPass123!")
        Attempt.objects.create(exam=self.exam, student=student, question_order=[],
            global_deadline=timezone.now()+timedelta(minutes=10),
            question_started_at=timezone.now(), question_deadline=timezone.now()+timedelta(minutes=1))
        response = self.client.post(f"/dashboard/admin/exams/{self.exam.id}/archive/")
        self.assertEqual(response.status_code, 302)
        self.exam.refresh_from_db()
        self.assertTrue(self.exam.is_archived)

    def test_permanent_delete_requires_export_confirmation_and_phrase(self):
        from django.utils import timezone
        from datetime import timedelta
        student = User.objects.create_user(username="lifecycle_student2", password="StrongPass123!")
        attempt = Attempt.objects.create(exam=self.exam, student=student, question_order=[],
            global_deadline=timezone.now()+timedelta(minutes=10),
            question_started_at=timezone.now(), question_deadline=timezone.now()+timedelta(minutes=1))
        self.exam.is_archived = True
        self.exam.save(update_fields=["is_archived"])
        response = self.client.post(f"/dashboard/admin/exams/{self.exam.id}/delete-permanently/",
            {"confirmation": "SUPPRIMER", "export_confirmed": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Exam.objects.filter(pk=self.exam.pk).exists())
        self.assertFalse(Attempt.objects.filter(pk=attempt.pk).exists())


class SecurityTerminationLockoutTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(username="lockout_teacher", password="StrongPass123!")
        self.student = User.objects.create_user(username="lockout_student", password="StrongPass123!")
        self.exam = Exam.objects.create(
            title="Examen sécurisé", teacher=self.teacher, published=True
        )
        self.enrollment = ExamEnrollment.objects.create(
            exam=self.exam, student=self.student, code_verified=True
        )
        now = timezone.now()
        self.attempt = Attempt.objects.create(
            exam=self.exam, student=self.student, status=Attempt.TERMINATED_SECURITY,
            question_order=[], global_deadline=now + timedelta(minutes=30),
            question_started_at=now, question_deadline=now + timedelta(minutes=1),
            ended_at=now,
        )

    def test_student_cannot_start_new_attempt_after_security_termination(self):
        self.client.force_login(self.student)
        response = self.client.post(f"/student/exams/{self.exam.id}/start/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Attempt.objects.filter(exam=self.exam, student=self.student).count(), 1)
        self.assertEqual(Attempt.objects.get(pk=self.attempt.pk).status, Attempt.TERMINATED_SECURITY)

    def test_student_cannot_reopen_terminated_attempt_url(self):
        self.client.force_login(self.student)
        response = self.client.get(f"/attempt/{self.attempt.id}/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Attempt.objects.filter(exam=self.exam, student=self.student).count(), 1)
