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


@override_settings(DEBUG=True)
class SeedDemoResetSafetyTests(TestCase):
    """Relecture de la PR #20 : --reset ne doit jamais toucher de vraies données."""

    def run_seed(self, *args):
        call_command("seed_demo", *args, stdout=StringIO())

    def test_reset_epargne_un_vrai_compte_demo_(self):
        from qcm.models import Attempt
        self.run_seed("--students", "2")
        # Un vrai étudiant inscrit avec un identifiant qui commence par demo_, et sa copie.
        real = User.objects.create_user(username="demo_reel", password="x", email="awa@example.com")
        exam = Exam.objects.create(title="Vrai examen", teacher=User.objects.create_user("vrai_prof"),
                                   duration_minutes=10, access_code="VRAI0001")
        from django.utils import timezone
        now = timezone.now()
        Attempt.objects.create(exam=exam, student=real, global_deadline=now, question_started_at=now,
                               question_deadline=now)
        self.run_seed("--students", "2", "--reset")
        self.assertTrue(User.objects.filter(username="demo_reel").exists())
        self.assertTrue(Attempt.objects.filter(student=real).exists())

    def test_meme_email_demo_mais_autre_identifiant_epargne(self):
        User.objects.create_user(username="demo_x", password="x", email="demo_etu001@demo.invalid")
        self.run_seed("--students", "1")
        self.run_seed("--students", "1", "--reset")
        self.assertTrue(User.objects.filter(username="demo_x").exists())

    def test_identifiant_deja_pris_par_un_vrai_compte(self):
        User.objects.create_user(username="demo_etu001", password="x", email="vrai@example.com")
        with self.assertRaisesMessage(CommandError, "demo_etu001"):
            self.run_seed("--students", "2")
        self.assertFalse(User.objects.filter(username="demo_admin").exists())

    def test_examen_d_un_vrai_enseignant_dans_une_classe_de_demo(self):
        self.run_seed("--students", "1")
        prof = User.objects.create_user("vrai_prof")
        Exam.objects.create(title="Examen réel", teacher=prof, duration_minutes=10, access_code="VRAI0002",
                            classroom=Classroom.objects.get(join_code="DEMOGLM"))
        with self.assertRaisesMessage(CommandError, "Examen réel"):
            self.run_seed("--students", "1", "--reset")
        # Rien n'a été supprimé.
        self.assertTrue(User.objects.filter(username="demo_admin").exists())
        self.assertTrue(Exam.objects.filter(title="Examen réel").exists())
