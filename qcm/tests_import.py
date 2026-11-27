"""Import de sujets : format JSON et signalement des questions invalides (issue #26)."""
import io
import json
import tempfile
from decimal import Decimal
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.test import TestCase

from . import importers
from .models import Exam
from .tests_classrooms import make_user

URL = "/teacher/import-qcm/"
PREVIEW_URL = "/teacher/import-qcm/preview/"


def opt(text, correct=False):
    return {"text": text, "correct": correct}


def question(**changes):
    return {"text": "2 + 2 ?", "options": [opt("4", True), opt("5")], **changes}


def json_file(data, name="sujet.json"):
    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    return SimpleUploadedFile(name, raw)


def docx_file(*lines):
    from docx import Document
    document = Document()
    for line in lines:
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return SimpleUploadedFile("sujet.docx", buffer.getvalue())


def xlsx_file(*rows, name="sujet.xlsx"):
    from openpyxl import Workbook
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return SimpleUploadedFile(name, buffer.getvalue())


class ImportTestCase(TestCase):
    def setUp(self):
        self.client.force_login(make_user("imp_teacher", "TEACHER"))

    def upload(self, subject, **fields):
        data = {"subject_file": subject, "answer_mode": "integrated", "audience_mode": "LEVEL",
                "target_level": "L3", "duration": "30", **fields}
        return self.client.post(URL, data)

    def assertRefused(self, response, *messages):
        """L'import reste sur le formulaire, nomme chaque problème et ne prépare rien."""
        self.assertEqual(response.status_code, 200)
        for message in messages:
            self.assertContains(response, message)
        self.assertNotIn("qcm_import_preview", self.client.session)
        self.assertEqual(Exam.objects.count(), 0)


class JsonImportTests(ImportTestCase):
    def test_valid_file_is_previewed_then_keeps_type_and_points(self):
        response = self.upload(json_file({"questions": [
            question(points=2.5),
            question(text="Nombres premiers ?", type="MULTIPLE", options=[opt("2", True), opt("4")]),
        ]}))

        self.assertRedirects(response, PREVIEW_URL)
        self.assertEqual(Exam.objects.count(), 0)  # rien avant la confirmation
        preview = self.client.get(PREVIEW_URL)
        self.assertContains(preview, "2.5 pt")
        self.assertContains(preview, "Réponses multiples")

        self.client.post(PREVIEW_URL, {"correct_0": ["A"], "correct_1": ["A"]})

        first, second = Exam.objects.get().questions.all()
        self.assertEqual((first.question_type, first.points), ("SINGLE", Decimal("2.5")))
        self.assertEqual((second.question_type, second.points), ("MULTIPLE", Decimal("1")))
        self.assertEqual([(o.text, o.is_correct) for o in first.options.all()], [("4", True), ("5", False)])

    def test_single_answer_question_cannot_get_two_correct_answers_in_preview(self):
        self.upload(json_file({"questions": [question(type="SINGLE")]}))

        response = self.client.post(PREVIEW_URL, {"correct_0": ["A", "B"]})

        self.assertContains(response, "réponse unique")
        self.assertEqual(Exam.objects.count(), 0)

    def test_every_invalid_question_is_reported_and_nothing_is_imported(self):
        response = self.upload(json_file({"questions": [
            question(),
            question(text="  "),
            question(options=[opt("seule", True)]),
            question(options=[opt("4", "false"), opt("5")]),
            question(options=[opt("4", True), opt("")]),
            question(type="OUVERTE"),
            question(type="SINGLE", options=[opt("4", True), opt("5", True)]),
            question(points=0),
            question(points="beaucoup"),
            question(points=1.255),
            question(text="x" * 5001),
            question(options=[opt("y" * 501, True), opt("5")]),
            question(options=[opt(str(n), n == 0) for n in range(9)]),
            "pas un objet",
        ]}))

        self.assertRefused(
            response,
            "Question 2 : énoncé vide",
            "Question 3 : au moins deux propositions",
            "Question 4 : proposition A",
            "Question 5 : proposition B vide",
            "Question 6 : type inconnu",
            "Question 7 : une question à réponse unique",
            "Question 8 : barème",
            "Question 9 : barème",
            "Question 10 : barème",
            "Question 11 : énoncé de plus de 5000 caractères",
            "Question 12 : proposition A de plus de 500 caractères",
            "Question 13 : plus de 8 propositions",
            "Question 14 : format invalide",
        )
        self.assertNotContains(response, "Question 1 :")

    def test_non_finite_points_are_reported(self):
        raw = b'{"questions": [{"text": "q", "points": NaN, "options": [{"text": "a"}, {"text": "b"}]}]}'
        self.assertRefused(self.upload(json_file(raw)), "Question 1 : barème")

    def test_unreadable_or_unexpected_content_is_refused(self):
        for raw in (b"{pas du json", b"\xff\xfe\x00", b"[" * 100000, b"[]", b'{"questions": []}',
                    b'{"questions": "abc"}'):
            with self.subTest(raw=raw[:30]):
                self.assertRefused(self.upload(json_file(raw)), "JSON")

    def test_characters_the_database_or_page_cannot_hold_are_reported(self):
        response = self.upload(json_file({"questions": [
            question(text="nul\x00"),
            question(options=[opt("\ud800", True), opt("5")]),
        ]}))

        self.assertRefused(response, "Question 1 : énoncé : caractère non autorisé",
                           "Question 2 : proposition A : caractère non autorisé")

    def test_utf8_bom_is_accepted(self):
        raw = b"\xef\xbb\xbf" + json.dumps({"questions": [question()]}).encode()
        self.assertRedirects(self.upload(json_file(raw)), PREVIEW_URL)

    def test_too_many_questions_are_refused(self):
        response = self.upload(json_file({"questions": [question()] * (importers.MAX_QUESTIONS + 1)}))
        self.assertRefused(response, "plus de 500 questions")

    def test_oversized_file_is_refused(self):
        response = self.upload(json_file(b" " * (15 * 1024 * 1024 + 1)))
        self.assertRefused(response, "15 Mo")

    def test_unexpected_file_type_is_refused(self):
        response = self.upload(SimpleUploadedFile("sujet.txt", b"1. Question"))
        self.assertRefused(response, "Utilisez PDF, DOCX, XLSX ou JSON")

    def test_form_offers_json(self):
        self.assertContains(self.client.get(URL), ".json")


class OtherFormatsReportInvalidQuestionsTests(ImportTestCase):
    def test_word_blocks_that_used_to_be_dropped_are_reported(self):
        response = self.upload(docx_file(
            "1. Question correcte", "A) oui", "B) non", "Réponse : A",
            "2. Question sans proposition suffisante", "A) seule",
            "3.", "A) oui", "B) non",
        ))

        self.assertRefused(response, "Question 2 : au moins deux propositions", "Question 3 : énoncé vide")

    def test_word_empty_duplicate_and_unknown_answers_are_reported(self):
        response = self.upload(docx_file(
            "1. Proposition vide", "A)", "B) non",
            "2. Lettre répétée", "A) oui", "A) encore", "B) non",
            "3. Réponse hors liste", "A) oui", "B) non", "Réponse : A, E",
        ))

        self.assertRefused(
            response,
            "Question 1 : proposition A vide",
            "Question 2 : proposition A en double",
            "Question 3 : la réponse E ne correspond à aucune proposition",
        )

    def test_long_texts_are_reported_instead_of_truncated(self):
        response = self.upload(xlsx_file(
            ["Question", "A", "B", "Réponse"],
            ["x" * 5001, "oui", "non", "A"],
            ["Question", "y" * 501, "non", "A"],
        ))

        self.assertRefused(response, "Question 1 (ligne 2) : énoncé de plus de 5000",
                           "Question 2 (ligne 3) : proposition A de plus de 500")

    def test_excel_rows_that_used_to_be_skipped_are_reported(self):
        response = self.upload(xlsx_file(
            ["Question", "A", "B", "Réponse"],
            ["Correcte", "oui", "non", "A"],
            [None, None, None, None],
            ["Une seule proposition", "oui", None, "A"],
            [None, "oui", "non", "A"],
            ["Réponse hors liste", "oui", "non", "C"],
        ))

        self.assertRefused(
            response,
            "Question 3 (ligne 4) : au moins deux propositions",
            "Question 4 (ligne 5) : énoncé vide",
            "Question 5 (ligne 6) : la réponse C ne correspond à aucune proposition",
        )

    def test_excel_columns_beyond_d_are_imported(self):
        self.upload(xlsx_file(
            ["Question", "A", "B", "C", "D", "E", "Réponse"],
            ["Cinq choix", "1", "2", "3", "4", "5", "E"],
        ))

        imported = self.client.session["qcm_import_preview"]["questions"][0]
        self.assertEqual([o["letter"] for o in imported["options"]], list("ABCDE"))
        self.assertEqual(imported["correct"], ["E"])

    def test_separate_answer_key_pointing_to_a_missing_option_is_reported(self):
        response = self.upload(
            docx_file("1. Question", "A) oui", "B) non"),
            answer_mode="separate",
            answer_file=xlsx_file(["Question", "Réponse"], [1, "D"], name="corrige.xlsx"),
        )

        self.assertRefused(response, "Question 1 : la réponse D ne correspond à aucune proposition")

    def test_manual_mode_ignores_the_answers_written_in_the_file(self):
        response = self.upload(docx_file("1. Question", "A) oui", "B) non", "Réponse : E"), answer_mode="manual")

        self.assertRedirects(response, PREVIEW_URL)


class ImportCommandTests(TestCase):
    def setUp(self):
        make_user("cmd_teacher", "TEACHER")

    def run_command(self, data):
        # Le fichier doit être fermé avant que la commande le relise (exigé par Windows).
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sujet.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            call_command("import_qcm", file=str(path), teacher="cmd_teacher", stdout=io.StringIO())

    def test_command_keeps_type_points_and_metadata(self):
        self.run_command({"title": "Depuis la ligne de commande", "questions": [
            question(points=3, options=[opt("a", True), opt("b", True), opt("c")]),
        ]})

        exam = Exam.objects.get(title="Depuis la ligne de commande")
        imported = exam.questions.get()
        self.assertEqual((imported.question_type, imported.points, imported.duration_seconds),
                         ("MULTIPLE", Decimal("3"), 30))
        self.assertFalse(exam.published)

    def test_command_reports_every_invalid_question_and_imports_nothing(self):
        with self.assertRaises(CommandError) as caught:
            self.run_command({"questions": [
                question(options=[opt("a"), opt("b")]),
                question(text=""),
            ]})

        self.assertIn("Question 1 : aucune bonne réponse", str(caught.exception))
        self.assertIn("Question 2 : énoncé vide", str(caught.exception))
        self.assertEqual(Exam.objects.count(), 0)
