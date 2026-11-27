"""Tests de l'issue #25 : règle de notation, ordre, clôture et archivage (cahier §2.2, §4, §8)."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from .models import Attempt, Classroom, Exam, ExamEnrollment, Option, Question, Response
from .services import calculate_score, enroll_student_in_class_exams, grade_summary
from .tests_examen_securite import make_user

PARTIAL_TEXT = "Choix multiples : points partiels"
ALL_OR_NOTHING_TEXT = "Choix multiples : tout ou rien"


class NotationFixture(TestCase):
    """Une question à choix multiples sur 2 points (A et B justes, C fausse) puis une à choix unique sur 1 point."""
    exam_settings = {}

    def setUp(self):
        self.teacher = make_user("n_teacher", "TEACHER")
        self.student = make_user("n_student")
        self.exam = Exam.objects.create(title="Notation", teacher=self.teacher, published=True, audience_mode="LIST",
                                        duration_minutes=10, shuffle_questions=False, shuffle_answers=False,
                                        **self.exam_settings)
        self.multi = Question.objects.create(exam=self.exam, text="Multiple", position=1, points=2,
                                             question_type=Question.MULTIPLE)
        self.a, self.b, self.c = [Option.objects.create(question=self.multi, text=t, is_correct=ok, position=n)
                                  for n, (t, ok) in enumerate([("A", True), ("B", True), ("C", False)], 1)]
        self.single = Question.objects.create(exam=self.exam, text="Unique", position=2, points=1)
        self.yes = Option.objects.create(question=self.single, text="Oui", is_correct=True, position=1)
        self.no = Option.objects.create(question=self.single, text="Non", position=2)
        self.enrollment = ExamEnrollment.objects.create(exam=self.exam, student=self.student, code_verified=True)
        self.client.force_login(self.student)

    def start(self):
        self.client.post(f"/student/exams/{self.exam.id}/start/", {"confirm": "on"})
        return Attempt.objects.get(student=self.student, status=Attempt.IN_PROGRESS)

    def answer(self, attempt, question, *options):
        return self.client.post(f"/attempt/{attempt.id}/answer.json",
                                {"question_id": question.id, "option": [o.id for o in options]})

    def sit(self, multi, single=()):
        attempt = self.start()
        self.answer(attempt, self.multi, *multi)
        self.answer(attempt, self.single, *single)
        attempt.refresh_from_db()
        return attempt

    def set_exam(self, **fields):
        Exam.objects.filter(pk=self.exam.pk).update(**fields)


# --------------------------------------------------------------------------- #
# Les deux règles de notation
# --------------------------------------------------------------------------- #
class PartialScoringTests(NotationFixture):
    def test_partial_scoring_stays_the_default(self):
        self.assertEqual(self.exam.multiple_scoring, Exam.PARTIAL)
        self.assertEqual(calculate_score(self.sit([self.a])), Decimal("1"))

    def test_finished_page_rounds_a_repeating_partial_score(self):
        third = Option.objects.create(question=self.multi, text="D", is_correct=True, position=4)
        attempt = self.sit([self.a])  # 1/3 de 2 points
        self.assertNotEqual(third.id, None)
        page = self.client.get(f"/attempt/{attempt.id}/")
        self.assertContains(page, "Score : 0,67 / 3,00 points")


class AllOrNothingScoringTests(NotationFixture):
    exam_settings = {"multiple_scoring": "ALL_OR_NOTHING"}

    def test_incomplete_selection_earns_nothing(self):
        self.assertEqual(calculate_score(self.sit([self.a])), Decimal("0"))

    def test_extra_wrong_option_earns_nothing(self):
        self.assertEqual(calculate_score(self.sit([self.a, self.b, self.c])), Decimal("0"))

    def test_exact_selection_earns_all_points(self):
        self.assertEqual(calculate_score(self.sit([self.a, self.b], [self.yes])), Decimal("3"))

    def test_single_choice_is_not_affected(self):
        self.assertEqual(calculate_score(self.sit([], [self.yes])), Decimal("1"))

    def test_results_page_and_csv_use_the_rule(self):
        attempt = self.sit([self.a], [self.yes])  # 1 / 3 points
        self.client.force_login(self.teacher)
        row = self.client.get(f"/teacher/exams/{self.exam.id}/results/").context["rows"][0]
        self.assertEqual(row["final_grade"], Decimal("6.67"))
        csv = self.client.get(f"/teacher/exams/{self.exam.id}/results/export/").content.decode("utf-8-sig")
        self.assertIn(";1.00;3.00;33.3;6.67", csv)
        self.assertEqual(grade_summary(attempt)["final_grade"], Decimal("6.67"))


# --------------------------------------------------------------------------- #
# Règle et barème figés au démarrage
# --------------------------------------------------------------------------- #
class GradingSnapshotTests(NotationFixture):
    def change_everything(self):
        self.set_exam(multiple_scoring=Exam.ALL_OR_NOTHING)
        Question.objects.filter(pk=self.multi.pk).update(points=10)
        Option.objects.filter(pk=self.a.pk).update(is_correct=False)
        Option.objects.filter(pk=self.c.pk).update(is_correct=True)

    def test_later_changes_do_not_alter_the_grade_of_an_attempt(self):
        attempt = self.sit([self.a], [self.yes])
        self.change_everything()
        grade = grade_summary(Attempt.objects.get(pk=attempt.pk))
        self.assertEqual((grade["score"], grade["max_score"]), (Decimal("2"), Decimal("3")))

    def test_copy_shows_the_frozen_correct_answers(self):
        attempt = self.sit([self.a, self.b])
        self.change_everything()
        self.client.force_login(self.teacher)
        page = self.client.get(f"/teacher/attempts/{attempt.id}/results/")
        detail = page.context["details"][0]
        self.assertEqual(detail["correct"], {self.a.id, self.b.id})
        self.assertTrue(detail["is_right"])
        self.assertEqual(page.context["max_score"], Decimal("3"))

    def test_attempt_without_snapshot_is_graded_from_the_exam(self):
        attempt = self.sit([self.a])
        Attempt.objects.filter(pk=attempt.pk).update(grading_snapshot={})
        Question.objects.filter(pk=self.multi.pk).update(points=4)
        grade = grade_summary(Attempt.objects.get(pk=attempt.pk))
        self.assertEqual((grade["score"], grade["max_score"]), (Decimal("2"), Decimal("5")))

    def test_correct_answers_are_never_sent_to_the_student(self):
        attempt = self.start()
        page = self.client.get(f"/attempt/{attempt.id}/")
        self.assertNotIn("correct", str(page.context["state"]))


# --------------------------------------------------------------------------- #
# Règle annoncée avant et pendant l'examen
# --------------------------------------------------------------------------- #
class AnnouncementTests(NotationFixture):
    def instructions(self):
        return self.client.get(f"/student/exams/{self.exam.id}/start/")

    def test_instructions_announce_partial_scoring(self):
        page = self.instructions()
        self.assertContains(page, PARTIAL_TEXT)
        self.assertNotContains(page, ALL_OR_NOTHING_TEXT)

    def test_instructions_announce_all_or_nothing(self):
        self.set_exam(multiple_scoring=Exam.ALL_OR_NOTHING)
        page = self.instructions()
        self.assertContains(page, ALL_OR_NOTHING_TEXT)
        self.assertNotContains(page, PARTIAL_TEXT)

    def test_rule_of_the_attempt_is_recalled_on_multiple_questions_only(self):
        self.set_exam(multiple_scoring=Exam.ALL_OR_NOTHING)
        attempt = self.start()
        self.set_exam(multiple_scoring=Exam.PARTIAL)
        state = self.client.get(f"/attempt/{attempt.id}/").context["state"]
        self.assertIn(ALL_OR_NOTHING_TEXT, state["question"]["scoring_rule"])
        following = self.answer(attempt, self.multi, self.a).json()
        self.assertEqual(following["question"]["scoring_rule"], "")


# --------------------------------------------------------------------------- #
# Réglages à la création et modification
# --------------------------------------------------------------------------- #
class ExamSettingsTests(TestCase):
    FIXED = {"multiple_scoring": "ALL_OR_NOTHING", "question_order": "fixed", "answer_order": "fixed"}

    def setUp(self):
        self.teacher = make_user("p_teacher", "TEACHER")
        self.client.force_login(self.teacher)

    def create(self, **extra):
        self.client.post("/teacher/exams/create/", {"title": "Réglages", "audience_mode": "LEVEL",
                                                    "target_level": "L1", "duration": 10, **extra})
        return Exam.objects.filter(title="Réglages").first()

    def settings_of(self, exam):
        exam.refresh_from_db()
        return exam.multiple_scoring, exam.shuffle_questions, exam.shuffle_answers

    def update(self, exam, data):
        return self.client.post(f"/teacher/exams/{exam.id}/settings/", data)

    def test_creation_defaults_to_partial_and_random_order(self):
        self.assertEqual(self.settings_of(self.create()), ("PARTIAL", True, True))

    def test_creation_stores_the_chosen_settings(self):
        self.assertEqual(self.settings_of(self.create(**self.FIXED)), ("ALL_OR_NOTHING", False, False))

    def test_creation_refuses_an_unknown_value(self):
        for bad in ({"multiple_scoring": "FREE"}, {"question_order": "x"}, {"answer_order": ""}):
            self.assertIsNone(self.create(**bad), bad)

    def test_creation_forms_offer_the_settings(self):
        classroom = Classroom.objects.create(name="C", owner=self.teacher)
        for url in ("/dashboard/teacher/", f"/classes/{classroom.id}/"):
            page = self.client.get(url)
            for name in self.FIXED:
                self.assertContains(page, f'name="{name}"')

    def test_settings_can_change_before_any_attempt(self):
        exam = self.create()
        self.assertContains(self.client.get(f"/teacher/exams/{exam.id}/"), 'name="multiple_scoring"')
        self.update(exam, self.FIXED)
        self.assertEqual(self.settings_of(exam), ("ALL_OR_NOTHING", False, False))
        page = self.client.get(f"/teacher/exams/{exam.id}/")
        self.assertContains(page, '<option value="ALL_OR_NOTHING" selected>', html=False)

    def test_settings_are_locked_once_an_attempt_exists(self):
        exam = self.create()
        now = timezone.now()
        Attempt.objects.create(exam=exam, student=make_user("p_student"), question_order=[],
                               global_deadline=now, question_started_at=now, question_deadline=now)
        self.update(exam, self.FIXED)
        self.assertEqual(self.settings_of(exam), ("PARTIAL", True, True))
        self.assertNotContains(self.client.get(f"/teacher/exams/{exam.id}/"), 'name="multiple_scoring"')

    def test_invalid_update_changes_nothing(self):
        exam = self.create()
        self.update(exam, {**self.FIXED, "multiple_scoring": "FREE"})
        self.assertEqual(self.settings_of(exam), ("PARTIAL", True, True))

    def test_only_a_manager_of_the_exam_can_change_settings(self):
        exam = self.create()
        self.client.force_login(make_user("p_other", "TEACHER"))
        self.assertEqual(self.update(exam, self.FIXED).status_code, 403)
        self.assertEqual(self.settings_of(exam), ("PARTIAL", True, True))


class FixedOrderTests(NotationFixture):
    def test_fixed_order_follows_the_positions(self):
        attempt = self.start()
        self.assertEqual(attempt.question_order, [self.multi.id, self.single.id])
        self.assertEqual(attempt.option_orders[str(self.multi.id)], [self.a.id, self.b.id, self.c.id])


# --------------------------------------------------------------------------- #
# Clôture par l'enseignant
# --------------------------------------------------------------------------- #
class CloseExamTests(NotationFixture):
    def close(self, user=None):
        self.client.force_login(user or self.teacher)
        response = self.client.post(f"/teacher/exams/{self.exam.id}/close/")
        self.client.force_login(self.student)
        self.exam.refresh_from_db()
        return response

    def test_teacher_closes_a_published_exam(self):
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(f"/teacher/exams/{self.exam.id}/"), f"/teacher/exams/{self.exam.id}/close/")
        self.close()
        self.assertIsNotNone(self.exam.closed_at)
        self.assertEqual(self.exam.state_label, "Clôturé")

    def test_draft_cannot_be_closed(self):
        self.set_exam(published=False)
        self.close()
        self.assertIsNone(self.exam.closed_at)

    def test_students_and_other_teachers_cannot_close(self):
        for user in (self.student, make_user("n_other", "TEACHER")):
            self.assertEqual(self.close(user).status_code, 403)
        self.assertIsNone(self.exam.closed_at)

    def test_closing_requires_post(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(f"/teacher/exams/{self.exam.id}/close/").status_code, 405)

    def test_closed_exam_cannot_be_started(self):
        self.close()
        page = self.client.post(f"/student/exams/{self.exam.id}/start/", {"confirm": "on"}, follow=True)
        self.assertContains(page, "clôturé par l&#x27;enseignant")
        self.assertFalse(Attempt.objects.exists())

    def test_closed_exam_refuses_the_access_code(self):
        ExamEnrollment.objects.filter(pk=self.enrollment.pk).update(code_verified=False)
        self.close()
        self.client.post("/student/join-exam/", {"exam_id": self.exam.id, "access_code": self.exam.access_code})
        self.assertFalse(ExamEnrollment.objects.get(pk=self.enrollment.pk).code_verified)

    def test_closed_exam_leaves_the_dashboard_of_students_who_never_started(self):
        self.close()
        page = self.client.get("/dashboard/student/")  # le titre seul figure encore dans le message flash
        self.assertEqual((page.context["todo_exams"], page.context["done_exams"]), ([], []))

    def test_started_attempt_can_be_finished_after_closing(self):
        attempt = self.start()
        self.close()
        self.assertContains(self.client.get("/dashboard/student/"), f'href="/student/exams/{self.exam.id}/start/"')
        self.assertRedirects(self.client.get(f"/student/exams/{self.exam.id}/start/"), f"/attempt/{attempt.id}/",
                             fetch_redirect_response=False)
        self.answer(attempt, self.multi, self.a)
        self.assertEqual(self.answer(attempt, self.single, self.yes).json()["status"], Attempt.COMPLETED)

    def test_interrupted_attempt_cannot_restart_after_closing(self):
        attempt = self.start()
        Attempt.objects.filter(pk=attempt.pk).update(status=Attempt.INTERRUPTED)
        self.close()
        self.client.post(f"/student/exams/{self.exam.id}/start/", {"confirm": "on"})
        self.assertEqual(Attempt.objects.count(), 1)

    def test_new_class_member_is_not_assigned_to_a_closed_exam(self):
        classroom = Classroom.objects.create(name="C", owner=self.teacher)
        self.set_exam(classroom=classroom, audience_mode="CLASS")
        self.close()
        newcomer = make_user("n_newcomer")
        enroll_student_in_class_exams(newcomer, classroom)
        self.assertFalse(ExamEnrollment.objects.filter(student=newcomer).exists())


# --------------------------------------------------------------------------- #
# Archivage par l'enseignant
# --------------------------------------------------------------------------- #
class TeacherArchiveTests(NotationFixture):
    def archive(self, user=None):
        self.client.force_login(user or self.teacher)
        response = self.client.post(f"/teacher/exams/{self.exam.id}/archive/")
        self.exam.refresh_from_db()
        return response

    def test_teacher_archives_an_exam_with_results(self):
        self.sit([self.a])
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(f"/teacher/exams/{self.exam.id}/"), f"/teacher/exams/{self.exam.id}/archive/")
        response = self.archive()
        self.assertRedirects(response, f"/teacher/exams/{self.exam.id}/", fetch_redirect_response=False)
        self.assertTrue(self.exam.is_archived)
        self.assertEqual(self.exam.archived_by, self.teacher)
        self.assertEqual(Response.objects.count(), 2)

    def test_archived_standalone_exam_stays_reachable_by_its_teacher(self):
        self.sit([self.a])
        self.archive()
        page = self.client.get("/dashboard/teacher/")
        self.assertContains(page, f'href="/teacher/exams/{self.exam.id}/results/"')
        self.assertContains(page, "Archivé")

    def test_exam_without_attempts_is_deleted_rather_than_archived(self):
        self.archive()
        self.assertFalse(self.exam.is_archived)

    def test_teacher_cannot_archive_while_an_attempt_is_running(self):
        self.start()
        self.archive()
        self.assertFalse(self.exam.is_archived)

    def test_expired_attempt_does_not_block_archiving(self):
        attempt = self.start()
        past = timezone.now() - timedelta(seconds=1)
        Attempt.objects.filter(pk=attempt.pk).update(global_deadline=past, question_deadline=past)
        self.archive()
        self.assertTrue(self.exam.is_archived)

    def test_students_and_other_teachers_cannot_archive(self):
        self.sit([self.a])
        for user in (self.student, make_user("n_other", "TEACHER")):
            self.assertEqual(self.archive(user).status_code, 403)
        self.assertFalse(self.exam.is_archived)
