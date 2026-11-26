"""
Logique métier partagée entre les vues : affectations aux examens, déroulement des tentatives
et notation.
Garder ici ce qui n'est pas spécifique à une page facilite les tests et le travail en équipe.
"""
from datetime import timedelta
from decimal import Decimal
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Attempt, Exam, ExamEnrollment, ClassroomMembership, Response


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
# Déroulement d'une tentative (temps contrôlé côté serveur)
# --------------------------------------------------------------------------- #
def locked_attempts():
    """
    Tentatives verrouillées jusqu'à la fin de la transaction : toute route qui en modifie une
    passe par ici. Seule la ligne de la tentative est verrouillée (of="self"), sinon les
    étudiants d'un même examen s'attendraient les uns les autres.
    """
    return Attempt.objects.select_for_update(of=("self",)).select_related("exam")


def question_time_seconds(attempt, index=None):
    """Répartit exactement la durée totale, en secondes entières, entre les questions."""
    count = len(attempt.question_order)
    if count <= 0:
        return 0
    if index is None:
        index = attempt.current_index
    total_seconds = int(attempt.exam.duration_minutes) * 60
    base_seconds, extra_seconds = divmod(total_seconds, count)
    # Les premières questions reçoivent chacune une seconde supplémentaire
    # lorsque la division ne tombe pas juste : la somme est exactement égale
    # à la durée totale de l'examen.
    return base_seconds + (1 if 0 <= index < extra_seconds else 0)


@transaction.atomic
def advance(attempt):
    """Passe à la question suivante ; sans réponse enregistrée, la question est notée blanche."""
    Response.objects.get_or_create(
        attempt=attempt, question_id=attempt.question_order[attempt.current_index],
        defaults={"selected_option_ids": [], "auto_submitted": True},
    )
    attempt.current_index += 1
    if attempt.current_index >= len(attempt.question_order):
        close_attempt(attempt, Attempt.COMPLETED)
        return
    now = timezone.now()
    attempt.question_started_at = now
    allotted = timedelta(seconds=question_time_seconds(attempt, attempt.current_index))
    attempt.question_deadline = min(attempt.global_deadline, now + allotted)
    attempt.save(update_fields=["current_index", "question_started_at", "question_deadline"])


def close_attempt(attempt, status):
    attempt.status = status
    # Temps écoulé : la fin est l'échéance, même si la clôture est constatée plus tard.
    attempt.ended_at = attempt.global_deadline if status == Attempt.TIME_EXPIRED else timezone.now()
    attempt.save(update_fields=["status", "ended_at"])


def apply_deadlines(attempt):
    """
    Applique les échéances serveur : clôture si le temps global est écoulé, passage à la question
    suivante quand le temps d'une question est écoulé. La sélection sauvegardée automatiquement
    est conservée. Ne fait rien si la tentative est close. À appeler sur une tentative verrouillée.
    """
    while attempt.status == Attempt.IN_PROGRESS:
        now = timezone.now()
        if now < min(attempt.global_deadline, attempt.question_deadline):
            break
        current = attempt.question_order[attempt.current_index:attempt.current_index + 1]
        Response.objects.filter(attempt=attempt, question_id__in=current).update(auto_submitted=True)
        if now >= attempt.global_deadline:
            close_attempt(attempt, Attempt.TIME_EXPIRED)
        else:
            advance(attempt)
    return attempt


def close_expired_attempts(attempts=None):
    """Clôt les tentatives dont le temps global est écoulé, même si l'étudiant n'est pas revenu."""
    attempts = Attempt.objects.all() if attempts is None else attempts
    expired = attempts.filter(status=Attempt.IN_PROGRESS, global_deadline__lte=timezone.now())
    closed = 0
    for pk in list(expired.values_list("pk", flat=True)):
        with transaction.atomic():
            attempt = locked_attempts().get(pk=pk)
            if attempt.status == Attempt.IN_PROGRESS:  # a pu changer avant l'obtention du verrou
                apply_deadlines(attempt)
                closed += attempt.status != Attempt.IN_PROGRESS
    return closed


# --------------------------------------------------------------------------- #
# Notation
# --------------------------------------------------------------------------- #
def calculate_score(attempt):
    total = Decimal("0")
    for response in attempt.responses.select_related("question").all():
        q = response.question
        correct = set(q.options.filter(is_correct=True).values_list("id", flat=True))
        selected = set(response.selected_option_ids)
        if not correct:
            continue
        if q.question_type == "SINGLE":
            fraction = Decimal("1") if selected == correct else Decimal("0")
        else:
            fraction = max(Decimal("0"), min(Decimal("1"), Decimal(len(selected & correct) - len(selected - correct)) / Decimal(len(correct))))
        total += q.points * fraction
    return total


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
