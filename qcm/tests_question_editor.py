"""Éditeur graphique des questions (façon Google Forms) : points d'accès JSON et page de l'examen."""
import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import Attempt, AuditLog, Exam, Question
from .views.teacher import write_options


def make_user(username, role="TEACHER"):
    user = User.objects.create_user(username=username, password="StrongPass123!")
    user.profile.role = role
    user.profile.save()
    return user


def payload(**overrides):
    data = {"text": "Capitale du Sénégal ?", "kind": "SINGLE", "points": "2",
            "options": [{"text": "Dakar", "correct": True}, {"text": "Thiès", "correct": False}]}
    data.update(overrides)
    return data


class QuestionEditorTests(TestCase):
    def setUp(self):
        self.teacher = make_user("qe_prof")
        self.exam = Exam.objects.create(title="Brouillon", teacher=self.teacher, audience_mode="LEVEL", target_level="L1")
        self.client.force_login(self.teacher)
        self.base = f"/teacher/exams/{self.exam.id}/questions/api/"

    def post(self, path, data=None, raw=None):
        return self.client.post(self.base + path, raw if raw is not None else json.dumps(data or {}),
                                content_type="application/json")

    def add(self, text, **kw):
        response = self.post("save/", payload(text=text, **kw))
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["question"]

    def order(self):
        return list(self.exam.questions.order_by("position").values_list("text", flat=True))

    # ---- page
    def test_draft_page_mounts_editor_with_data_and_keeps_classic_form(self):
        self.add("Q1")
        page = self.client.get(f"/teacher/exams/{self.exam.id}/")
        self.assertContains(page, 'id="questionEditor"')
        self.assertContains(page, 'id="qeData"')
        self.assertContains(page, "js/question_editor.js")
        self.assertContains(page, 'class="qe-fallback"')  # formulaire sans JavaScript
        self.assertEqual(page.context["editor_questions"][0]["text"], "Q1")

    def test_published_exam_has_no_editor(self):
        Exam.objects.filter(pk=self.exam.pk).update(published=True)
        page = self.client.get(f"/teacher/exams/{self.exam.id}/")
        self.assertNotContains(page, 'id="questionEditor"')
        self.assertNotContains(page, "js/question_editor.js")

    # ---- création et modification
    def test_create_then_update_question(self):
        q = self.add("Capitale ?")
        self.assertEqual(q["points"], "2")
        self.assertEqual([o["correct"] for o in q["options"]], [True, False])
        response = self.post("save/", payload(id=q["id"], text="Capitale du Mali ?", kind="MULTIPLE", points="1.5",
                                              options=[{"text": "Bamako", "correct": True},
                                                       {"text": "Ségou", "correct": True},
                                                       {"text": "", "correct": False}]))
        self.assertEqual(response.status_code, 200)
        question = Question.objects.get(pk=q["id"])
        self.assertEqual((question.text, question.question_type, question.points), ("Capitale du Mali ?", "MULTIPLE", Decimal("1.5")))
        self.assertEqual(list(question.options.values_list("text", "is_correct")), [("Bamako", True), ("Ségou", True)])

    def test_eight_options_are_kept(self):
        options = [{"text": f"Option {i}", "correct": i == 0} for i in range(8)]
        q = self.add("Huit", options=options)
        self.assertEqual(len(q["options"]), 8)

    def test_validation_errors_are_returned(self):
        cases = [
            (payload(text="  "), "énoncé"),
            (payload(points="0"), "barème"),
            (payload(points=""), "barème"),
            (payload(options=[{"text": "Seule", "correct": True}]), "deux propositions"),
            (payload(options=[{"text": "A", "correct": False}, {"text": "B", "correct": False}]), "bonne réponse"),
            (payload(options=[{"text": "A", "correct": True}, {"text": "B", "correct": True}]), "réponse unique"),
            (payload(kind="TEXT"), "Type"),
        ]
        for data, expected in cases:
            response = self.post("save/", data)
            self.assertEqual(response.status_code, 400, data)
            self.assertIn(expected, response.json()["error"])
        self.assertFalse(Question.objects.exists())

    def test_malformed_requests_are_rejected(self):
        self.assertEqual(self.post("save/", raw="pas du json").status_code, 400)
        self.assertEqual(self.post("save/", raw="[1, 2]").status_code, 400)
        self.assertEqual(self.post("save/", payload(options="Dakar")).status_code, 400)
        self.assertEqual(self.post("save/", payload(id=999999)).status_code, 404)
        self.assertEqual(self.post("save/", payload(id="abc")).status_code, 404)

    def test_correct_flag_must_be_a_real_boolean(self):
        response = self.post("save/", payload(options=[{"text": "A", "correct": "false"}, {"text": "B", "correct": 1}]))
        self.assertEqual(response.status_code, 400)  # ni "false" ni 1 ne valent « vrai »

    def test_new_question_is_inserted_after_the_given_one(self):
        first = self.add("Q1")
        self.add("Q3")
        self.post("save/", payload(text="Q2", after=first["id"]))
        self.assertEqual(self.order(), ["Q1", "Q2", "Q3"])
        self.assertEqual(list(self.exam.questions.values_list("position", flat=True)), [1, 2, 3])

    def test_resent_creation_updates_instead_of_duplicating(self):
        """Réponse de la création perdue : le nouvel essai, même `client` sans `id`, ne crée pas de double."""
        first = self.add("Q1", client="abc123")
        again = self.add("Q1 corrigée", client="abc123")
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(self.order(), ["Q1 corrigée"])
        other = self.add("Q2", client="def456")  # autre question de la page : bien créée
        self.assertNotEqual(other["id"], first["id"])
        self.assertEqual(self.order(), ["Q1 corrigée", "Q2"])

    def test_creation_key_is_per_exam_and_odd_values_are_ignored(self):
        self.add("Q1", client="abc123")
        other_exam = Exam.objects.create(title="Autre", teacher=self.teacher, audience_mode="LEVEL", target_level="L1")
        response = self.client.post(f"/teacher/exams/{other_exam.id}/questions/api/save/",
                                    json.dumps(payload(text="Ailleurs", client="abc123")), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(other_exam.questions.count(), 1)
        for odd in (12, ["x"], {"a": 1}, ""):
            self.assertEqual(self.post("save/", payload(text="Q", client=odd)).status_code, 200)
        self.assertEqual(self.exam.questions.count(), 5)

    # ---- dupliquer, supprimer, réordonner
    def test_duplicate_inserts_copy_after_source(self):
        q1 = self.add("Q1", kind="MULTIPLE", options=[{"text": "A", "correct": True}, {"text": "B", "correct": True}])
        self.add("Q2")
        response = self.post(f"{q1['id']}/duplicate/")
        self.assertEqual(response.status_code, 200)
        copy = response.json()["question"]
        self.assertNotEqual(copy["id"], q1["id"])
        self.assertEqual((copy["text"], copy["kind"], copy["options"]), (q1["text"], q1["kind"], q1["options"]))
        self.assertEqual(self.order(), ["Q1", "Q1", "Q2"])

    def test_delete_renumbers_and_is_idempotent(self):
        q1, q2, q3 = self.add("Q1"), self.add("Q2"), self.add("Q3")
        response = self.post(f"{q2['id']}/delete/")
        self.assertEqual(response.json()["order"], [q1["id"], q3["id"]])
        self.assertEqual(list(self.exam.questions.values_list("position", flat=True)), [1, 2])
        self.assertEqual(self.post(f"{q2['id']}/delete/").status_code, 200)  # double clic

    def test_reorder(self):
        q1, q2, q3 = self.add("Q1"), self.add("Q2"), self.add("Q3")
        response = self.post("order/", {"order": [q3["id"], q1["id"], q2["id"]]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.order(), ["Q3", "Q1", "Q2"])

    def test_reorder_requires_exactly_the_exam_questions(self):
        q1, q2 = self.add("Q1"), self.add("Q2")
        other_exam = Exam.objects.create(title="Autre", teacher=self.teacher)
        foreign = Question.objects.create(exam=other_exam, text="X", position=1)
        for order in ([q1["id"]], [q1["id"], q1["id"]], [q1["id"], foreign.id], [q2["id"], q1["id"], foreign.id],
                      "1,2", [q1["id"], True]):
            self.assertEqual(self.post("order/", {"order": order}).status_code, 409, order)
        self.assertEqual(self.order(), ["Q1", "Q2"])

    # ---- droits et verrouillage
    def test_other_teacher_and_student_are_refused(self):
        q = self.add("Q1")
        for user in (make_user("qe_other"), make_user("qe_student", "STUDENT")):
            self.client.force_login(user)
            self.assertEqual(self.post("save/", payload()).status_code, 403)
            self.assertEqual(self.post(f"{q['id']}/delete/").status_code, 403)
            self.assertEqual(self.post(f"{q['id']}/duplicate/").status_code, 403)
            self.assertEqual(self.post("order/", {"order": [q["id"]]}).status_code, 403)
        self.assertEqual(Question.objects.count(), 1)

    def test_anonymous_is_redirected_and_get_is_refused(self):
        self.assertEqual(self.client.get(self.base + "save/").status_code, 405)
        self.client.logout()
        self.assertEqual(self.post("save/", payload()).status_code, 302)

    def test_questions_are_locked_after_publication_or_first_attempt(self):
        q = self.add("Q1")
        Exam.objects.filter(pk=self.exam.pk).update(published=True)
        response = self.post("save/", payload(id=q["id"], text="Changé"))
        self.assertEqual(response.status_code, 409)
        self.assertIn("publié", response.json()["error"])
        Exam.objects.filter(pk=self.exam.pk).update(published=False)
        now = timezone.now()
        Attempt.objects.create(exam=self.exam, student=make_user("qe_etu", "STUDENT"), question_order=[],
                               global_deadline=now + timedelta(minutes=5), question_started_at=now,
                               question_deadline=now + timedelta(minutes=5))
        for path in ("save/", f"{q['id']}/delete/", f"{q['id']}/duplicate/"):
            self.assertEqual(self.post(path, payload()).status_code, 409, path)
        self.assertEqual(Question.objects.get(pk=q["id"]).text, "Q1")

    def test_unknown_exam(self):
        self.base = "/teacher/exams/999999/questions/api/"
        self.assertEqual(self.post("save/", payload()).status_code, 404)

    # ---- journal
    def test_journal_records_changes_without_flooding(self):
        q = self.add("Q1")
        for text in ("Q1 bis", "Q1 ter", "Q1 quater"):  # saisie continue : enregistrements successifs
            self.post("save/", payload(id=q["id"], text=text))
        self.post("save/", payload(id=q["id"], text="Q1 quater"))  # rien de changé
        self.post(f"{q['id']}/duplicate/")
        self.post(f"{q['id']}/delete/")
        actions = list(AuditLog.objects.order_by("id").values_list("action", flat=True))
        self.assertEqual(actions, ["Question ajoutée", "Question modifiée", "Question dupliquée", "Question supprimée"])

    def test_write_options_helper_keeps_order(self):
        question = Question.objects.create(exam=self.exam, text="Q", position=1)
        write_options(question, [("B", False), ("A", True)])
        self.assertEqual(list(question.options.values_list("text", "position", "is_correct")), [("B", 1, False), ("A", 2, True)])

    def test_classic_form_still_works(self):
        response = self.client.post(f"/teacher/exams/{self.exam.id}/question/add/", {
            "text": "Classique", "kind": "SINGLE", "points": "1",
            "option_text": ["Oui", "Non", ""], "correct": ["0"]})
        self.assertEqual(response.status_code, 302)
        question = Question.objects.get(text="Classique")
        self.assertEqual(list(question.options.values_list("text", "is_correct")), [("Oui", True), ("Non", False)])

    def test_classic_forms_are_journaled_too(self):
        self.client.post(f"/teacher/exams/{self.exam.id}/question/add/", {
            "text": "A", "kind": "SINGLE", "points": "1", "option_text": ["Oui", "Non"], "correct": ["0"]})
        self.client.post(f"/teacher/exams/{self.exam.id}/question/add/", {
            "text": "B", "kind": "SINGLE", "points": "1", "option_text": ["Oui", "Non"], "correct": ["0"]})
        b = Question.objects.get(text="B")
        self.client.post(f"/teacher/exams/{self.exam.id}/question/{b.id}/move/", {"direction": "up"})
        self.client.post(f"/teacher/exams/{self.exam.id}/question/{b.id}/delete/")
        actions = list(AuditLog.objects.order_by("id").values_list("action", flat=True))
        self.assertEqual(actions, ["Question ajoutée", "Question ajoutée", "Ordre des questions modifié", "Question supprimée"])

    def test_odd_json_values_are_refused_not_crashing(self):
        q = self.add("Q1")
        for data in (payload(kind=["x"]), payload(kind={"a": 1}), payload(points="NaN"), payload(points="Infinity")):
            self.assertEqual(self.post("save/", data).status_code, 400, data)
        response = self.post("save/", raw=json.dumps(payload(text="Inf"))[:-1] + ', "id": Infinity}')
        self.assertEqual(response.status_code, 404)
        response = self.post("save/", raw=json.dumps(payload(text="Après"))[:-1] + ', "after": Infinity}')
        self.assertEqual(response.status_code, 200)  # « après » inconnu : ajoutée à la fin
        self.assertEqual(self.order(), [q["text"], "Après"])

    def test_page_marks_publish_form_and_question_count_for_editor(self):
        page = self.client.get(f"/teacher/exams/{self.exam.id}/")
        self.assertContains(page, "data-publish")
        self.assertContains(page, 'id="qeCount"')
