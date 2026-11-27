"""Tests de l'issue #15 : export Excel des résultats, mêmes colonnes que le CSV."""
import csv
from datetime import datetime
from io import BytesIO

from django.db import connection
from django.test.utils import CaptureQueriesContext
from openpyxl import load_workbook

from .models import Attempt, SecurityEvent
from .tests_examen_securite import ExamFixture, make_user

HEADER = ["Identifiant", "Matricule", "Nom", "Prénom", "Statut", "Nature du score", "Motif de clôture",
          "Début", "Fin", "Score obtenu", "Score maximal", "Pourcentage (%)", "Note finale (/20)", "Violations"]


class ResultsExportTests(ExamFixture):
    def setUp(self):
        super().setUp()
        self.student.last_name = "Diop"
        self.student.save(update_fields=["last_name"])
        self.student.profile.student_number = "00123"
        self.student.profile.save(update_fields=["student_number"])
        for event in ("TAB_SWITCH", "FULLSCREEN_EXIT", "DUPLICATE_IGNORED"):
            SecurityEvent.objects.create(attempt=self.attempt, event_type=event)
        self.client.force_login(self.teacher)
        self.base = f"/teacher/exams/{self.exam.id}/results/"

    def sheet(self):
        response = self.client.get(self.base + "export.xlsx")
        self.assertEqual(response.status_code, 200)
        self.response = response
        return load_workbook(BytesIO(response.content)).active

    def first_row(self):
        sheet = self.sheet()
        return {name: sheet.cell(2, n) for n, name in enumerate(HEADER, 1)}

    def test_file_opens_with_the_expected_header(self):
        sheet = self.sheet()
        self.assertEqual([c.value for c in sheet[1]], HEADER)
        self.assertEqual(self.response["Content-Type"],
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIn(f"resultats_examen_{self.exam.id}.xlsx", self.response["Content-Disposition"])

    def test_row_holds_text_numbers_and_dates(self):
        Attempt.objects.filter(pk=self.attempt.pk).update(status=Attempt.COMPLETED)
        row = self.first_row()
        self.assertEqual(row["Matricule"].value, "00123")  # le zéro de tête est conservé
        self.assertEqual((row["Nom"].value, row["Nature du score"].value), ("Diop", "Définitif"))
        self.assertEqual(row["Violations"].value, 2)  # le doublon ignoré ne compte pas
        for name in ("Score obtenu", "Score maximal", "Pourcentage (%)", "Note finale (/20)"):
            self.assertEqual(row[name].data_type, "n", name)
        self.assertIsInstance(row["Début"].value, datetime)

    def test_student_text_is_never_a_formula(self):
        self.student.last_name = '=HYPERLINK("http://x")'
        self.student.first_name = "Awa\x07"  # caractère interdit dans un classeur
        self.student.save(update_fields=["last_name", "first_name"])
        row = self.first_row()
        self.assertEqual((row["Nom"].value, row["Nom"].data_type), ('=HYPERLINK("http://x")', "s"))
        self.assertEqual(row["Prénom"].value, "Awa")

    def test_csv_has_the_same_columns_and_values(self):
        text = self.client.get(self.base + "export/").content.decode("utf-8-sig")
        header, row = list(csv.reader(text.splitlines(), delimiter=";"))
        self.assertEqual(header, HEADER)
        self.assertEqual(row[HEADER.index("Violations")], "2")
        self.assertEqual(row[HEADER.index("Score maximal")], f"{self.exam.questions.count()}.00")

    def test_number_of_queries_does_not_grow_with_the_attempts(self):
        def queries(url):
            with CaptureQueriesContext(connection) as captured:
                self.assertEqual(self.client.get(self.base + url).status_code, 200)
            return len(captured)

        urls = ("", "export/", "export.xlsx")
        # Copies démarrées avant que le barème soit figé : il est recalculé depuis l'examen.
        Attempt.objects.filter(pk=self.attempt.pk).update(grading_snapshot={})
        self.attempt.grading_snapshot = {}
        before = [queries(url) for url in urls]
        for n in range(3):
            Attempt.objects.create(
                exam=self.exam, student=make_user(f"x_student{n}"), status=Attempt.COMPLETED,
                question_order=self.attempt.question_order, grading_snapshot=self.attempt.grading_snapshot,
                global_deadline=self.attempt.global_deadline, question_started_at=self.attempt.question_started_at,
                question_deadline=self.attempt.question_deadline)
        self.assertEqual([queries(url) for url in urls], before)

    def test_results_page_offers_both_exports(self):
        page = self.client.get(self.base)
        self.assertContains(page, f'href="{self.base}export/"')
        self.assertContains(page, f'href="{self.base}export.xlsx"')

    def test_only_a_manager_of_the_exam_can_export(self):
        for user in (self.student, make_user("x_other", "TEACHER")):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.base + "export.xlsx").status_code, 403)
