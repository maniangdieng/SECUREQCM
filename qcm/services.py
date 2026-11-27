"""
Logique métier partagée entre les vues : affectations aux examens et notation.
Garder ici ce qui n'est pas spécifique à une page facilite les tests et le travail en équipe.
"""
from decimal import Decimal
from django.contrib.auth.models import User
from django.db.models import Q

from .models import ClassroomMembership, Exam, ExamEnrollment, Option, Question, Response


# --------------------------------------------------------------------------- #
# Affectations
# --------------------------------------------------------------------------- #
def enroll_audience(exam):
    """
    Crée les affectations automatiques d'un examen publié :
    - CLASS : tous les étudiants membres de la classe ;
    - LEVEL : tous les étudiants du niveau ciblé ;
    - LIST : rien d'automatique (import CSV par l'enseignant).
    """
    if exam.audience_mode == "CLASS" and exam.classroom_id:
        students = User.objects.filter(
            classroom_memberships__classroom_id=exam.classroom_id,
            classroom_memberships__role=ClassroomMembership.STUDENT,
        )
        source = "CLASS"
    elif exam.audience_mode == "LEVEL" and exam.target_level:
        students = User.objects.filter(profile__role="STUDENT", profile__study_level=exam.target_level)
        source = "LEVEL"
    else:
        return 0
    created = 0
    for student in students.iterator():
        _, was_created = ExamEnrollment.objects.get_or_create(exam=exam, student=student, defaults={"source": source})
        created += int(was_created)
    return created


def enroll_student_in_class_exams(student, classroom):
    """À l'arrivée d'un étudiant dans une classe, l'affecter aux examens CLASS déjà publiés."""
    for exam in Exam.objects.filter(classroom=classroom, audience_mode="CLASS", published=True, is_archived=False):
        ExamEnrollment.objects.get_or_create(exam=exam, student=student, defaults={"source": "CLASS"})


def unenroll_student_from_class_exams(student, classroom):
    """Au départ d'une classe, retirer les affectations CLASS non entamées (l'historique est conservé)."""
    ExamEnrollment.objects.filter(
        student=student, source="CLASS", exam__classroom=classroom,
    ).exclude(exam__attempts__student=student).delete()


def visible_exams_for_student(user, classroom=None):
    """Examens publiés, non archivés, auxquels l'étudiant a accès."""
    level = getattr(getattr(user, "profile", None), "study_level", "")
    criteria = Q(audience_mode="LIST", enrollments__student=user)
    criteria |= Q(audience_mode="CLASS", classroom__memberships__user=user,
                  classroom__memberships__role=ClassroomMembership.STUDENT)
    if level:
        criteria |= Q(audience_mode="LEVEL", target_level=level)
    qs = Exam.objects.filter(criteria, published=True, is_archived=False)
    if classroom is not None:
        qs = qs.filter(classroom=classroom)
    return qs.distinct().select_related("classroom").order_by("-created_at")


# --------------------------------------------------------------------------- #
# Notation
# --------------------------------------------------------------------------- #
def response_points(question_type, points, correct, selected):
    """Points obtenus pour une réponse (règle de notation unique, utilisée partout)."""
    if not correct:
        return Decimal("0")
    if question_type == "SINGLE":
        fraction = Decimal("1") if selected == correct else Decimal("0")
    else:
        fraction = max(Decimal("0"), min(Decimal("1"), Decimal(len(selected & correct) - len(selected - correct)) / Decimal(len(correct))))
    return points * fraction


def calculate_score(attempt):
    total = Decimal("0")
    for response in attempt.responses.select_related("question").all():
        q = response.question
        correct = set(q.options.filter(is_correct=True).values_list("id", flat=True))
        total += response_points(q.question_type, q.points, correct, set(response.selected_option_ids))
    return total


def final_grades(attempts):
    """
    Note /20 de plusieurs tentatives en un nombre constant de requêtes
    (onglet « Notes » d'une classe : étudiants × examens). Même règle que grade_summary.
    """
    attempts = list(attempts)
    exam_ids = {a.exam_id for a in attempts}
    questions = {q.id: q for q in Question.objects.filter(exam_id__in=exam_ids)}
    correct = {}
    for option_id, question_id in Option.objects.filter(question_id__in=questions, is_correct=True).values_list("id", "question_id"):
        correct.setdefault(question_id, set()).add(option_id)
    max_by_exam = {}
    for q in questions.values():
        max_by_exam[q.exam_id] = max_by_exam.get(q.exam_id, Decimal("0")) + q.points
    score = {a.id: Decimal("0") for a in attempts}
    for r in Response.objects.filter(attempt__in=attempts).only("attempt_id", "question_id", "selected_option_ids"):
        q = questions.get(r.question_id)
        if q:
            score[r.attempt_id] += response_points(q.question_type, q.points, correct.get(q.id, set()), set(r.selected_option_ids))
    grades = {}
    for a in attempts:
        max_score = max_by_exam.get(a.exam_id, Decimal("0"))
        grades[a.id] = (score[a.id] / max_score * Decimal("20")).quantize(Decimal("0.01")) if max_score else Decimal("0.00")
    return grades


def exam_max_score(exam):
    """Le maximum inclut TOUTES les questions, y compris celles laissées blanches."""
    return sum((q.points for q in exam.questions.all()), Decimal("0"))


def grade_summary(attempt, max_score=None):
    score = calculate_score(attempt)
    if max_score is None:
        max_score = exam_max_score(attempt.exam)
    percent = (score / max_score * Decimal("100")) if max_score else Decimal("0")
    final_grade = (score / max_score * Decimal("20")) if max_score else Decimal("0")
    return {
        "score": score,
        "max_score": max_score,
        "percent": percent.quantize(Decimal("0.1")),
        "final_grade": final_grade.quantize(Decimal("0.01")),
    }
