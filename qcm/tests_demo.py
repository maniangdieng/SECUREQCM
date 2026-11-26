"""Tests de la commande seed_demo (issue #7)."""
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from qcm.models import Classroom, Exam, ExamEnrollment
from qcm.permissions import role


@override_settings(DEBUG=True)
class SeedDemoTests(TestCase):
    def run_seed(self, *args):
        out = StringIO()
        call_command("seed_demo", *args, stdout=out)
        return out.getvalue()

    def test_cree_comptes_classes_examens(self):
        output = self.run_seed("--students", "6")
        self.assertIn("DEMOGL01", output)
        self.assertEqual(User.objects.filter(username__startswith="demo_etu").count(), 6)
        self.assertEqual(role(User.objects.get(username="demo_admin")), "ADMIN")
        self.assertEqual(role(User.objects.get(username="demo_prof1")), "TEACHER")
        self.assertEqual(role(User.objects.get(username="demo_etu001")), "STUDENT")
        self.assertEqual(Classroom.objects.count(), 2)
        exam = Exam.objects.get(access_code="DEMOGL01")
        self.assertTrue(exam.published)
        # Tous les étudiants de la classe sont affectés à l'examen publié.
        self.assertEqual(ExamEnrollment.objects.filter(exam=exam).count(), 6)
        self.assertFalse(Exam.objects.get(access_code="DEMODRFT").published)

    def test_les_comptes_peuvent_se_connecter(self):
        self.run_seed("--students", "2")
        self.assertTrue(self.client.login(username="demo_etu001", password="Demo-SecureQCM-2026"))

    def test_questions_publiables(self):
        self.run_seed("--students", "1")
        for exam in Exam.objects.filter(published=True):
            for q in exam.questions.prefetch_related("options"):
                opts = list(q.options.all())
                self.assertGreaterEqual(len(opts), 2)
                n_correct = sum(o.is_correct for o in opts)
                self.assertGreaterEqual(n_correct, 1)
                if q.question_type == "SINGLE":
                    self.assertEqual(n_correct, 1)

    def test_refuse_de_dupliquer_puis_reset(self):
        self.run_seed("--students", "2")
        with self.assertRaises(CommandError):
            self.run_seed("--students", "2")
        self.run_seed("--students", "3", "--reset")
        self.assertEqual(User.objects.filter(username__startswith="demo_etu").count(), 3)
        self.assertEqual(Exam.objects.count(), 3)

    @override_settings(DEBUG=False)
    def test_refuse_en_production_sans_force(self):
        with self.assertRaises(CommandError):
            self.run_seed()
