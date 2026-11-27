"""Tests de la réorganisation façon Google Classroom (menu, onglets, À faire, Notes, page d'examen étudiant)."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import Attempt, Classroom, ClassroomMembership, Exam, ExamEnrollment, Option, Question, Response
from .services import final_grades, grade_summary


def make_user(username, role_value="STUDENT", first_name=""):
    user = User.objects.create_user(username=username, password="StrongPass123!", first_name=first_name)
    user.profile.role = role_value
    user.profile.save()
    return user


class ClassroomLayoutTests(TestCase):
    def setUp(self):
        self.teacher = make_user("gc_prof", "TEACHER", "Awa")
        self.student = make_user("gc_etu", first_name="Moussa")
        self.other = make_user("gc_autre")
        self.classroom = Classroom.objects.create(name="Machine Learning", section="L3", owner=self.teacher, color="indigo")
        ClassroomMembership.objects.create(classroom=self.classroom, user=self.teacher, role="TEACHER")
        ClassroomMembership.objects.create(classroom=self.classroom, user=self.student, role="STUDENT")
        self.exam = Exam.objects.create(title="Devoir 1", teacher=self.teacher, classroom=self.classroom,
                                        audience_mode="CLASS", published=True, shuffle_questions=False)
        q1 = Question.objects.create(exam=self.exam, text="Q1", position=1, points=2)
        self.q1_ok = Option.objects.create(question=q1, text="ok", is_correct=True)
        Option.objects.create(question=q1, text="ko")
        q2 = Question.objects.create(exam=self.exam, text="Q2", position=2, question_type="MULTIPLE")
        self.q2_a = Option.objects.create(question=q2, text="a", is_correct=True)
        Option.objects.create(question=q2, text="b", is_correct=True)
        self.q2_c = Option.objects.create(question=q2, text="c")
        ExamEnrollment.objects.create(exam=self.exam, student=self.student, source="CLASS")

    def finished_attempt(self, student, options):
        now = timezone.now()
        attempt = Attempt.objects.create(exam=self.exam, student=student, status=Attempt.COMPLETED, ended_at=now,
                                         question_order=[], global_deadline=now, question_started_at=now,
                                         question_deadline=now)
        for question_id, selected in options.items():
            Response.objects.create(attempt=attempt, question_id=question_id, selected_option_ids=selected)
        return attempt

    def test_teacher_tabs_render(self):
        self.client.force_login(self.teacher)
        for tab in ("flux", "travaux", "personnes", "notes", "parametres"):
            page = self.client.get(f"/classes/{self.classroom.id}/?tab={tab}")
            self.assertEqual(page.status_code, 200, tab)
            self.assertContains(page, 'class="class-tabs theme-indigo"')
        self.assertContains(self.client.get(f"/classes/{self.classroom.id}/"), "a publié un nouvel examen")

    def test_student_tabs_render_and_hide_teacher_tabs(self):
        self.client.force_login(self.student)
        for tab in ("flux", "travaux", "personnes"):
            self.assertEqual(self.client.get(f"/classes/{self.classroom.id}/?tab={tab}").status_code, 200, tab)
        page = self.client.get(f"/classes/{self.classroom.id}/?tab=notes")  # onglet enseignant : retombe sur le flux
        self.assertNotContains(page, "?tab=notes")
        self.assertNotContains(page, "?tab=parametres")
        self.assertContains(page, "Devoir 1")

    def test_drawer_lists_user_classes(self):
        self.client.force_login(self.student)
        page = self.client.get("/dashboard/student/")
        self.assertContains(page, 'id="drawer"')
        self.assertContains(page, "Machine Learning")
        self.assertContains(page, "À faire")

    def test_student_home_card_shows_work_due(self):
        self.client.force_login(self.student)
        page = self.client.get("/dashboard/student/")
        self.assertContains(page, f'href="/student/exams/{self.exam.id}/"')

    def test_student_todo_splits_assigned_and_done(self):
        self.client.force_login(self.student)
        self.assertContains(self.client.get("/student/todo/"), "Devoir 1")
        self.finished_attempt(self.student, {})
        self.assertNotContains(self.client.get("/student/todo/"), "Devoir 1")
        self.assertContains(self.client.get("/student/todo/?tab=termines"), "Devoir 1")

    def test_teacher_todo_counts_turned_in(self):
        self.finished_attempt(self.student, {})
        self.client.force_login(self.teacher)
        page = self.client.get("/teacher/to-review/")
        self.assertContains(page, "Devoir 1")
        self.assertContains(page, "<strong>1</strong>Remis", html=False)

    def test_student_exam_page_requires_access(self):
        self.client.force_login(self.student)
        page = self.client.get(f"/student/exams/{self.exam.id}/")
        self.assertContains(page, "Vos travaux")
        self.assertContains(page, "Valider le code")
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(f"/student/exams/{self.exam.id}/").status_code, 404)

    def test_student_exam_page_shows_start_after_code(self):
        ExamEnrollment.objects.filter(exam=self.exam, student=self.student).update(code_verified=True)
        self.client.force_login(self.student)
        self.assertContains(self.client.get(f"/student/exams/{self.exam.id}/"), "Commencer l'examen")

    def test_gradebook_matches_results_page(self):
        attempt = self.finished_attempt(self.student, {
            self.q1_ok.question_id: [self.q1_ok.id],
            self.q2_a.question_id: [self.q2_a.id, self.q2_c.id],  # réponse partielle : 1 bonne, 1 fausse → 0 point
        })
        expected = grade_summary(attempt)["final_grade"]
        self.assertEqual(final_grades([attempt])[attempt.id], expected)
        self.client.force_login(self.teacher)
        page = self.client.get(f"/classes/{self.classroom.id}/?tab=notes")
        self.assertContains(page, f"{expected:.2f}".replace(".", ","))

    def test_archived_classes_page(self):
        self.classroom.is_archived = True
        self.classroom.save()
        for user in (self.teacher, self.student):
            self.client.force_login(user)
            self.assertContains(self.client.get("/classes/archived/"), "Machine Learning")
        self.client.force_login(self.student)
        self.assertNotContains(self.client.get("/dashboard/student/"), 'class="class-card"')

    def test_other_student_cannot_see_class(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(f"/classes/{self.classroom.id}/").status_code, 403)
