import csv
import io
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import Profile, Exam, ExamEnrollment, Question, Option, Attempt, Classroom
from ..permissions import is_admin, is_teacher_or_admin, can_manage_exam, can_manage_classroom
from ..services import close_expired_attempts, enroll_audience
from .common import redirect_back

MAX_OPTIONS = 6


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
    fallback = ("classroom_detail", {"classroom_id": classroom.id}) if classroom else ("teacher_dashboard", {})

    level = request.POST.get("target_level", "").strip()
    audience_mode = request.POST.get("audience_mode", "CLASS" if classroom else "LEVEL").strip()
    duration = _parse_duration(request.POST.get("duration", 60))
    title = request.POST.get("title", "").strip()[:200]
    settings = _parse_exam_settings(request.POST)

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
    if error:
        messages.error(request, error)
        return redirect(fallback[0], **fallback[1])

    if not level and classroom:
        level = classroom.study_level
    exam = Exam.objects.create(
        title=title, description=request.POST.get("description", "").strip(),
        teacher=request.user, classroom=classroom, duration_minutes=duration,
        target_level=level, audience_mode=audience_mode, **settings,
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
def close_exam(request, exam_id):
    """Clôture : plus de nouvelle tentative ; celles en cours se terminent dans leur temps."""
    exam = get_object_or_404(Exam, pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    if not exam.published or exam.is_archived:
        messages.error(request, "Seul un examen publié et non archivé peut être clôturé.")
    elif Exam.objects.filter(pk=exam.pk, closed_at__isnull=True).update(closed_at=timezone.now()):
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
        exam.save(update_fields=["is_archived", "archived_at", "archived_by"])
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
        exam.delete()
    messages.success(request, f"L'examen « {title} » et ses questions/propositions ont été supprimés.")
    if classroom_id:
        return redirect("classroom_detail", classroom_id=classroom_id)
    return redirect("teacher_dashboard")


@login_required
def teacher_exam(request, exam_id):
    exam = get_object_or_404(Exam.objects.select_related("classroom"), pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    return render(request, "qcm/teacher_exam.html", {
        "exam": exam,
        "questions": exam.questions.prefetch_related("options").all(),
        "has_attempts": exam.attempts.exists(),
        "enrollment_count": exam.enrollments.count(),
        "option_slots": range(MAX_OPTIONS),
    })


@login_required
@require_POST
def add_question(request, exam_id):
    exam = get_object_or_404(Exam, pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    if exam.published:
        messages.error(request, "Examen déjà publié : les questions ne peuvent plus être modifiées.")
        return redirect("teacher_exam", exam_id=exam.id)

    text = request.POST.get("text", "").strip()
    kind = request.POST.get("kind", Question.SINGLE)
    try:
        points = Decimal(request.POST.get("points", "1"))
    except InvalidOperation:
        points = None
    options = [(i, t.strip()) for i, t in enumerate(request.POST.getlist("option_text")[:MAX_OPTIONS]) if t.strip()]
    correct = set(request.POST.getlist("correct"))
    correct_count = sum(1 for i, _ in options if str(i) in correct)

    error = None
    if not text:
        error = "L'énoncé de la question est obligatoire."
    elif kind not in dict(Question.TYPE_CHOICES):
        error = "Type de question invalide."
    elif points is None or not (Decimal("0.1") <= points <= Decimal("100")):
        error = "Le barème doit être un nombre entre 0,1 et 100."
    elif len(options) < 2:
        error = "Saisissez au moins deux propositions."
    elif correct_count == 0:
        error = "Sélectionnez au moins une bonne réponse."
    elif kind == Question.SINGLE and correct_count > 1:
        # Une question à réponse unique s'affiche avec des boutons radio : avec deux
        # bonnes réponses, l'étudiant ne pourrait jamais obtenir les points.
        error = "Une question à réponse unique doit avoir exactement une bonne réponse. Choisissez « Réponses multiples »."
    if error:
        messages.error(request, error)
        return redirect("teacher_exam", exam_id=exam.id)

    with transaction.atomic():
        q = Question.objects.create(exam=exam, text=text, question_type=kind, duration_seconds=0,
                                    points=points, position=exam.questions.count() + 1)
        for position, (index, option_text) in enumerate(options, 1):
            Option.objects.create(question=q, text=option_text[:500], is_correct=str(index) in correct, position=position)
    messages.success(request, "Question ajoutée.")
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
        added = 0
        unknown = []
        with transaction.atomic():
            if exam.audience_mode != "LIST":
                # Passage en mode liste : seuls les étudiants du fichier restent autorisés.
                exam.enrollments.all().delete()
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
        messages.success(request, f"Import terminé : {added} étudiant(s) ajouté(s).")
        if unknown:
            messages.warning(request, "Matricules non reconnus : " + ", ".join(unknown[:20]))
    except (UnicodeDecodeError, ValueError, csv.Error) as exc:
        messages.error(request, str(exc))
    return redirect("teacher_exam", exam_id=exam.id)
