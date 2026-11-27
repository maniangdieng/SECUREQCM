"""Tests de l'issue #27 : statistiques par statut, détail des réponses, colonnes d'export, page imprimable."""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from .models import Attempt, Question, Response, SecurityEvent
from .services import result_rows, RESULT_HEADER
from .tests_examen_securite import ExamFixture, make_user

RIGHT, WRONG, BLANK = True, False, None


class ResultsFixture(ExamFixture):
    question_count = 4

    def setUp(self):
        super().setUp()
        self.questions = list(Question.objects.filter(exam=self.exam).order_by("position"))
        self.client.force_login(self.teacher)
        self.base = f"/teacher/exams/{self.exam.id}/results/"

    def copy(self, name, answers, status=Attempt.COMPLETED):
        attempt = Attempt.objects.create(
            exam=self.exam, student=make_user(name), status=status, question_order=self.attempt.question_order,
            grading_snapshot=self.attempt.grading_snapshot, global_deadline=self.attempt.global_deadline,
            question_started_at=self.attempt.question_started_at, question_deadline=self.attempt.question_deadline)
        for question, answer in zip(self.questions, answers):
            selected = [] if answer is BLANK else [question.options.get(is_correct=answer).id]
            Response.objects.create(attempt=attempt, question=question, selected_option_ids=selected)
        return attempt

    def row(self, attempt):
        username = attempt.student.username
        for values in result_rows(self.exam):
            row = dict(zip(RESULT_HEADER, values))
            if row["Identifiant"] == username:
                return row
        self.fail(f"copie absente de l'export : {username}")


class StatisticsTests(ResultsFixture):
    def summary(self):
        return self.client.get(self.base).context["summary"]

    def test_copies_are_counted_by_status(self):
        self.copy("r_done1", [RIGHT] * 4)
        self.copy("r_done2", [WRONG] * 4)
        self.copy("r_late", [RIGHT], status=Attempt.TIME_EXPIRED)
        self.copy("r_cheat", [RIGHT], status=Attempt.TERMINATED_SECURITY)
        # La copie du fixture est en cours.
        self.assertEqual(dict(self.summary()["status_counts"]),
                         {"En cours": 1, "Terminée": 2, "Clôturée pour sécurité": 1, "Temps écoulé": 1})

    def test_average_and_success_rate_cover_closed_copies_only(self):
        self.copy("r_top", [RIGHT] * 4)                             # 20
        self.copy("r_half", [RIGHT, RIGHT, WRONG, BLANK])           # 10 : réussite (seuil inclus)
        self.copy("r_low", [RIGHT], status=Attempt.TIME_EXPIRED)    # 5
        self.copy("r_old", [RIGHT] * 4, status=Attempt.INTERRUPTED)  # remplacée : ne compte pas
        summary = self.summary()
        self.assertEqual(summary["graded_count"], 3)
        self.assertEqual(summary["average"].quantize(Decimal("0.01")), Decimal("11.67"))
        self.assertEqual(summary["success_rate"], 66.7)
        self.assertEqual(dict(summary["status_counts"])["Interrompue"], 1)

    def test_no_closed_copy_gives_no_rate(self):
        summary = self.summary()
        self.assertIsNone(summary["average"])
        self.assertIsNone(summary["success_rate"])


class CopyDetailTests(ResultsFixture):
    def test_each_copy_counts_right_wrong_and_blank_answers(self):
        attempt = self.copy("r_mix", [RIGHT, WRONG, BLANK])  # 4e question jamais atteinte
        row = self.row(attempt)
        self.assertEqual((row["Réponses justes"], row["Réponses fausses"], row["Sans réponse"]), (1, 1, 2))
        self.assertContains(self.client.get(self.base), "1 / 1 / 2")
        detail = self.client.get(f"/teacher/attempts/{attempt.id}/results/")
        self.assertContains(detail, "1 juste · 1 fausse · 2 sans réponse")

    def test_export_names_the_exam_and_details_violations(self):
        attempt = self.copy("r_v", [RIGHT])
        for event in ("TAB_SWITCH", "TAB_SWITCH", "FULLSCREEN_EXIT", "VIOLATION_IGNORED"):
            SecurityEvent.objects.create(attempt=attempt, event_type=event)
        row = self.row(attempt)
        self.assertEqual((row["Identifiant examen"], row["Examen"]), (self.exam.id, "Sécurité"))
        self.assertEqual(row["Violations"], 3)
        self.assertEqual(row["Détail des violations"], "Changement d'onglet : 2 ; Sortie du plein écran : 1")

    def test_effective_duration_of_a_closed_copy(self):
        attempt = self.copy("r_time", [RIGHT])
        start = timezone.now() - timedelta(hours=1)
        Attempt.objects.filter(pk=attempt.pk).update(started_at=start, ended_at=start + timedelta(minutes=7, seconds=30))
        self.assertEqual(self.row(attempt)["Durée effective (min)"], Decimal("7.50"))

    def test_effective_duration_ignores_the_time_between_closure_and_resume(self):
        attempt = self.copy("r_resumed", [RIGHT])
        resumed_at = timezone.now()
        start = resumed_at - timedelta(minutes=40)
        Attempt.objects.filter(pk=attempt.pk).update(started_at=start, ended_at=resumed_at + timedelta(minutes=2))
        event = SecurityEvent.objects.create(attempt=attempt, event_type="RESUME_AUTHORIZED", details={
            "closed_at": (start + timedelta(minutes=3)).isoformat()})
        SecurityEvent.objects.filter(pk=event.pk).update(created_at=resumed_at)
        self.assertEqual(self.row(attempt)["Durée effective (min)"], Decimal("5.00"))

    def test_copy_in_progress_has_no_duration(self):
        self.assertIsNone(self.row(self.attempt)["Durée effective (min)"])


class PrintViewTests(ResultsFixture):
    def test_printable_page_holds_the_exam_the_statistics_and_every_copy(self):
        late = self.copy("r_zed", [RIGHT])
        late.student.last_name = "Zed"
        late.student.save(update_fields=["last_name"])
        first = self.copy("r_ba", [RIGHT] * 4)
        first.student.last_name = "Ba"
        first.student.save(update_fields=["last_name"])
        page = self.client.get(self.base + "print/")
        self.assertContains(page, "Sécurité")
        self.assertContains(page, f"Examen n° {self.exam.id}")
        self.assertContains(page, "Taux de réussite")
        self.assertContains(page, "data-print")
        self.assertContains(page, "A4 landscape")
        self.assertNotContains(page, 'class="appbar"')
        names = [row["attempt"].student.last_name for row in page.context["rows"]]
        self.assertEqual(names, ["", "Ba", "Zed"])

    def test_printable_page_escapes_student_text(self):
        self.student.last_name = "<script>x</script>"
        self.student.save(update_fields=["last_name"])
        self.assertNotContains(self.client.get(self.base + "print/"), "<script>x</script>")

    def test_results_page_links_to_the_printable_page(self):
        self.assertContains(self.client.get(self.base), f'href="{self.base}print/"')

    def test_only_a_manager_of_the_exam_can_print(self):
        for user in (self.student, make_user("r_other", "TEACHER")):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.base + "print/").status_code, 403)
