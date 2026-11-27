from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import (Attempt, Classroom, ClassroomMembership, Exam, ExamEnrollment, Option, Question, Response)


def make_user(username, role_value="STUDENT", number=""):
    user = User.objects.create_user(username=username, password="StrongPass123!")
    user.profile.role = role_value
    user.profile.student_number = number
    user.profile.save()
    return user


def make_question(exam, text="2 + 2 ?", question_type=Question.SINGLE, points=Decimal("1"), position=1):
    question = Question.objects.create(exam=exam, text=text, question_type=question_type, points=points, position=position)
    Option.objects.create(question=question, text="4", is_correct=True, position=1)
    Option.objects.create(question=question, text="5", is_correct=False, position=2)
    return question


def make_class_exam(teacher, classroom, **kwargs):
    defaults = {"title": "Examen", "teacher": teacher, "classroom": classroom,
                "audience_mode": "CLASS", "published": True}
    defaults.update(kwargs)
    return Exam.objects.create(**defaults)


def make_completed_attempt(exam, student, question):
    now = timezone.now()
    correct = question.options.get(is_correct=True)
    attempt = Attempt.objects.create(
        exam=exam, student=student, question_order=[question.id],
        option_orders={str(question.id): [option.id for option in question.options.order_by("position", "id")]},
        current_index=1, global_deadline=now + timedelta(minutes=10),
        question_started_at=now - timedelta(minutes=5), question_deadline=now + timedelta(minutes=5),
        status=Attempt.COMPLETED, ended_at=now,
    )
    Response.objects.create(attempt=attempt, question=question, selected_option_ids=[correct.id])
    return attempt


class ResultsPublishedTests(TestCase):
    def setUp(self):
        self.teacher = make_user("results_teacher", "TEACHER")
        self.student = make_user("results_student", number="RES-1")
        self.classroom = Classroom.objects.create(name="Results", owner=self.teacher)
        ClassroomMembership.objects.create(classroom=self.classroom, user=self.teacher, role=ClassroomMembership.TEACHER)
        ClassroomMembership.objects.create(classroom=self.classroom, user=self.student, role=ClassroomMembership.STUDENT)
        self.exam = make_class_exam(self.teacher, self.classroom)
        self.question = make_question(self.exam)
        self.attempt = make_completed_attempt(self.exam, self.student, self.question)
        self.finished_url = f"/attempt/{self.attempt.id}/"

    def test_finished_page_hides_score_until_results_published(self):
        self.client.force_login(self.student)
        response = self.client.get(self.finished_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Copie remise")
        self.assertNotContains(response, "Score :")

    def test_teacher_can_publish_results_and_student_sees_score(self):
        self.client.force_login(self.teacher)
        response = self.client.post(f"/teacher/exams/{self.exam.id}/results/publish/")
        self.assertEqual(response.status_code, 302)
        self.exam.refresh_from_db()
        self.assertTrue(self.exam.results_published)

        self.client.force_login(self.student)
        response = self.client.get(self.finished_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Évaluation clôturée")
        self.assertContains(response, "Score :")
        self.assertNotContains(response, "Copie remise")

    def test_student_cannot_publish_results(self):
        self.client.force_login(self.student)
        response = self.client.post(f"/teacher/exams/{self.exam.id}/results/publish/")
        self.assertEqual(response.status_code, 403)
        self.exam.refresh_from_db()
        self.assertFalse(self.exam.results_published)

    def test_cannot_publish_results_before_exam_is_published(self):
        self.exam.published = False
        self.exam.save(update_fields=["published"])
        self.client.force_login(self.teacher)
        response = self.client.post(f"/teacher/exams/{self.exam.id}/results/publish/")
        self.assertEqual(response.status_code, 302)
        self.exam.refresh_from_db()
        self.assertFalse(self.exam.results_published)


class DuplicateExamTests(TestCase):
    def setUp(self):
        self.teacher = make_user("dup_teacher", "TEACHER")
        self.other_teacher = make_user("dup_other_teacher", "TEACHER")
        self.student = make_user("dup_student", number="DUP-1")
        self.classroom = Classroom.objects.create(name="Source", owner=self.teacher)
        self.other_classroom = Classroom.objects.create(name="Target", owner=self.teacher)
        ClassroomMembership.objects.create(classroom=self.classroom, user=self.teacher, role=ClassroomMembership.TEACHER)
        ClassroomMembership.objects.create(classroom=self.other_classroom, user=self.teacher, role=ClassroomMembership.TEACHER)
        ClassroomMembership.objects.create(classroom=self.classroom, user=self.student, role=ClassroomMembership.STUDENT)
        self.exam = make_class_exam(self.teacher, self.classroom, published=True, results_published=True,
                                    opens_at=timezone.now() - timedelta(days=1), closes_at=timezone.now() + timedelta(days=1))
        self.question = make_question(self.exam, text="Question source", question_type=Question.MULTIPLE, points=Decimal("2"))
        extra = Question.objects.create(exam=self.exam, text="Second", question_type=Question.SINGLE, points=Decimal("1.5"), position=2)
        Option.objects.create(question=extra, text="A", is_correct=True, position=1)
        Option.objects.create(question=extra, text="B", is_correct=False, position=2)
        ExamEnrollment.objects.create(exam=self.exam, student=self.student, source="CLASS", code_verified=True)
        self.client.force_login(self.teacher)

    def test_duplicate_exam_copies_content_in_draft_without_history(self):
        response = self.client.post(f"/teacher/exams/{self.exam.id}/duplicate/",
                                    {"classroom_id": str(self.other_classroom.id)})
        self.assertEqual(response.status_code, 302)
        copy = Exam.objects.exclude(pk=self.exam.pk).get()
        self.assertEqual(response["Location"], f"/teacher/exams/{copy.id}/")
        self.assertEqual(copy.teacher, self.teacher)
        self.assertEqual(copy.classroom, self.other_classroom)
        self.assertEqual(copy.audience_mode, "CLASS")
        self.assertFalse(copy.published)
        self.assertFalse(copy.results_published)
        self.assertNotEqual(copy.access_code, self.exam.access_code)
        self.assertEqual(copy.questions.count(), 2)
        self.assertEqual(copy.questions.get(text="Question source").question_type, Question.MULTIPLE)
        self.assertEqual(copy.questions.get(text="Question source").points, Decimal("2"))
        self.assertEqual(copy.questions.get(text="Question source").options.count(), 2)
        self.assertEqual(copy.questions.get(text="Question source").options.filter(is_correct=True).count(), 1)
        self.assertEqual(copy.enrollments.count(), 0)
        self.assertEqual(copy.attempts.count(), 0)

    def test_duplicate_exam_can_target_same_classroom(self):
        response = self.client.post(f"/teacher/exams/{self.exam.id}/duplicate/",
                                    {"classroom_id": str(self.classroom.id)})
        self.assertEqual(response.status_code, 302)
        copy = Exam.objects.exclude(pk=self.exam.pk).get()
        self.assertEqual(copy.classroom, self.classroom)

    def test_other_teacher_cannot_duplicate_exam(self):
        self.client.force_login(self.other_teacher)
        response = self.client.post(f"/teacher/exams/{self.exam.id}/duplicate/",
                                    {"classroom_id": str(self.other_classroom.id)})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Exam.objects.count(), 1)


class QuestionEditTests(TestCase):
    def setUp(self):
        self.teacher = make_user("edit_teacher", "TEACHER")
        self.exam = Exam.objects.create(title="Brouillon", teacher=self.teacher)
        self.question = make_question(self.exam, text="Ancien", points=Decimal("1"))
        self.client.force_login(self.teacher)

    def test_teacher_can_edit_question_and_options_in_draft(self):
        response = self.client.post(f"/teacher/exams/{self.exam.id}/question/{self.question.id}/edit/", {
            "text": "Nouvel énoncé", "kind": Question.MULTIPLE, "points": "2.5",
            "option_text": ["A", "B", "C", "", "", ""], "correct": ["0", "2"],
        })
        self.assertEqual(response.status_code, 302)
        self.question.refresh_from_db()
        self.assertEqual(self.question.text, "Nouvel énoncé")
        self.assertEqual(self.question.question_type, Question.MULTIPLE)
        self.assertEqual(self.question.points, Decimal("2.5"))
        options = list(self.question.options.order_by("position", "id"))
        self.assertEqual([o.text for o in options], ["A", "B", "C"])
        self.assertEqual([o.is_correct for o in options], [True, False, True])
        self.assertEqual([o.position for o in options], [1, 2, 3])

    def test_edit_question_rejects_invalid_question_without_changes(self):
        response = self.client.post(f"/teacher/exams/{self.exam.id}/question/{self.question.id}/edit/", {
            "text": "Invalide", "kind": Question.SINGLE, "points": "1",
            "option_text": ["A", "B", "", "", "", ""], "correct": ["0", "1"],
        })
        self.assertEqual(response.status_code, 200)
        self.question.refresh_from_db()
        self.assertEqual(self.question.text, "Ancien")
        self.assertEqual(self.question.options.count(), 2)
        self.assertEqual(self.question.options.filter(is_correct=True).count(), 1)

    def test_cannot_edit_published_question(self):
        self.exam.published = True
        self.exam.save(update_fields=["published"])
        response = self.client.post(f"/teacher/exams/{self.exam.id}/question/{self.question.id}/edit/", {
            "text": "Pirate", "kind": Question.SINGLE, "points": "1",
            "option_text": ["A", "B", "", "", "", ""], "correct": ["0"],
        })
        self.assertEqual(response.status_code, 302)
        self.question.refresh_from_db()
        self.assertEqual(self.question.text, "Ancien")

    def test_cannot_edit_question_when_attempt_exists(self):
        student = make_user("edit_student")
        Attempt.objects.create(exam=self.exam, student=student, question_order=[self.question.id],
                               global_deadline=timezone.now() + timedelta(minutes=10),
                               question_started_at=timezone.now(), question_deadline=timezone.now() + timedelta(minutes=1))
        response = self.client.post(f"/teacher/exams/{self.exam.id}/question/{self.question.id}/edit/", {
            "text": "Pirate", "kind": Question.SINGLE, "points": "1",
            "option_text": ["A", "B", "", "", "", ""], "correct": ["0"],
        })
        self.assertEqual(response.status_code, 302)
        self.question.refresh_from_db()
        self.assertEqual(self.question.text, "Ancien")

    def test_can_reorder_questions_with_up_and_down(self):
        second = Question.objects.create(exam=self.exam, text="Second", question_type=Question.SINGLE, points=Decimal("1"), position=2)
        Option.objects.create(question=second, text="A", is_correct=True, position=1)
        Option.objects.create(question=second, text="B", is_correct=False, position=2)

        response = self.client.post(f"/teacher/exams/{self.exam.id}/question/{second.id}/move/", {"direction": "up"})
        self.assertEqual(response.status_code, 302)
        self.exam.refresh_from_db()
        ordered = list(self.exam.questions.order_by("position", "id"))
        self.assertEqual([q.text for q in ordered], ["Second", "Ancien"])
        self.assertEqual([q.position for q in ordered], [1, 2])

        response = self.client.post(f"/teacher/exams/{self.exam.id}/question/{second.id}/move/", {"direction": "down"})
        self.assertEqual(response.status_code, 302)
        self.exam.refresh_from_db()
        ordered = list(self.exam.questions.order_by("position", "id"))
        self.assertEqual([q.text for q in ordered], ["Ancien", "Second"])
        self.assertEqual([q.position for q in ordered], [1, 2])


class ExamWindowTests(TestCase):
    def setUp(self):
        self.teacher = make_user("window_teacher", "TEACHER")
        self.student = make_user("window_student", number="WIN-1")
        self.classroom = Classroom.objects.create(name="Window", owner=self.teacher)
        ClassroomMembership.objects.create(classroom=self.classroom, user=self.teacher, role=ClassroomMembership.TEACHER)
        ClassroomMembership.objects.create(classroom=self.classroom, user=self.student, role=ClassroomMembership.STUDENT)
        self.exam = make_class_exam(self.teacher, self.classroom, published=True)
        make_question(self.exam)
        ExamEnrollment.objects.create(exam=self.exam, student=self.student, source="CLASS", code_verified=True)
        self.start_url = f"/student/exams/{self.exam.id}/start/"
        self.client.force_login(self.student)

    def test_start_rejected_before_opens_at(self):
        self.exam.opens_at = timezone.now() + timedelta(minutes=30)
        self.exam.save(update_fields=["opens_at"])
        response = self.client.post(self.start_url, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Attempt.objects.filter(exam=self.exam, student=self.student).exists())
        self.assertContains(response, "ouvrira")

    def test_start_allowed_during_window(self):
        now = timezone.now()
        self.exam.opens_at = now - timedelta(minutes=5)
        self.exam.closes_at = now + timedelta(minutes=30)
        self.exam.save(update_fields=["opens_at", "closes_at"])
        response = self.client.post(self.start_url, {"confirm": "on"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Attempt.objects.filter(exam=self.exam, student=self.student, status=Attempt.IN_PROGRESS).exists())

    def test_start_rejected_after_closes_at(self):
        self.exam.closes_at = timezone.now() - timedelta(minutes=1)
        self.exam.save(update_fields=["closes_at"])
        response = self.client.post(self.start_url, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Attempt.objects.filter(exam=self.exam, student=self.student).exists())
        self.assertContains(response, "fermé")

    def test_attempt_started_before_closes_at_continues(self):
        now = timezone.now()
        self.exam.opens_at = now - timedelta(minutes=5)
        self.exam.closes_at = now + timedelta(minutes=30)
        self.exam.save(update_fields=["opens_at", "closes_at"])
        self.client.post(self.start_url, {"confirm": "on"})
        attempt = Attempt.objects.get(exam=self.exam, student=self.student)
        attempt.global_deadline = now + timedelta(minutes=60)
        attempt.question_deadline = now + timedelta(minutes=30)
        attempt.save(update_fields=["global_deadline", "question_deadline"])

        self.exam.closes_at = timezone.now() - timedelta(seconds=1)
        self.exam.save(update_fields=["closes_at"])
        response = self.client.post(self.start_url, {"confirm": "on"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"/attempt/{attempt.id}/")
        self.assertEqual(self.client.get(f"/attempt/{attempt.id}/").status_code, 200)

    def test_student_sees_exam_window(self):
        self.exam.opens_at = timezone.now() + timedelta(minutes=30)
        self.exam.closes_at = timezone.now() + timedelta(hours=1)
        self.exam.save(update_fields=["opens_at", "closes_at"])
        # Interface façon Classroom (#42) : l'accueil mène à la page de l'examen, qui affiche la fenêtre.
        self.assertContains(self.client.get("/dashboard/student/"), f'href="/student/exams/{self.exam.id}/"')
        response = self.client.get(f"/student/exams/{self.exam.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ouvre le")
        self.assertContains(response, "Ferme le")
        self.assertContains(response, "ouvrira le")
        self.assertNotContains(response, "Commencer l'examen")

    def test_create_exam_with_window_and_results_published(self):
        self.client.force_login(self.teacher)
        now = timezone.now().replace(second=0, microsecond=0)
        opens_at = now + timedelta(hours=1)
        closes_at = now + timedelta(hours=2)
        response = self.client.post("/teacher/exams/create/", {
            "title": "Création", "description": "", "audience_mode": "LEVEL", "target_level": "L1",
            "duration": "60", "opens_at": opens_at.strftime("%Y-%m-%dT%H:%M"),
            "closes_at": closes_at.strftime("%Y-%m-%dT%H:%M"), "results_published": "on",
        })
        self.assertEqual(response.status_code, 302)
        exam = Exam.objects.get(title="Création")
        self.assertTrue(exam.results_published)
        self.assertIsNotNone(exam.opens_at)
        self.assertIsNotNone(exam.closes_at)
        self.assertLess(exam.opens_at, exam.closes_at)

    def test_create_exam_rejects_closes_before_opens(self):
        self.client.force_login(self.teacher)
        now = timezone.now().replace(second=0, microsecond=0)
        response = self.client.post("/teacher/exams/create/", {
            "title": "Invalid", "description": "", "audience_mode": "LEVEL", "target_level": "L1",
            "duration": "60", "opens_at": (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
            "closes_at": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Exam.objects.filter(title="Invalid").exists())

    def test_update_exam_window(self):
        self.client.force_login(self.teacher)
        now = timezone.now().replace(second=0, microsecond=0)
        opens_at = now + timedelta(hours=1)
        closes_at = now + timedelta(hours=2)
        response = self.client.post(f"/teacher/exams/{self.exam.id}/window/", {
            "opens_at": opens_at.strftime("%Y-%m-%dT%H:%M"),
            "closes_at": closes_at.strftime("%Y-%m-%dT%H:%M"),
        })
        self.assertEqual(response.status_code, 302)
        self.exam.refresh_from_db()
        self.assertIsNotNone(self.exam.opens_at)
        self.assertIsNotNone(self.exam.closes_at)
        self.assertLess(self.exam.opens_at, self.exam.closes_at)

        response = self.client.post(f"/teacher/exams/{self.exam.id}/window/", {"opens_at": "", "closes_at": ""})
        self.assertEqual(response.status_code, 302)
        self.exam.refresh_from_db()
        self.assertIsNone(self.exam.opens_at)
        self.assertIsNone(self.exam.closes_at)


# --------------------------------------------------------------------------- #
# Intégration avec la chaîne #22 → #45 et l'interface #42 (relecture de #38)
# --------------------------------------------------------------------------- #
class LifecycleIntegrationTests(TestCase):
    def setUp(self):
        self.teacher = make_user("int_teacher", "TEACHER")
        self.student = make_user("int_student", number="INT-1")
        self.classroom = Classroom.objects.create(name="Intégration", owner=self.teacher)
        ClassroomMembership.objects.create(classroom=self.classroom, user=self.teacher, role=ClassroomMembership.TEACHER)
        ClassroomMembership.objects.create(classroom=self.classroom, user=self.student, role=ClassroomMembership.STUDENT)
        self.exam = make_class_exam(self.teacher, self.classroom, multiple_scoring=Exam.ALL_OR_NOTHING)
        self.question = make_question(self.exam)
        self.enrollment = ExamEnrollment.objects.create(exam=self.exam, student=self.student, source="CLASS")

    def test_manual_closing_and_window_share_one_rule(self):
        self.assertEqual(self.exam.window_state(), "OPEN")
        self.exam.closed_at = timezone.now()
        self.assertEqual(self.exam.window_state(), "AFTER")
        self.exam.closed_at = None
        self.exam.opens_at = timezone.now() + timedelta(hours=1)
        self.assertEqual(self.exam.window_state(), "BEFORE")

    def test_access_code_can_be_validated_before_opening_but_not_after_closing(self):
        Exam.objects.filter(pk=self.exam.pk).update(opens_at=timezone.now() + timedelta(hours=1))
        self.client.force_login(self.student)
        self.client.post("/student/join-exam/", {"exam_id": self.exam.id, "access_code": self.exam.access_code})
        self.enrollment.refresh_from_db()
        self.assertTrue(self.enrollment.code_verified)
        self.assertFalse(Attempt.objects.exists())

        other = make_class_exam(self.teacher, self.classroom, title="Fermé", closes_at=timezone.now() - timedelta(minutes=1))
        make_question(other)
        ExamEnrollment.objects.create(exam=other, student=self.student, source="CLASS")
        self.client.post("/student/join-exam/", {"exam_id": other.id, "access_code": other.access_code})
        self.assertFalse(ExamEnrollment.objects.get(exam=other, student=self.student).code_verified)

    def test_results_cannot_be_published_while_students_compose(self):
        now = timezone.now()
        Attempt.objects.create(exam=self.exam, student=self.student, question_order=[self.question.id],
                               global_deadline=now + timedelta(minutes=30), question_started_at=now,
                               question_deadline=now + timedelta(minutes=10))
        self.client.force_login(self.teacher)
        self.client.post(f"/teacher/exams/{self.exam.id}/results/publish/")
        self.exam.refresh_from_db()
        self.assertFalse(self.exam.results_published)

    def test_publishing_results_is_journaled(self):
        from .models import AuditLog
        self.client.force_login(self.teacher)
        self.client.post(f"/teacher/exams/{self.exam.id}/results/publish/")
        self.exam.refresh_from_db()
        self.assertTrue(self.exam.results_published)
        self.assertTrue(AuditLog.objects.filter(action="Notes publiées").exists())

    def test_duplicate_keeps_scoring_rule(self):
        self.client.force_login(self.teacher)
        self.client.post(f"/teacher/exams/{self.exam.id}/duplicate/", {"classroom_id": self.classroom.id})
        copy = Exam.objects.exclude(pk=self.exam.pk).get()
        self.assertEqual(copy.multiple_scoring, Exam.ALL_OR_NOTHING)
        self.assertFalse(copy.published)

    def test_student_finds_published_grade_on_exam_page_even_after_security_closing(self):
        attempt = make_completed_attempt(self.exam, self.student, self.question)
        Attempt.objects.filter(pk=attempt.pk).update(status=Attempt.TERMINATED_SECURITY)
        self.client.force_login(self.student)
        page = self.client.get(f"/student/exams/{self.exam.id}/")
        self.assertContains(page, "Note pas encore publiée")
        Exam.objects.filter(pk=self.exam.pk).update(results_published=True)
        page = self.client.get(f"/student/exams/{self.exam.id}/")
        self.assertContains(page, "20,00")
