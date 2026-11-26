"""
Logique métier partagée entre les vues : affectations aux examens, déroulement des tentatives
et notation.
Garder ici ce qui n'est pas spécifique à une page facilite les tests et le travail en équipe.
"""
from collections import Counter
from datetime import timedelta
from decimal import Decimal
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import Attempt, Exam, ExamEnrollment, ClassroomMembership, Question, Response


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
    for exam in Exam.objects.filter(classroom=classroom, audience_mode="CLASS", published=True, is_archived=False,
                                    closed_at__isnull=True):
        ExamEnrollment.objects.get_or_create(exam=exam, student=student, defaults={"source": "CLASS"})


def unenroll_student_from_class_exams(student, classroom):
    """Au départ d'une classe, retirer les affectations CLASS non entamées (l'historique est conservé)."""
    ExamEnrollment.objects.filter(
        student=student, source="CLASS", exam__classroom=classroom,
    ).exclude(exam__attempts__student=student).delete()


def visible_exams_for_student(user, classroom=None):
    """Examens publiés, non archivés, auxquels l'étudiant a accès ; clôturés : seulement s'il les a commencés."""
    level = getattr(getattr(user, "profile", None), "study_level", "")
    criteria = Q(audience_mode="LIST", enrollments__student=user)
    criteria |= Q(audience_mode="CLASS", classroom__memberships__user=user,
                  classroom__memberships__role=ClassroomMembership.STUDENT)
    if level:
        criteria |= Q(audience_mode="LEVEL", target_level=level)
    started = Attempt.objects.filter(student=user).values("exam_id")
    qs = Exam.objects.filter(criteria, published=True, is_archived=False)
    qs = qs.filter(Q(closed_at__isnull=True) | Q(pk__in=started))
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
def build_grading(exam, questions=None):
    """Règle et barème d'un examen, sous la forme conservée sur la tentative (JSON)."""
    if questions is None:
        questions = exam.questions.prefetch_related("options")
    return {
        "multiple_scoring": exam.multiple_scoring,
        "questions": {str(q.id): {"type": q.question_type, "points": str(q.points),
                                  "correct": [o.id for o in q.options.all() if o.is_correct]}
                      for q in questions},
    }


def grading_of(attempt):
    """Barème appliqué à la tentative : figé au démarrage, sinon (anciennes tentatives) celui de l'examen."""
    return attempt.grading_snapshot or build_grading(attempt.exam)


def calculate_score(attempt, grading=None):
    grading = grading or grading_of(attempt)
    total = Decimal("0")
    for response in attempt.responses.all():
        q = grading["questions"].get(str(response.question_id))
        if not q or not q["correct"]:
            continue
        correct = set(q["correct"])
        selected = set(response.selected_option_ids)
        if q["type"] == Question.SINGLE or grading["multiple_scoring"] == Exam.ALL_OR_NOTHING:
            fraction = Decimal("1") if selected == correct else Decimal("0")
        else:
            fraction = max(Decimal("0"), min(Decimal("1"), Decimal(len(selected & correct) - len(selected - correct)) / Decimal(len(correct))))
        total += Decimal(q["points"]) * fraction
    return total


def exam_max_score(exam):
    """Le maximum inclut TOUTES les questions, y compris celles laissées blanches."""
    return sum((q.points for q in exam.questions.all()), Decimal("0"))


def grade_summary(attempt, grading=None):
    grading = grading or grading_of(attempt)
    score = calculate_score(attempt, grading)
    max_score = sum((Decimal(q["points"]) for q in grading["questions"].values()), Decimal("0"))
    percent = (score / max_score * Decimal("100")) if max_score else Decimal("0")
    final_grade = (score / max_score * Decimal("20")) if max_score else Decimal("0")
    return {
        "score": score,
        "max_score": max_score,
        "percent": percent.quantize(Decimal("0.1")),
        "final_grade": final_grade.quantize(Decimal("0.01")),
    }


RESULT_HEADER = ["Identifiant", "Matricule", "Nom", "Prénom", "Statut", "Nature du score", "Motif de clôture",
                 "Début", "Fin", "Score obtenu", "Score maximal", "Pourcentage (%)", "Note finale (/20)", "Violations"]


def exam_attempts(exam):
    """Tentatives d'un examen, avec de quoi les noter sans requête supplémentaire par copie."""
    # Seules les vraies violations comptent (pas les doublons ignorés ni les reprises).
    violations = Count("security_events",
                       filter=Q(security_events__event_type__in=["TAB_SWITCH", "FULLSCREEN_EXIT"]))
    return (Attempt.objects.filter(exam=exam).select_related("exam", "student", "student__profile")
            .prefetch_related("responses").annotate(violation_count=violations))


def graded_attempts(exam, attempts):
    """Couples (tentative, notes) ; le barème des copies sans barème figé n'est calculé qu'une fois."""
    fallback = None
    for attempt in attempts:
        if not attempt.grading_snapshot and fallback is None:
            fallback = build_grading(exam)
        yield attempt, grade_summary(attempt, attempt.grading_snapshot or fallback)


def result_rows(exam):
    """Lignes d'export (colonnes de RESULT_HEADER) : texte, nombres et dates locales, communes à tous les formats."""
    def local(moment):
        return timezone.localtime(moment).replace(tzinfo=None) if moment else None

    for attempt, g in graded_attempts(exam, exam_attempts(exam).order_by("student__username", "-started_at")):
        profile = getattr(attempt.student, "profile", None)
        yield [
            attempt.student.username,
            profile.student_number if profile else "",
            attempt.student.last_name,
            attempt.student.first_name,
            attempt.get_status_display(),
            "Provisoire" if attempt.status == Attempt.IN_PROGRESS else "Définitif",
            "Violation des règles" if attempt.status == Attempt.TERMINATED_SECURITY else attempt.get_status_display(),
            local(attempt.started_at),
            local(attempt.ended_at),
            g["score"].quantize(Decimal("0.01")),
            g["max_score"].quantize(Decimal("0.01")),
            g["percent"],
            g["final_grade"],
            attempt.violation_count,
        ]


# --------------------------------------------------------------------------- #
# Analyse par question
# --------------------------------------------------------------------------- #
TOO_EASY_ABOVE, TOO_HARD_BELOW = 90, 20  # % de réussite


def question_stats(exam):
    """
    Réussite, non-réponse et propositions choisies pour chaque question, sur les copies terminées
    (une tentative interrompue est remplacée : elle ne compte pas). Réussite = réponse exactement
    juste selon le barème figé de la copie, même en notation partielle.
    """
    done = exam.attempts.filter(status__in=[Attempt.COMPLETED, Attempt.TIME_EXPIRED, Attempt.TERMINATED_SECURITY])
    snapshots = dict(done.values_list("pk", "grading_snapshot"))
    if not snapshots:
        return []
    questions = list(exam.questions.prefetch_related("options"))
    fallback = None if all(snapshots.values()) else build_grading(exam, questions)
    # ponytail: réponses agrégées en Python (une seule requête) car les choix sont en JSON ;
    # passer à une agrégation SQL si un examen dépasse quelques dizaines de milliers de réponses.
    responses = {(attempt, question): selected for attempt, question, selected in
                 Response.objects.filter(attempt__in=done)
                 .values_list("attempt_id", "question_id", "selected_option_ids")}

    stats = []
    for question in questions:
        total = right = blank = 0
        chosen, key = Counter(), set()
        for pk, snapshot in snapshots.items():
            graded = (snapshot or fallback)["questions"].get(str(question.id))
            if graded is None:
                continue
            total += 1
            correct, selected = set(graded["correct"]), set(responses.get((pk, question.id), ()))
            key |= correct
            chosen.update(selected)
            blank += not selected
            right += bool(correct) and selected == correct
        if not total:
            continue

        def rate(count):
            return round(100 * count / total, 1)

        # Comparaison en entiers : exactement 90 % ou 20 % n'est pas signalé.
        level = "easy" if 100 * right > TOO_EASY_ABOVE * total else "hard" if 100 * right < TOO_HARD_BELOW * total else ""
        stats.append({
            "question": question, "total": total, "level": level,
            "success_rate": rate(right), "blank_rate": rate(blank),
            "options": [{"option": o, "count": chosen[o.id], "rate": rate(chosen[o.id]), "correct": o.id in key}
                        for o in question.options.all()],
        })
    return stats
