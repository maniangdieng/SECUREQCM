"""
Logique métier partagée entre les vues : affectations aux examens, déroulement des tentatives
et notation.
Garder ici ce qui n'est pas spécifique à une page facilite les tests et le travail en équipe.
"""
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Q, prefetch_related_objects
from django.utils import timezone

from .models import Attempt, AuditLog, Exam, ExamEnrollment, ClassroomMembership, Question, Response


# Événements de sécurité : seules ces violations sont comptées.
VIOLATION_LABELS = {"TAB_SWITCH": "Changement d'onglet", "FULLSCREEN_EXIT": "Sortie du plein écran",
                    "FOCUS_AWAY": "Perte de focus prolongée"}
RESUME_EVENT = "RESUME_AUTHORIZED"


# --------------------------------------------------------------------------- #
# Journal des opérations administratives
# --------------------------------------------------------------------------- #
def audit(actor, action, target, details=""):
    """Journalise une opération. `target` est un objet encore en base : appeler avant une suppression."""
    AuditLog.objects.create(actor=actor, actor_name=actor.username, action=action,
                            target=f"{target} (#{target.pk})"[:300], details=details[:500])


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


def enroll_student_in_level_exams(student):
    """Nouveau compte étudiant : l'affecter aux examens de son niveau déjà publiés."""
    for exam in Exam.objects.filter(published=True, is_archived=False, closed_at__isnull=True,
                                    audience_mode="LEVEL", target_level=student.profile.study_level):
        ExamEnrollment.objects.get_or_create(exam=exam, student=student, defaults={"source": "LEVEL"})


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
    # Inscription individuelle ou par liste : elle vaut quel que soit le public visé par l'examen.
    criteria |= Q(enrollments__student=user, enrollments__source="LIST")
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


def final_grades(attempts):
    """
    Note /20 de plusieurs tentatives (onglet « Notes » d'une classe : étudiants × examens).
    Même calcul que grade_summary : barème figé au démarrage, règle « tout ou rien » comprise.
    Les réponses sont chargées en une requête ; le barème de repli (anciennes copies sans barème
    figé) n'est calculé qu'une fois par examen.
    """
    attempts = list(attempts)
    prefetch_related_objects(attempts, "responses")
    fallback = {}
    grades = {}
    for attempt in attempts:
        grading = attempt.grading_snapshot
        if not grading:
            if attempt.exam_id not in fallback:
                fallback[attempt.exam_id] = build_grading(attempt.exam)
            grading = fallback[attempt.exam_id]
        grades[attempt.id] = grade_summary(attempt, grading)["final_grade"]
    return grades


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
        **answer_counts(attempt, grading),
    }


def answer_counts(attempt, grading):
    """Réponses justes, fausses (une réponse partielle en fait partie) et sans réponse d'une copie."""
    selected = {str(r.question_id): set(r.selected_option_ids) for r in attempt.responses.all()}
    counts = {"right_count": 0, "wrong_count": 0, "blank_count": 0}
    for question_id, graded in grading["questions"].items():
        chosen = selected.get(question_id)
        if not chosen:
            counts["blank_count"] += 1
        elif graded["correct"] and chosen == set(graded["correct"]):
            counts["right_count"] += 1
        else:
            counts["wrong_count"] += 1
    return counts


# --------------------------------------------------------------------------- #
# Résultats d'un examen
# --------------------------------------------------------------------------- #
# Copies closes qui comptent dans les statistiques (une tentative interrompue est remplacée).
GRADED_STATUSES = [Attempt.COMPLETED, Attempt.TIME_EXPIRED, Attempt.TERMINATED_SECURITY]
PASS_MARK = Decimal("10")  # note sur 20 à partir de laquelle une copie est réussie

RESULT_HEADER = ["Identifiant examen", "Examen", "Identifiant", "Matricule", "Nom", "Prénom", "Statut",
                 "Nature du score", "Motif de clôture", "Début", "Fin", "Durée effective (min)", "Score obtenu",
                 "Score maximal", "Pourcentage (%)", "Note finale (/20)", "Réponses justes", "Réponses fausses",
                 "Sans réponse", "Violations", "Détail des violations"]


def exam_attempts(exam):
    """Tentatives d'un examen, avec de quoi les noter sans requête supplémentaire par copie."""
    # Seules les vraies violations comptent (pas les doublons ignorés ni les reprises).
    violations = Count("security_events", filter=Q(security_events__event_type__in=list(VIOLATION_LABELS)))
    return (Attempt.objects.filter(exam=exam).select_related("exam", "student", "student__profile")
            .prefetch_related("responses", "security_events").annotate(violation_count=violations))


def graded_attempts(exam, attempts):
    """Couples (tentative, notes) ; le barème des copies sans barème figé n'est calculé qu'une fois."""
    fallback = None
    for attempt in attempts:
        if not attempt.grading_snapshot and fallback is None:
            fallback = build_grading(exam)
        yield attempt, grade_summary(attempt, attempt.grading_snapshot or fallback)


def effective_minutes(attempt):
    """Temps de composition d'une copie close, sans l'interruption entre une clôture et sa reprise."""
    if not attempt.ended_at:
        return None
    spent = attempt.ended_at - attempt.started_at
    for event in attempt.security_events.all():
        if event.event_type == RESUME_EVENT and "closed_at" in event.details:
            spent -= event.created_at - datetime.fromisoformat(event.details["closed_at"])
    return (Decimal(max(int(spent.total_seconds()), 0)) / 60).quantize(Decimal("0.01"))


def violation_detail(attempt):
    counts = Counter(event.event_type for event in attempt.security_events.all())
    return " ; ".join(f"{label} : {counts[kind]}" for kind, label in VIOLATION_LABELS.items() if counts[kind])


def graded_rows(exam, *ordering):
    """Une ligne par copie : tentative, notes, durée effective et détail des violations."""
    for attempt, grade in graded_attempts(exam, exam_attempts(exam).order_by(*ordering)):
        yield {"attempt": attempt, **grade, "minutes": effective_minutes(attempt),
               "violation_detail": violation_detail(attempt)}


def results_summary(rows):
    """Effectifs par statut, moyenne et taux de réussite des copies de graded_rows()."""
    counts = Counter(row["attempt"].status for row in rows)
    grades = [row["final_grade"] for row in rows if row["attempt"].status in GRADED_STATUSES]
    return {
        # « Interrompue » est rare (posée par l'administration) : affichée seulement s'il y en a.
        "status_counts": [(label, counts[status]) for status, label in Attempt.STATUS_CHOICES
                          if counts[status] or status != Attempt.INTERRUPTED],
        "graded_count": len(grades),
        "average": sum(grades) / len(grades) if grades else None,
        "success_rate": round(100 * sum(g >= PASS_MARK for g in grades) / len(grades), 1) if grades else None,
    }


def result_rows(exam):
    """Lignes d'export (colonnes de RESULT_HEADER) : texte, nombres et dates locales, communes à tous les formats."""
    def local(moment):
        return timezone.localtime(moment).replace(tzinfo=None) if moment else None

    for row in graded_rows(exam, "student__username", "-started_at"):
        attempt = row["attempt"]
        profile = getattr(attempt.student, "profile", None)
        yield [
            exam.id,
            exam.title,
            attempt.student.username,
            profile.student_number if profile else "",
            attempt.student.last_name,
            attempt.student.first_name,
            attempt.get_status_display(),
            "Provisoire" if attempt.status == Attempt.IN_PROGRESS else "Définitif",
            "Violation des règles" if attempt.status == Attempt.TERMINATED_SECURITY else attempt.get_status_display(),
            local(attempt.started_at),
            local(attempt.ended_at),
            row["minutes"],
            row["score"].quantize(Decimal("0.01")),
            row["max_score"].quantize(Decimal("0.01")),
            row["percent"],
            row["final_grade"],
            row["right_count"],
            row["wrong_count"],
            row["blank_count"],
            attempt.violation_count,
            row["violation_detail"],
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
    done = exam.attempts.filter(status__in=GRADED_STATUSES)
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


def add_turn_in_counts(exams):
    """Ajoute assigned_count (inscrits) et turned_in_count (étudiants ayant remis) à chaque examen.

    Deux requêtes groupées à part : réunis dans la requête des examens, les Count sur inscriptions,
    copies et questions multiplient les lignes entre eux (plusieurs secondes à 200 étudiants).
    """
    exams = list(exams)
    assigned = dict(ExamEnrollment.objects.filter(exam__in=exams).order_by()
                    .values_list("exam").annotate(Count("id")))
    turned_in = dict(Attempt.objects.filter(exam__in=exams).exclude(status=Attempt.IN_PROGRESS).order_by()
                     .values_list("exam").annotate(Count("student", distinct=True)))
    for exam in exams:
        exam.assigned_count = assigned.get(exam.id, 0)
        exam.turned_in_count = turned_in.get(exam.id, 0)
    return exams
