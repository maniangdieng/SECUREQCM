"""Tests de l'issue #23 : passation fiable (cahier des charges §6 et §7.3)."""
import threading
from datetime import timedelta

from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from .models import Attempt, Exam, ExamEnrollment, Option, Question, Response, SecurityEvent
from .tests_examen_securite import ExamFixture, make_user


def past():
    return timezone.now() - timedelta(seconds=1)


# --------------------------------------------------------------------------- #
# Consignes avant le démarrage
# --------------------------------------------------------------------------- #
class InstructionsTests(TestCase):
    def setUp(self):
        self.teacher = make_user("c_teacher", "TEACHER")
        self.student = make_user("c_student")
        self.exam = Exam.objects.create(title="Consignes", teacher=self.teacher, published=True,
                                        audience_mode="LIST", duration_minutes=25)
        for n in (1, 2):
            q = Question.objects.create(exam=self.exam, text=f"Q{n}", position=n)
            Option.objects.create(question=q, text="A", is_correct=True)
            Option.objects.create(question=q, text="B")
        self.enrollment = ExamEnrollment.objects.create(exam=self.exam, student=self.student, code_verified=True)
        self.client.force_login(self.student)
        self.url = f"/student/exams/{self.exam.id}/start/"

    def test_instructions_are_shown_before_any_attempt_exists(self):
        page = self.client.get(self.url)
        for text in ("25 minutes", "2 questions", "Une seule tentative", "Choix unique", "Choix multiples",
                     "plein écran", 'name="confirm"'):
            self.assertContains(page, text)
        self.assertFalse(Attempt.objects.exists())

    def test_start_without_confirmation_creates_nothing(self):
        page = self.client.post(self.url)
        self.assertContains(page, "Cochez la case")
        self.assertFalse(Attempt.objects.exists())

    def test_confirmed_start_creates_the_attempt_and_starts_the_clock(self):
        response = self.client.post(self.url, {"confirm": "on"})
        attempt = Attempt.objects.get()
        self.assertRedirects(response, f"/attempt/{attempt.id}/", fetch_redirect_response=False)
        remaining = (attempt.global_deadline - timezone.now()).total_seconds()
        self.assertAlmostEqual(remaining, 25 * 60, delta=5)

    def test_instructions_of_a_started_exam_redirect_to_the_attempt(self):
        self.client.post(self.url, {"confirm": "on"})
        response = self.client.get(self.url)
        self.assertRedirects(response, f"/attempt/{Attempt.objects.get().id}/", fetch_redirect_response=False)

    def test_instructions_require_the_exam_code(self):
        ExamEnrollment.objects.filter(pk=self.enrollment.pk).update(code_verified=False)
        self.assertRedirects(self.client.get(self.url), "/dashboard/student/", fetch_redirect_response=False)

    def test_dashboard_links_to_the_instructions(self):
        self.assertContains(self.client.get("/dashboard/student/"), f'href="{self.url}"')


# --------------------------------------------------------------------------- #
# Sauvegarde automatique
# --------------------------------------------------------------------------- #
class AutosaveTests(ExamFixture):
    def save(self, question=None, options=None, correct=True):
        question = question or self.current_question()
        if options is None:
            options = [question.options.get(is_correct=correct).id]
        return self.client.post(f"/attempt/{self.attempt.id}/save.json",
                                {"question_id": question.id, "option": options})

    def draft(self, question):
        return Response.objects.get(attempt=self.attempt, question=question)

    def test_save_stores_the_selection_without_advancing(self):
        q = self.current_question()
        self.assertEqual(self.save(q).json(), {"status": "IN_PROGRESS", "saved": True})
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.current_index, 0)
        self.assertEqual(self.draft(q).selected_option_ids, [q.options.get(is_correct=True).id])
        self.assertFalse(self.draft(q).auto_submitted)

    def test_saved_selection_is_restored_when_the_page_is_reloaded(self):
        q = self.current_question()
        self.save(q)
        state = self.client.get(f"/attempt/{self.attempt.id}/").context["state"]
        self.assertEqual(state["question"]["selected"], [q.options.get(is_correct=True).id])

    def test_draft_is_kept_when_the_question_expires(self):
        q = self.current_question()
        self.save(q)
        Attempt.objects.filter(pk=self.attempt.pk).update(question_deadline=past())
        self.client.get(f"/attempt/{self.attempt.id}/")
        self.assertEqual(self.draft(q).selected_option_ids, [q.options.get(is_correct=True).id])
        self.assertTrue(self.draft(q).auto_submitted)

    def test_late_answer_does_not_overwrite_the_draft(self):
        q = self.current_question()
        self.save(q)
        Attempt.objects.filter(pk=self.attempt.pk).update(question_deadline=past())
        self.answer_json(q, correct=False)
        self.assertEqual(self.draft(q).selected_option_ids, [q.options.get(is_correct=True).id])

    def test_draft_is_kept_and_counted_when_the_exam_time_runs_out(self):
        q = self.current_question()
        self.save(q)
        Attempt.objects.filter(pk=self.attempt.pk).update(global_deadline=past(), question_deadline=past())
        page = self.client.get(f"/attempt/{self.attempt.id}/")
        self.assertTrue(self.draft(q).auto_submitted)
        self.assertEqual(page.context["score"], q.points)

    def test_final_answer_replaces_the_draft(self):
        q = self.current_question()
        self.save(q, correct=True)
        self.answer_json(q, correct=False)
        self.assertEqual(self.draft(q).selected_option_ids, [q.options.get(is_correct=False).id])
        self.assertEqual(Response.objects.filter(attempt=self.attempt, question=q).count(), 1)

    def test_save_for_a_past_question_records_nothing(self):
        first = self.current_question()
        self.answer_json(first, correct=True)
        response = self.save(first, correct=False)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["index"], 2)
        self.assertEqual(self.draft(first).selected_option_ids, [first.options.get(is_correct=True).id])

    def test_save_validates_the_selection(self):
        q = self.current_question()
        self.assertEqual(self.save(q, options=["abc"]).status_code, 400)
        self.assertEqual(self.save(q, options=[999999]).status_code, 403)
        self.assertEqual(self.save(q, options=[o.id for o in q.options.all()]).status_code, 403)  # choix unique
        self.assertFalse(Response.objects.exists())

    def test_save_on_a_closed_attempt_is_refused(self):
        q = self.current_question()
        Attempt.objects.filter(pk=self.attempt.pk).update(status=Attempt.TERMINATED_SECURITY)
        self.assertEqual(self.save(q).status_code, 409)
        self.assertFalse(Response.objects.exists())

    def test_other_student_cannot_save(self):
        q = self.current_question()
        self.client.force_login(make_user("intrus_brouillon"))
        self.assertEqual(self.save(q).status_code, 404)

    def test_page_announces_the_save_status(self):
        page = self.client.get(f"/attempt/{self.attempt.id}/")
        self.assertContains(page, 'id="saveStatus" role="status" aria-live="polite"')
        self.assertContains(page, f"/attempt/{self.attempt.id}/save.json")

    def test_page_asks_to_confirm_the_final_submission(self):
        page = self.client.get(f"/attempt/{self.attempt.id}/")
        self.assertContains(page, '<dialog id="confirmDialog">')


# --------------------------------------------------------------------------- #
# Session expirée
# --------------------------------------------------------------------------- #
class ExpiredSessionTests(ExamFixture):
    def test_json_routes_answer_401_instead_of_redirecting(self):
        self.client.logout()
        for route in ("answer.json", "save.json", "event/"):
            response = self.client.post(f"/attempt/{self.attempt.id}/{route}", {"event": "TAB_SWITCH"})
            self.assertEqual(response.status_code, 401, route)
            self.assertEqual(response.json()["error"], "session_expired")
        self.assertFalse(SecurityEvent.objects.exists())


# --------------------------------------------------------------------------- #
# Clôture des tentatives expirées, même sans retour de l'étudiant
# --------------------------------------------------------------------------- #
class ExpiredAttemptClosureTests(ExamFixture):
    def expire(self):
        self.deadline = timezone.now() - timedelta(hours=2)
        Attempt.objects.filter(pk=self.attempt.pk).update(global_deadline=self.deadline,
                                                          question_deadline=self.deadline)

    def assert_closed(self):
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, Attempt.TIME_EXPIRED)
        self.assertEqual(self.attempt.ended_at, self.deadline)

    def test_command_closes_expired_attempts_only(self):
        call_command("close_expired_attempts", verbosity=0)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, Attempt.IN_PROGRESS)
        self.expire()
        call_command("close_expired_attempts", verbosity=0)
        self.assert_closed()

    def test_student_dashboard_closes_expired_attempts(self):
        self.expire()
        self.client.get("/dashboard/student/")
        self.assert_closed()

    def test_teacher_pages_close_expired_attempts(self):
        self.client.force_login(self.teacher)
        for url in (f"/teacher/exams/{self.exam.id}/results/",
                    f"/teacher/exams/{self.exam.id}/results/export/",
                    f"/teacher/attempts/{self.attempt.id}/results/"):
            Attempt.objects.filter(pk=self.attempt.pk).update(status=Attempt.IN_PROGRESS, ended_at=None)
            self.expire()
            self.assertEqual(self.client.get(url).status_code, 200, url)
            self.assert_closed()


# --------------------------------------------------------------------------- #
# Une seule tentative en cours
# --------------------------------------------------------------------------- #
class SingleAttemptTests(ExamFixture):
    def duplicate(self):
        now = timezone.now()
        return Attempt.objects.create(exam=self.exam, student=self.student, global_deadline=now,
                                      question_started_at=now, question_deadline=now)

    def test_database_refuses_a_second_attempt_in_progress(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.duplicate()

    def test_resume_is_refused_while_another_attempt_is_in_progress(self):
        Attempt.objects.filter(pk=self.attempt.pk).update(status=Attempt.TERMINATED_SECURITY, ended_at=timezone.now())
        other = self.duplicate()
        Attempt.objects.filter(pk=other.pk).update(global_deadline=timezone.now() + timedelta(minutes=5))
        self.client.force_login(self.teacher)
        response = self.client.post(f"/teacher/attempts/{self.attempt.id}/authorize-resume/",
                                    {"reason": "Coupure"}, follow=True)
        self.assertContains(response, "Une autre tentative est déjà en cours")
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, Attempt.TERMINATED_SECURITY)

    def test_unlocked_legacy_answer_route_is_gone(self):
        self.assertEqual(self.client.post(f"/attempt/{self.attempt.id}/answer/").status_code, 404)


class DuplicateAttemptMigrationTests(TransactionTestCase):
    """Une base existante contenant des doublons doit pouvoir migrer sans perdre de données."""
    before = [("qcm", "0006_exam_teacher_protect")]

    def test_older_duplicates_are_marked_interrupted(self):
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes("qcm")
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        MigrationExecutor(connection).migrate(self.before)
        apps = MigrationExecutor(connection).loader.project_state(self.before).apps
        user = apps.get_model("auth", "User").objects.create(username="doublon")
        exam = apps.get_model("qcm", "Exam").objects.create(title="D", teacher_id=user.id)
        Old = apps.get_model("qcm", "Attempt")
        now = timezone.now()
        first, second = [Old.objects.create(exam=exam, student_id=user.id, global_deadline=now,
                                            question_started_at=now, question_deadline=now) for _ in range(2)]
        Old.objects.filter(pk=first.pk).update(started_at=now - timedelta(hours=1))
        MigrationExecutor(connection).migrate(latest)
        statuses = dict(Attempt.objects.values_list("pk", "status"))
        self.assertEqual(statuses, {first.pk: Attempt.INTERRUPTED, second.pk: Attempt.IN_PROGRESS})


# --------------------------------------------------------------------------- #
# Requêtes simultanées (verrous de lignes : PostgreSQL uniquement)
# --------------------------------------------------------------------------- #
@skipUnlessDBFeature("has_select_for_update")
class ConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.teacher = make_user("p_teacher", "TEACHER")
        self.exam = Exam.objects.create(title="P", teacher=self.teacher, published=True,
                                        audience_mode="LIST", shuffle_questions=False)
        for n in (1, 2):
            self.question = Question.objects.create(exam=self.exam, text=f"Q{n}", position=3 - n)
            self.good = Option.objects.create(question=self.question, text="A", is_correct=True)
            Option.objects.create(question=self.question, text="B")
        self.student = self.enroll("p_student")

    def enroll(self, username):
        student = make_user(username)
        ExamEnrollment.objects.create(exam=self.exam, student=student, code_verified=True)
        return student

    def start(self, student):
        client = Client()
        client.force_login(student)
        client.post(f"/student/exams/{self.exam.id}/start/", {"confirm": "on"})
        return client, Attempt.objects.get(student=student)

    def in_thread(self, call):
        result = {}

        def run():
            try:
                result["response"] = call()
            finally:
                connection.close()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread, result

    def test_simultaneous_starts_create_a_single_attempt(self):
        clients = [Client(), Client()]
        for client in clients:
            client.force_login(self.student)
        url = f"/student/exams/{self.exam.id}/start/"
        with transaction.atomic():
            ExamEnrollment.objects.select_for_update().get(student=self.student)
            runs = [self.in_thread(lambda c=c: c.post(url, {"confirm": "on"})) for c in clients]
            for thread, _ in runs:
                thread.join(1)
                self.assertTrue(thread.is_alive(), "le démarrage n'attend pas le verrou")
        for thread, result in runs:
            thread.join(10)
            self.assertEqual(result["response"].status_code, 302)
        self.assertEqual(Attempt.objects.count(), 1)

    def test_no_route_overrides_a_closure_made_while_it_was_waiting(self):
        client, attempt = self.start(self.student)
        question_id = attempt.question_order[0]
        option_id = attempt.option_orders[str(question_id)][0]
        data = {"question_id": question_id, "option": [option_id], "event": "TAB_SWITCH"}
        base = f"/attempt/{attempt.id}/"
        routes = {
            "page": lambda: client.get(base),
            "answer": lambda: client.post(base + "answer.json", data),
            "save": lambda: client.post(base + "save.json", data),
            "event": lambda: client.post(base + "event/", data),
        }
        for name, call in routes.items():
            with self.subTest(name):
                Response.objects.filter(attempt=attempt).delete()
                Attempt.objects.filter(pk=attempt.pk).update(
                    status=Attempt.IN_PROGRESS, current_index=1, question_deadline=past(),
                    global_deadline=timezone.now() + timedelta(minutes=5))
                with transaction.atomic():
                    Attempt.objects.select_for_update().get(pk=attempt.pk)
                    thread, _ = self.in_thread(call)
                    thread.join(1)
                    self.assertTrue(thread.is_alive(), "la route n'attend pas le verrou")
                    Attempt.objects.filter(pk=attempt.pk).update(status=Attempt.TERMINATED_SECURITY)
                thread.join(10)
                attempt.refresh_from_db()
                self.assertEqual(attempt.status, Attempt.TERMINATED_SECURITY)
                self.assertFalse(Response.objects.filter(attempt=attempt).exists())

    def test_answering_does_not_lock_the_exam_row(self):
        """Sinon les étudiants d'un même examen se mettent en file les uns derrière les autres."""
        client, attempt = self.start(self.student)
        question_id = attempt.question_order[0]
        with transaction.atomic():
            Exam.objects.select_for_update(no_key=True).get(pk=self.exam.pk)
            thread, result = self.in_thread(lambda: client.post(
                f"/attempt/{attempt.id}/answer.json", {"question_id": question_id}))
            thread.join(5)
            blocked = thread.is_alive()
        thread.join(10)
        self.assertFalse(blocked, "la réponse attend un verrou sur la ligne de l'examen")
        self.assertEqual(result["response"].status_code, 200)
