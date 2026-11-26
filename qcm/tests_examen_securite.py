"""Tests des issues #1 à #4 (domaine examen-sécurité)."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from .models import Attempt, Exam, ExamEnrollment, Option, Question, Response, SecurityEvent
from .views.attempts import VIOLATION_DEBOUNCE_SECONDS


def make_user(username, role_value="STUDENT"):
    user = User.objects.create_user(username=username, password="StrongPass123!")
    user.profile.role = role_value
    user.profile.save()
    return user


class ExamFixture(TestCase):
    """Examen publié de N questions, étudiant affecté avec code validé, tentative démarrée."""
    question_count = 3

    def setUp(self):
        self.teacher = make_user("sec_teacher", "TEACHER")
        self.student = make_user("sec_student")
        self.exam = Exam.objects.create(title="Sécurité", teacher=self.teacher, published=True,
                                        audience_mode="LIST", duration_minutes=10, shuffle_questions=False)
        for n in range(1, self.question_count + 1):
            q = Question.objects.create(exam=self.exam, text=f"Question {n}", position=n)
            Option.objects.create(question=q, text="Juste", is_correct=True, position=1)
            Option.objects.create(question=q, text="Faux", position=2)
        ExamEnrollment.objects.create(exam=self.exam, student=self.student, code_verified=True)
        self.client.force_login(self.student)
        self.client.post(f"/student/exams/{self.exam.id}/start/", {"confirm": "on"})
        self.attempt = Attempt.objects.get(student=self.student)

    def current_question(self):
        self.attempt.refresh_from_db()
        return Question.objects.get(pk=self.attempt.question_order[self.attempt.current_index])

    def answer_json(self, question=None, correct=True):
        question = question or self.current_question()
        option = question.options.get(is_correct=correct)
        return self.client.post(f"/attempt/{self.attempt.id}/answer.json",
                                {"question_id": question.id, "option": [option.id]})

    def violation(self, event="TAB_SWITCH"):
        return self.client.post(f"/attempt/{self.attempt.id}/event/", {"event": event}).json()


# --------------------------------------------------------------------------- #
# Issue #1 : passage sans rechargement (endpoint JSON)
# --------------------------------------------------------------------------- #
class JsonAnswerTests(ExamFixture):
    question_count = 10

    def test_whole_exam_through_json_without_page_reload(self):
        page = self.client.get(f"/attempt/{self.attempt.id}/")
        self.assertContains(page, 'id="exam-state"')
        for index in range(1, 11):
            state = self.answer_json().json()
            if index < 10:
                self.assertEqual(state["status"], "IN_PROGRESS")
                self.assertEqual(state["index"], index + 1)
                self.assertEqual(state["total"], 10)
                self.assertEqual(len(state["question"]["options"]), 2)
        self.assertEqual(state["status"], Attempt.COMPLETED)
        self.assertEqual(state["redirect"], f"/attempt/{self.attempt.id}/")
        self.assertEqual(Response.objects.filter(attempt=self.attempt).count(), 10)

    def test_json_state_does_not_leak_correct_answers(self):
        state = self.client.get(f"/attempt/{self.attempt.id}/").context["state"]
        self.assertNotIn("is_correct", str(state))

    def test_stale_question_id_records_nothing(self):
        first = self.current_question()
        self.answer_json(first)
        before = Response.objects.count()
        state = self.answer_json(first).json()  # renvoi (double clic / nouvel essai réseau)
        self.assertEqual(Response.objects.count(), before)
        self.assertEqual(state["index"], 2)

    def test_expired_question_is_recorded_blank(self):
        q = self.current_question()
        Attempt.objects.filter(pk=self.attempt.pk).update(question_deadline=timezone.now() - timedelta(seconds=1))
        state = self.answer_json(q).json()
        response = Response.objects.get(attempt=self.attempt, question=q)
        self.assertEqual(response.selected_option_ids, [])
        self.assertTrue(response.auto_submitted)
        self.assertEqual(state["index"], 2)

    def test_global_expiry_closes_attempt(self):
        Attempt.objects.filter(pk=self.attempt.pk).update(global_deadline=timezone.now() - timedelta(seconds=1))
        state = self.answer_json().json()
        self.assertEqual(state["status"], Attempt.TIME_EXPIRED)

    def test_closed_attempt_returns_409_with_redirect(self):
        Attempt.objects.filter(pk=self.attempt.pk).update(status=Attempt.COMPLETED)
        response = self.answer_json()
        self.assertEqual(response.status_code, 409)
        self.assertIn("redirect", response.json())

    def test_other_student_cannot_answer(self):
        self.client.force_login(make_user("intrus"))
        self.assertEqual(self.answer_json().status_code, 404)


# --------------------------------------------------------------------------- #
# Issue #2 : anti-doublon des violations
# --------------------------------------------------------------------------- #
class ViolationDebounceTests(ExamFixture):
    def test_tab_switch_plus_fullscreen_exit_counts_once(self):
        first = self.violation("TAB_SWITCH")
        second = self.violation("FULLSCREEN_EXIT")  # même action, quelques ms plus tard
        self.assertTrue(first["warning"])
        self.assertTrue(second["duplicate"])
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, Attempt.IN_PROGRESS)
        self.assertTrue(SecurityEvent.objects.filter(attempt=self.attempt, event_type="VIOLATION_IGNORED").exists())

    def test_second_distinct_violation_still_terminates(self):
        self.violation("TAB_SWITCH")
        later = timezone.now() + timedelta(seconds=VIOLATION_DEBOUNCE_SECONDS + 1)
        with mock.patch("django.utils.timezone.now", return_value=later):
            result = self.violation("TAB_SWITCH")
        self.assertEqual(result["status"], "TERMINATED_SECURITY")
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, Attempt.TERMINATED_SECURITY)

    def test_unknown_event_is_ignored(self):
        self.assertEqual(self.violation("RESUME_AUTHORIZED")["status"], "IN_PROGRESS")
        self.assertFalse(SecurityEvent.objects.filter(attempt=self.attempt).exists())

    def test_exam_page_uses_html_dialogs_not_alert(self):
        page = self.client.get(f"/attempt/{self.attempt.id}/").content.decode()
        self.assertIn('<dialog id="warnDialog">', page)
        self.assertNotIn("alert(", page)


# --------------------------------------------------------------------------- #
# Issue #3 : reprise autorisée par l'enseignant
# --------------------------------------------------------------------------- #
class AuthorizeResumeTests(ExamFixture):
    def terminate(self, seconds_left=300, question_left=40):
        now = timezone.now()
        Attempt.objects.filter(pk=self.attempt.pk).update(
            status=Attempt.TERMINATED_SECURITY, ended_at=now,
            global_deadline=now + timedelta(seconds=seconds_left),
            question_deadline=now + timedelta(seconds=question_left))
        SecurityEvent.objects.create(attempt=self.attempt, event_type="TAB_SWITCH")
        SecurityEvent.objects.create(attempt=self.attempt, event_type="TAB_SWITCH")

    def resume(self, user, reason="Coupure de courant"):
        self.client.force_login(user)
        return self.client.post(f"/teacher/attempts/{self.attempt.id}/authorize-resume/", {"reason": reason})

    def test_teacher_reopens_attempt_with_remaining_time_and_answers(self):
        self.answer_json()  # une réponse avant la clôture
        self.terminate(seconds_left=300, question_left=40)
        self.resume(self.teacher)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, Attempt.IN_PROGRESS)
        self.assertIsNone(self.attempt.ended_at)
        remaining = (self.attempt.global_deadline - timezone.now()).total_seconds()
        self.assertAlmostEqual(remaining, 300, delta=5)
        self.assertEqual(Response.objects.filter(attempt=self.attempt).count(), 1)
        event = SecurityEvent.objects.get(attempt=self.attempt, event_type="RESUME_AUTHORIZED")
        self.assertEqual(event.details["reason"], "Coupure de courant")
        self.assertEqual(event.details["by_id"], self.teacher.id)

    def test_violation_counter_restarts_after_resume(self):
        self.terminate()
        self.resume(self.teacher)
        self.client.force_login(self.student)
        result = self.violation("TAB_SWITCH")
        self.assertTrue(result.get("warning"))  # 1re violation après reprise = simple avertissement
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, Attempt.IN_PROGRESS)

    def test_student_can_continue_after_resume(self):
        self.terminate()
        self.resume(self.teacher)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(f"/attempt/{self.attempt.id}/").status_code, 200)
        self.assertEqual(self.answer_json().json()["status"], "IN_PROGRESS")

    def test_reason_is_mandatory(self):
        self.terminate()
        self.resume(self.teacher, reason="  ")
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, Attempt.TERMINATED_SECURITY)

    def test_student_and_other_teacher_cannot_resume(self):
        self.terminate()
        self.assertEqual(self.resume(self.student).status_code, 403)
        self.assertEqual(self.resume(make_user("autre_prof", "TEACHER")).status_code, 403)

    def test_admin_can_resume(self):
        self.terminate()
        self.resume(User.objects.create_superuser("root", "root@test.local", "StrongPass123!"))
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, Attempt.IN_PROGRESS)

    def test_no_time_left_cannot_resume(self):
        self.terminate(seconds_left=0, question_left=0)
        self.resume(self.teacher)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, Attempt.TERMINATED_SECURITY)

    def test_completed_attempt_cannot_be_reopened(self):
        Attempt.objects.filter(pk=self.attempt.pk).update(status=Attempt.COMPLETED, ended_at=timezone.now())
        self.resume(self.teacher)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, Attempt.COMPLETED)

    def test_copy_page_shows_resume_form_and_journal(self):
        self.terminate()
        self.client.force_login(self.teacher)
        page = self.client.get(f"/teacher/attempts/{self.attempt.id}/results/")
        self.assertContains(page, "Autoriser la reprise")
        self.resume(self.teacher)
        page = self.client.get(f"/teacher/attempts/{self.attempt.id}/results/")
        self.assertContains(page, "Coupure de courant")
        self.assertNotContains(page, "Autoriser la reprise")


# --------------------------------------------------------------------------- #
# Issue #4 : suppression d'un enseignant
# --------------------------------------------------------------------------- #
class TeacherDeletionTests(ExamFixture):
    def test_teacher_with_exams_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            self.teacher.delete()
        self.assertTrue(Exam.objects.filter(pk=self.exam.pk).exists())

    def test_admin_delete_page_explains_instead_of_500(self):
        admin = User.objects.create_superuser("root", "root@test.local", "StrongPass123!")
        self.client.force_login(admin)
        page = self.client.get(f"/admin/auth/user/{self.teacher.id}/delete/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Désactivez plutôt le compte")
        response = self.client.post(f"/admin/auth/user/{self.teacher.id}/delete/", {"post": "yes"})
        self.assertIn(response.status_code, (200, 302))
        self.assertTrue(User.objects.filter(pk=self.teacher.pk).exists())

    def test_teacher_without_exams_can_still_be_deleted(self):
        lonely = make_user("prof_sans_examen", "TEACHER")
        lonely.delete()
        self.assertFalse(User.objects.filter(username="prof_sans_examen").exists())
