import csv
import io
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST

from ..importers import LETTERS
from ..models import Profile, Exam, ExamEnrollment, Question, Option, Attempt, Classroom
from ..permissions import is_admin, is_teacher_or_admin, can_manage_exam, can_manage_classroom
from ..services import add_turn_in_counts, audit, close_expired_attempts, enroll_audience
from .common import class_tab, redirect_back

# Même limite que l'import : le formulaire de modification ne doit perdre aucune proposition.
MAX_OPTIONS = len(LETTERS)


def manageable_classrooms(user):
    """Classes dont l'utilisateur est propriétaire ou co-enseignant."""
    return (Classroom.objects
            .filter(Q(owner=user) | Q(memberships__user=user, memberships__role="TEACHER"))
            .distinct())


@login_required
def teacher_dashboard(request):
    if not is_teacher_or_admin(request.user):
        return HttpResponseForbidden("Accès réservé aux enseignants.")
    classrooms = (manageable_classrooms(request.user)
                  .select_related("owner")
                  .annotate(student_count=Count("memberships", filter=Q(memberships__role="STUDENT"), distinct=True),
                            exam_count=Count("exams", distinct=True)))
    standalone_exams = (Exam.objects.filter(teacher=request.user, classroom__isnull=True)
                        .annotate(question_count=Count("questions", distinct=True),
                                  attempt_count=Count("attempts", distinct=True))
                        .order_by("is_archived", "-created_at"))
    return render(request, "qcm/teacher_dashboard.html", {
        "active_classrooms": [c for c in classrooms if not c.is_archived],
        "archived_classrooms": [c for c in classrooms if c.is_archived],
        "exams": standalone_exams,
        "levels": Profile.LEVEL_CHOICES,
        "colors": Classroom.COLOR_CHOICES,
    })


@login_required
def teacher_todo(request):
    """Page « À examiner » : les examens publiés des classes de l'enseignant, avec copies rendues / attribuées."""
    if not is_teacher_or_admin(request.user):
        return redirect("student_todo")
    exams = (Exam.objects.filter(Q(classroom__in=manageable_classrooms(request.user)) | Q(teacher=request.user),
                                 published=True, is_archived=False)
             .distinct().select_related("classroom").order_by("-created_at"))
    # Une copie au temps écoulé jamais rouverte doit compter comme remise.
    close_expired_attempts(Attempt.objects.filter(exam__in=exams))
    exams = add_turn_in_counts(exams)
    return render(request, "qcm/teacher_todo.html", {"exams": exams})


def _parse_duration(value):
    try:
        duration = int(value)
    except (TypeError, ValueError):
        return None
    return duration if 1 <= duration <= 180 else None


ORDERS = {"random": True, "fixed": False}


def _parse_exam_settings(data):
    """Règle de notation et ordre ; un champ absent prend sa valeur par défaut. None si une valeur est inconnue."""
    rule = data.get("multiple_scoring", Exam.PARTIAL)
    questions = data.get("question_order", "random")
    answers = data.get("answer_order", "random")
    if rule not in dict(Exam.SCORING_CHOICES) or questions not in ORDERS or answers not in ORDERS:
        return None
    return {"multiple_scoring": rule, "shuffle_questions": ORDERS[questions], "shuffle_answers": ORDERS[answers]}


def _parse_exam_window(request):
    """Ouverture / fermeture facultatives (#9). Renvoie (opens_at, closes_at, erreur)."""
    values = []
    for field, label in (("opens_at", "d'ouverture"), ("closes_at", "de fermeture")):
        raw = request.POST.get(field, "").strip()
        if not raw:
            values.append(None)
            continue
        try:
            parsed = parse_datetime(raw)
            if parsed is not None and timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        except (TypeError, ValueError, OverflowError):
            parsed = None
        if parsed is None:
            return None, None, f"La date {label} est invalide."
        values.append(parsed)
    opens_at, closes_at = values
    if opens_at and closes_at and opens_at >= closes_at:
        return None, None, "La date d'ouverture doit précéder la date de fermeture."
    return opens_at, closes_at, None


def validate_question(text, kind, points, options):
    """Règles d'une question, communes aux formulaires et à l'éditeur graphique (#10).

    `options` : liste ordonnée de (texte, bonne_réponse). Les propositions vides sont ignorées.
    Renvoie (données nettoyées, message d'erreur ou None).
    """
    text = str(text or "").strip()
    kind = kind or Question.SINGLE
    try:
        points = Decimal("1") if points is None else Decimal(str(points).strip().replace(",", "."))
    except (InvalidOperation, TypeError, ValueError):
        points = None
    options = [(str(label).strip(), bool(correct)) for label, correct in list(options)[:MAX_OPTIONS]
               if str(label or "").strip()]
    correct_count = sum(1 for _, correct in options if correct)

    error = None
    if not text:
        error = "L'énoncé de la question est obligatoire."
    elif kind not in dict(Question.TYPE_CHOICES):
        error = "Type de question invalide."
    elif points is None or not points.is_finite() or not (Decimal("0.1") <= points <= Decimal("100")):
        error = "Le barème doit être un nombre entre 0,1 et 100."
    elif len(options) < 2:
        error = "Saisissez au moins deux propositions."
    elif correct_count == 0:
        error = "Sélectionnez au moins une bonne réponse."
    elif kind == Question.SINGLE and correct_count > 1:
        # Une question à réponse unique s'affiche avec des boutons radio : avec deux
        # bonnes réponses, l'étudiant ne pourrait jamais obtenir les points.
        error = "Une question à réponse unique doit avoir exactement une bonne réponse. Choisissez « Réponses multiples »."
    return {"text": text, "kind": kind, "points": points, "options": options}, error


def _question_payload(request):
    """Énoncé, type, barème et propositions envoyés par un formulaire classique."""
    texts = request.POST.getlist("option_text")
    correct = set(request.POST.getlist("correct"))
    return validate_question(request.POST.get("text", ""), request.POST.get("kind", Question.SINGLE),
                             request.POST.get("points", "1"),
                             [(label, str(i) in correct) for i, label in enumerate(texts)])


def write_options(question, options):
    """Remplace les propositions d'une question par `options` [(texte, bonne_réponse)]."""
    question.options.all().delete()
    Option.objects.bulk_create([Option(question=question, text=label[:500], is_correct=correct, position=position)
                                for position, (label, correct) in enumerate(options, 1)])


def _questions_locked(exam):
    """Règle 8 : questions figées dès la publication ou la première tentative. Renvoie un message ou None."""
    if exam.published:
        return "Examen déjà publié : les questions ne peuvent plus être modifiées."
    if Attempt.objects.filter(exam=exam).exists():
        return ("Modification impossible : cet examen possède déjà des tentatives. "
                "Créez un nouveau brouillon pour modifier les questions.")
    return None


def _option_rows_from_post(request):
    texts = request.POST.getlist("option_text")[:MAX_OPTIONS]
    correct = set(request.POST.getlist("correct"))
    return [{"text": texts[i] if i < len(texts) else "", "correct": str(i) in correct} for i in range(MAX_OPTIONS)]


def _option_rows_from_question(question):
    rows = [{"text": o.text, "correct": o.is_correct} for o in question.options.order_by("position", "id")[:MAX_OPTIONS]]
    rows.extend({"text": "", "correct": False} for _ in range(MAX_OPTIONS - len(rows)))
    return rows


@login_required
@require_POST
def create_exam(request):
    if not is_teacher_or_admin(request.user):
        return HttpResponseForbidden()
    classroom = None
    classroom_id = request.POST.get("classroom_id", "").strip()
    if classroom_id:
        classroom = get_object_or_404(Classroom, pk=classroom_id) if classroom_id.isdigit() else None
        if classroom is None or not can_manage_classroom(request.user, classroom):
            return HttpResponseForbidden("Vous ne gérez pas cette classe.")

    level = request.POST.get("target_level", "").strip()
    audience_mode = request.POST.get("audience_mode", "CLASS" if classroom else "LEVEL").strip()
    duration = _parse_duration(request.POST.get("duration", 60))
    title = request.POST.get("title", "").strip()[:200]
    settings = _parse_exam_settings(request.POST)
    opens_at, closes_at, window_error = _parse_exam_window(request)

    error = None
    if duration is None:
        error = "La durée doit être un nombre entier de minutes entre 1 et 180."
    elif not title:
        error = "Donnez un titre à l'examen."
    elif audience_mode not in dict(Exam.AUDIENCE_CHOICES):
        error = "Mode d'affectation invalide."
    elif audience_mode == "CLASS" and not classroom:
        error = "Le mode « toute la classe » nécessite de créer l'examen depuis une classe."
    elif audience_mode == "LEVEL" and level not in dict(Profile.LEVEL_CHOICES):
        error = "Choisissez le niveau d'études ciblé."
    elif level and level not in dict(Profile.LEVEL_CHOICES):
        error = "Niveau d'études invalide."
    elif settings is None:
        error = "Réglage de notation ou d'ordre invalide."
    elif window_error:
        error = window_error
    if error:
        messages.error(request, error)
        return class_tab(classroom.id, "travaux") if classroom else redirect("teacher_dashboard")

    if not level and classroom:
        level = classroom.study_level
    exam = Exam.objects.create(
        title=title, description=request.POST.get("description", "").strip(),
        teacher=request.user, classroom=classroom, duration_minutes=duration,
        target_level=level, audience_mode=audience_mode, **settings,
        opens_at=opens_at, closes_at=closes_at,
        results_published=request.POST.get("results_published") == "on",
    )
    messages.success(request, "Examen créé en brouillon. Ajoutez maintenant vos questions.")
    return redirect("teacher_exam", exam_id=exam.id)


@login_required
@require_POST
def update_exam_duration(request, exam_id):
    """Modifie la durée d'un examen uniquement tant qu'aucune tentative n'existe."""
    exam = get_object_or_404(Exam, pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    if Attempt.objects.filter(exam=exam).exists():
        messages.error(request, "La durée ne peut plus être modifiée : au moins une tentative d'étudiant existe déjà.")
        return redirect_back(request, "teacher_dashboard")
    duration = _parse_duration(request.POST.get("duration", ""))
    if duration is None:
        messages.error(request, "La durée doit être comprise entre 1 et 180 minutes.")
        return redirect_back(request, "teacher_dashboard")
    exam.duration_minutes = duration
    exam.save(update_fields=["duration_minutes"])
    messages.success(request, f"Durée de « {exam.title} » mise à jour : {duration} minute(s).")
    return redirect_back(request, "teacher_dashboard")


@login_required
@require_POST
@transaction.atomic
def update_exam_window(request, exam_id):
    """Fenêtre d'ouverture (#9) : modifiable à tout moment ; une tentative en cours va au bout de sa durée."""
    exam = get_object_or_404(Exam, pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    opens_at, closes_at, error = _parse_exam_window(request)
    if error:
        messages.error(request, error)
        return redirect("teacher_exam", exam_id=exam.id)
    exam.opens_at, exam.closes_at = opens_at, closes_at
    exam.save(update_fields=["opens_at", "closes_at"])

    def show(moment):
        return f"{timezone.localtime(moment):%d/%m/%Y %H:%M}" if moment else "—"
    audit(request.user, "Fenêtre d'ouverture modifiée", exam, f"{show(opens_at)} → {show(closes_at)}")
    messages.success(request, "Fenêtre d'ouverture de l'examen mise à jour.")
    return redirect("teacher_exam", exam_id=exam.id)


@login_required
@require_POST
def duplicate_exam(request, exam_id):
    """Copie en brouillon (#11) : questions et propositions, sans tentative, affectation ni fenêtre."""
    exam = get_object_or_404(Exam.objects.prefetch_related("questions__options"), pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    classroom = None
    classroom_id = request.POST.get("classroom_id", "").strip()
    if classroom_id:
        classroom = Classroom.objects.filter(pk=classroom_id).first() if classroom_id.isdigit() else None
        if classroom is None or not can_manage_classroom(request.user, classroom):
            return HttpResponseForbidden("Vous ne gérez pas cette classe.")
    if exam.audience_mode == "CLASS" and classroom is None:
        messages.error(request, "Choisissez la classe cible de la copie.")
        return redirect("teacher_exam", exam_id=exam.id)

    with transaction.atomic():
        copy = Exam.objects.create(
            title=f"{exam.title} (copie)"[:200], description=exam.description,
            teacher=request.user, classroom=classroom, duration_minutes=exam.duration_minutes,
            shuffle_questions=exam.shuffle_questions, shuffle_answers=exam.shuffle_answers,
            multiple_scoring=exam.multiple_scoring,
            target_level=(classroom.study_level or exam.target_level) if classroom else exam.target_level,
            audience_mode="CLASS" if classroom else exam.audience_mode,
        )
        for position, question in enumerate(exam.questions.order_by("position", "id"), 1):
            new_question = Question.objects.create(
                exam=copy, text=question.text, question_type=question.question_type,
                duration_seconds=question.duration_seconds, points=question.points, position=position)
            Option.objects.bulk_create(
                Option(question=new_question, text=o.text, is_correct=o.is_correct, position=o.position)
                for o in question.options.all())
        where = f" dans {classroom}" if classroom else ""
        audit(request.user, "Examen dupliqué", exam, f"copie #{copy.pk}{where}")
    messages.success(request, f"Examen dupliqué en brouillon : « {copy.title} ».")
    return redirect("teacher_exam", exam_id=copy.id)


@login_required
@require_POST
def update_exam_settings(request, exam_id):
    """Règle de notation et ordre : modifiables uniquement tant qu'aucune tentative n'existe."""
    exam = get_object_or_404(Exam, pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    settings = _parse_exam_settings(request.POST)
    if Attempt.objects.filter(exam=exam).exists():
        messages.error(request, "Ces réglages ne peuvent plus être modifiés : au moins une tentative d'étudiant existe déjà.")
    elif settings is None:
        messages.error(request, "Réglage de notation ou d'ordre invalide.")
    else:
        Exam.objects.filter(pk=exam.pk).update(**settings)
        messages.success(request, "Réglages de notation et d'ordre enregistrés.")
    return redirect("teacher_exam", exam_id=exam.id)


@login_required
@require_POST
@transaction.atomic
def close_exam(request, exam_id):
    """Clôture : plus de nouvelle tentative ; celles en cours se terminent dans leur temps."""
    exam = get_object_or_404(Exam, pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    if not exam.published or exam.is_archived:
        messages.error(request, "Seul un examen publié et non archivé peut être clôturé.")
    elif Exam.objects.filter(pk=exam.pk, closed_at__isnull=True).update(closed_at=timezone.now()):
        audit(request.user, "Examen clôturé", exam)
        messages.success(request, f"L'examen « {exam.title} » est clôturé.")
    else:
        messages.info(request, "Cet examen est déjà clôturé.")
    return redirect("teacher_exam", exam_id=exam.id)


@login_required
@require_POST
def archive_exam(request, exam_id):
    """Archivage par l'enseignant de l'examen ou l'administration ; l'historique est conservé."""
    exam = get_object_or_404(Exam, pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    admin = is_admin(request.user)
    back = redirect_back(request, "admin_dashboard") if admin else redirect("teacher_exam", exam_id=exam.id)
    attempts = Attempt.objects.filter(exam=exam)
    close_expired_attempts(attempts)
    if not attempts.exists():
        messages.error(request, "Cet examen ne possède aucune tentative : utilisez la suppression normale.")
    elif exam.is_archived:
        messages.info(request, "Cet examen est déjà archivé.")
    elif not admin and attempts.filter(status=Attempt.IN_PROGRESS).exists():
        # Archiver retire l'examen aux étudiants : un enseignant ne peut pas couper une épreuve en cours.
        messages.error(request, "Des tentatives sont en cours : clôturez l'examen, puis archivez-le quand elles sont terminées.")
    else:
        exam.is_archived = True
        exam.archived_at = timezone.now()
        exam.archived_by = request.user
        with transaction.atomic():
            exam.save(update_fields=["is_archived", "archived_at", "archived_by"])
            audit(request.user, "Examen archivé", exam)
        messages.success(request, f"L’examen « {exam.title} » a été archivé. Son historique est conservé.")
    return back


@login_required
@require_POST
def delete_exam(request, exam_id):
    """Supprime un examen et ses questions/options seulement s'il n'a aucune tentative."""
    exam = get_object_or_404(Exam, pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    classroom_id = exam.classroom_id
    if Attempt.objects.filter(exam=exam).exists():
        messages.error(request, "Suppression impossible : des étudiants ont déjà commencé cet examen ou des résultats existent. "
                                "L'historique est conservé.")
        return redirect_back(request, "teacher_dashboard")
    title = exam.title
    with transaction.atomic():
        # Question et Option sont liées à Exam par CASCADE. La vérification des
        # tentatives protège les réponses et les résultats (Attempt.exam est en PROTECT).
        audit(request.user, "Examen supprimé", exam)
        exam.delete()
    messages.success(request, f"L'examen « {title} » et ses questions/propositions ont été supprimés.")
    if classroom_id:
        return class_tab(classroom_id, "travaux")
    return redirect("teacher_dashboard")


@login_required
def teacher_exam(request, exam_id):
    exam = get_object_or_404(Exam.objects.select_related("classroom"), pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    from .question_editor import editor_data  # import local : question_editor importe ce module
    has_attempts = exam.attempts.exists()
    editable = not exam.published and not has_attempts
    return render(request, "qcm/teacher_exam.html", {
        "exam": exam,
        "questions": exam.questions.prefetch_related("options").all(),
        "has_attempts": has_attempts,
        "editable": editable,
        "editor_questions": editor_data(exam) if editable else None,
        "max_options": MAX_OPTIONS,
        "enrollment_count": exam.enrollments.count(),
        "option_slots": range(MAX_OPTIONS),
        "classrooms": manageable_classrooms(request.user).filter(is_archived=False).order_by("name"),
    })


@login_required
@require_POST
def add_question(request, exam_id):
    exam = get_object_or_404(Exam, pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    locked = _questions_locked(exam)
    if locked:
        messages.error(request, locked)
        return redirect("teacher_exam", exam_id=exam.id)
    payload, error = _question_payload(request)
    if error:
        messages.error(request, error)
        return redirect("teacher_exam", exam_id=exam.id)

    with transaction.atomic():
        last = exam.questions.aggregate(last=Max("position"))["last"] or 0
        q = Question.objects.create(exam=exam, text=payload["text"], question_type=payload["kind"],
                                    duration_seconds=0, points=payload["points"], position=last + 1)
        write_options(q, payload["options"])
        audit(request.user, "Question ajoutée", exam, f"question #{q.pk}")
    messages.success(request, "Question ajoutée.")
    return redirect("teacher_exam", exam_id=exam.id)


@login_required
def edit_question(request, exam_id, question_id):
    """Modification d'une question d'un brouillon sans tentative (#10)."""
    exam = get_object_or_404(Exam, pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    locked = _questions_locked(exam)
    if locked:
        messages.error(request, locked)
        return redirect("teacher_exam", exam_id=exam.id)
    question = get_object_or_404(Question, pk=question_id, exam=exam)
    context = {"exam": exam, "question": question, "form_text": question.text,
               "form_kind": question.question_type, "form_points": question.points,
               "option_rows": _option_rows_from_question(question)}
    if request.method == "POST":
        payload, error = _question_payload(request)
        if error:
            messages.error(request, error)
            context.update(form_text=request.POST.get("text", ""),
                           form_kind=request.POST.get("kind", question.question_type),
                           form_points=request.POST.get("points", question.points),
                           option_rows=_option_rows_from_post(request))
            return render(request, "qcm/edit_question.html", context)
        with transaction.atomic():
            question.text, question.question_type, question.points = payload["text"], payload["kind"], payload["points"]
            question.save(update_fields=["text", "question_type", "points"])
            write_options(question, payload["options"])
            audit(request.user, "Question modifiée", exam, f"question n° {question.position}")
        messages.success(request, "Question mise à jour.")
        return redirect("teacher_exam", exam_id=exam.id)
    return render(request, "qcm/edit_question.html", context)


@login_required
@require_POST
def move_question(request, exam_id, question_id):
    """Monter / descendre une question d'un brouillon (#10)."""
    exam = get_object_or_404(Exam, pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    locked = _questions_locked(exam)
    if locked:
        messages.error(request, locked)
        return redirect("teacher_exam", exam_id=exam.id)
    question = get_object_or_404(Question, pk=question_id, exam=exam)
    direction = request.POST.get("direction", "")
    if direction not in ("up", "down"):
        messages.error(request, "Direction de déplacement invalide.")
        return redirect("teacher_exam", exam_id=exam.id)
    questions = list(exam.questions.order_by("position", "id"))
    index = next(i for i, item in enumerate(questions) if item.pk == question.pk)
    target = index - 1 if direction == "up" else index + 1
    if not 0 <= target < len(questions):
        messages.info(request, "Cette question est déjà à sa place.")
        return redirect("teacher_exam", exam_id=exam.id)
    questions[index], questions[target] = questions[target], questions[index]
    with transaction.atomic():
        for position, item in enumerate(questions, 1):
            if item.position != position:
                item.position = position
                item.save(update_fields=["position"])
        audit(request.user, "Ordre des questions modifié", exam)
    messages.success(request, "Ordre des questions mis à jour.")
    return redirect("teacher_exam", exam_id=exam.id)


@login_required
@require_POST
def delete_question(request, exam_id, question_id):
    exam = get_object_or_404(Exam, pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    if exam.published:
        messages.error(request, "Impossible de supprimer une question après publication de l'examen.")
        return redirect("teacher_exam", exam_id=exam.id)
    question = get_object_or_404(Question, pk=question_id, exam=exam)
    if Attempt.objects.filter(exam=exam).exists():
        messages.error(request, "Suppression impossible : cet examen possède déjà des tentatives. Créez un nouveau brouillon pour modifier les questions.")
        return redirect("teacher_exam", exam_id=exam.id)
    audit(request.user, "Question supprimée", exam, f"question #{question.pk} : {question.text[:80]}")
    question.delete()
    for position, item in enumerate(exam.questions.order_by("position", "id"), 1):
        if item.position != position:
            item.position = position
            item.save(update_fields=["position"])
    messages.success(request, "Question supprimée.")
    return redirect("teacher_exam", exam_id=exam.id)


@login_required
@require_POST
def publish_exam(request, exam_id):
    exam = get_object_or_404(Exam, pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    if exam.published:
        messages.info(request, "Cet examen est déjà publié.")
        return redirect("teacher_exam", exam_id=exam.id)
    if exam.audience_mode == "LEVEL" and not exam.target_level:
        messages.error(request, "Définissez le niveau d'études de cet examen avant sa publication.")
        return redirect("teacher_exam", exam_id=exam.id)
    if exam.audience_mode == "CLASS" and not exam.classroom_id:
        messages.error(request, "Cet examen n'est rattaché à aucune classe.")
        return redirect("teacher_exam", exam_id=exam.id)
    questions = list(exam.questions.prefetch_related("options"))
    if not questions:
        messages.error(request, "Ajoutez au moins une question.")
        return redirect("teacher_exam", exam_id=exam.id)
    incomplete = [str(q.position) for q in questions
                  if len(q.options.all()) < 2 or not any(o.is_correct for o in q.options.all())]
    if incomplete:
        messages.error(request, "Publication impossible : questions incomplètes (au moins 2 propositions et 1 bonne réponse) : n° "
                       + ", ".join(incomplete))
        return redirect("teacher_exam", exam_id=exam.id)
    with transaction.atomic():
        exam.published = True
        exam.save(update_fields=["published"])
        enroll_audience(exam)
        audit(request.user, "Examen publié", exam)
    messages.success(request, f"Examen publié. Communiquez le code d'accès {exam.access_code} aux étudiants concernés.")
    return redirect("teacher_exam", exam_id=exam.id)


@login_required
@require_POST
def import_exam_students(request, exam_id):
    exam = get_object_or_404(Exam, pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    uploaded = request.FILES.get("student_file")
    if not uploaded:
        messages.error(request, "Sélectionnez un fichier CSV contenant une colonne matricule.")
        return redirect("teacher_exam", exam_id=exam.id)
    try:
        content = uploaded.read().decode("utf-8-sig")
        sample = content[:2048]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(content), dialect=dialect)
        if not reader.fieldnames:
            raise ValueError("Le fichier CSV doit contenir une ligne d'en-tête.")
        key = next((h for h in reader.fieldnames if h.strip().lower() in ("matricule", "student_number", "numero_etudiant", "numéro étudiant")), None)
        if not key:
            raise ValueError("Ajoutez une colonne nommée matricule.")
        added = removed = 0
        unknown = []
        with transaction.atomic():
            if exam.audience_mode != "LIST":
                # Passage en mode liste : seuls les étudiants du fichier restent autorisés.
                removed = exam.enrollments.all().delete()[0]
            exam.audience_mode = "LIST"
            exam.save(update_fields=["audience_mode"])
            for row in reader:
                number = (row.get(key) or "").strip()
                if not number:
                    continue
                profile = Profile.objects.select_related("user").filter(student_number=number, role="STUDENT").first()
                if not profile:
                    unknown.append(number)
                    continue
                _, created = ExamEnrollment.objects.get_or_create(exam=exam, student=profile.user, defaults={"source": "LIST"})
                added += int(created)
            audit(request.user, "Liste d'étudiants importée", exam, f"{added} ajouté(s), {removed} retiré(s)")
        messages.success(request, f"Import terminé : {added} étudiant(s) ajouté(s).")
        if unknown:
            messages.warning(request, "Matricules non reconnus : " + ", ".join(unknown[:20]))
    except (UnicodeDecodeError, ValueError, csv.Error) as exc:
        messages.error(request, str(exc))
    return redirect("teacher_exam", exam_id=exam.id)


@login_required
@require_POST
@transaction.atomic
def add_exam_student(request, exam_id):
    """Inscription d'un seul étudiant par matricule ; les autres inscrits ne sont pas touchés."""
    exam = get_object_or_404(Exam, pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    number = request.POST.get("student_number", "").strip()
    # Le matricule n'est pas unique en base : deux résultats suffisent à détecter l'ambiguïté.
    students = list(User.objects.filter(profile__student_number=number, profile__role="STUDENT")[:2]) if number else []
    if exam.is_archived or exam.closed_at:
        messages.error(request, "Cet examen est clôturé ou archivé : plus aucune inscription n'est possible.")
    elif not students:
        messages.error(request, "Aucun compte étudiant ne porte ce matricule.")
    elif len(students) > 1:
        messages.error(request, "Plusieurs comptes portent ce matricule : corrigez-les avant d'inscrire l'étudiant.")
    else:
        student = students[0]
        name = student.get_full_name() or student.username
        enrollment, created = ExamEnrollment.objects.get_or_create(exam=exam, student=student,
                                                                   defaults={"source": "LIST"})
        if not created and enrollment.source == "LIST":
            messages.info(request, f"{name} est déjà inscrit à cet examen.")
        else:
            if not created:
                enrollment.source = "LIST"
                enrollment.save(update_fields=["source"])
            audit(request.user, "Étudiant inscrit à un examen", exam, f"{student.username} (matricule {number})")
            messages.success(request, f"Inscription enregistrée : {name}.")
    return redirect("teacher_exam", exam_id=exam.id)
