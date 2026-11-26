"""Tests de l'issue #16 : analyse par question dans les résultats."""
from .models import Attempt, Option, Question, Response
from .services import question_stats
from .tests_examen_securite import ExamFixture, make_user

RIGHT, WRONG, BLANK, UNSEEN = "right", "wrong", "blank", "unseen"


class QuestionStatsTests(ExamFixture):
    question_count = 4

    def setUp(self):
        super().setUp()  # laisse une tentative en cours, qui ne doit jamais compter
        self.questions = list(self.exam.questions.order_by("position"))
        self.copies = 0

    def copy(self, *answers, status=Attempt.COMPLETED):
        """Une copie : une réponse par question, dans l'ordre (UNSEEN = aucune ligne enregistrée)."""
        self.copies += 1
        attempt = Attempt.objects.create(
            exam=self.exam, student=make_user(f"a_student{self.copies}"), status=status,
            question_order=self.attempt.question_order, grading_snapshot=self.attempt.grading_snapshot,
            global_deadline=self.attempt.global_deadline, question_started_at=self.attempt.question_started_at,
            question_deadline=self.attempt.question_deadline)
        for question, answer in zip(self.questions, answers):
            if answer == UNSEEN:
                continue
            selected = [] if answer == BLANK else [question.options.get(is_correct=answer == RIGHT).id]
            Response.objects.create(attempt=attempt, question=question, selected_option_ids=selected)

    def dataset(self):
        self.copy(RIGHT, WRONG, RIGHT, RIGHT)
        self.copy(RIGHT, WRONG, RIGHT, WRONG, status=Attempt.TIME_EXPIRED)
        self.copy(RIGHT, WRONG, RIGHT, WRONG)
        self.copy(RIGHT, WRONG, BLANK, WRONG)
        self.copy(RIGHT, BLANK, UNSEEN, WRONG, status=Attempt.TERMINATED_SECURITY)
        self.copy(WRONG, RIGHT, WRONG, RIGHT, status=Attempt.INTERRUPTED)  # remplacée : ne compte pas

    def test_rates_per_question_over_finished_copies(self):
        self.dataset()
        stats = question_stats(self.exam)
        self.assertEqual([s["question"] for s in stats], self.questions)
        self.assertEqual([s["total"] for s in stats], [5, 5, 5, 5])
        self.assertEqual([s["success_rate"] for s in stats], [100, 0, 60, 20])
        self.assertEqual([s["blank_rate"] for s in stats], [0, 20, 40, 0])

    def test_distribution_of_chosen_options(self):
        self.dataset()
        options = question_stats(self.exam)[3]["options"]
        self.assertEqual([(o["option"].text, o["count"], o["rate"], o["correct"]) for o in options],
                         [("Juste", 1, 20, True), ("Faux", 4, 80, False)])

    def test_flags_only_beyond_the_thresholds(self):
        self.dataset()
        # 100 % trop facile, 0 % trop difficile, 20 % pile : pas signalée.
        self.assertEqual([s["level"] for s in question_stats(self.exam)], ["easy", "hard", "", ""])

    def test_ninety_percent_exactly_is_not_too_easy(self):
        for n in range(10):
            self.copy(RIGHT if n else WRONG)
        self.assertEqual(question_stats(self.exam)[0]["success_rate"], 90)
        self.assertEqual(question_stats(self.exam)[0]["level"], "")

    def test_partially_right_multiple_answer_is_not_a_success(self):
        question = self.questions[0]
        question.question_type = Question.MULTIPLE
        question.save(update_fields=["question_type"])
        second = Option.objects.create(question=question, text="Juste aussi", is_correct=True, position=3)
        first = question.options.get(text="Juste")
        snapshot = self.attempt.grading_snapshot
        snapshot["questions"][str(question.id)] = {"type": Question.MULTIPLE, "points": "1",
                                                   "correct": [first.id, second.id]}
        for selected in ([first.id], [second.id, first.id]):
            self.copy()
            Response.objects.create(attempt=Attempt.objects.latest("pk"), question=question,
                                    selected_option_ids=selected)
        self.assertEqual(question_stats(self.exam)[0]["success_rate"], 50)

    def test_answer_key_frozen_at_start_is_used(self):
        self.copy(RIGHT)
        for option in self.questions[0].options.all():
            option.is_correct = not option.is_correct
            option.save(update_fields=["is_correct"])
        stats = question_stats(self.exam)[0]
        self.assertEqual(stats["success_rate"], 100)
        self.assertEqual([o["correct"] for o in stats["options"]], [True, False])

    def test_results_page_shows_the_analysis(self):
        self.dataset()
        self.client.force_login(self.teacher)
        page = self.client.get(f"/teacher/exams/{self.exam.id}/results/")
        for text in ("Analyse par question", "Question 1", "Trop facile", "Trop difficile", "Bonne réponse",
                     "5 copies terminées"):
            self.assertContains(page, text)

    def test_results_page_without_finished_copy(self):
        self.assertEqual(question_stats(self.exam), [])
        self.client.force_login(self.teacher)
        page = self.client.get(f"/teacher/exams/{self.exam.id}/results/")
        self.assertContains(page, "L'analyse apparaîtra dès qu'une copie sera terminée.")
        self.assertNotContains(page, "Trop difficile")
