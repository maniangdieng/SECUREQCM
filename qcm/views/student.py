from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render, redirect
from django.views.decorators.http import require_POST

from ..models import Exam, ExamEnrollment, Attempt, ClassroomMembership
from ..permissions import role, is_classroom_student
from ..services import close_expired_attempts, visible_exams_for_student
from .common import redirect_back


def annotate_exams_for_student(user, exams):
    """Ajoute à chaque examen l'affectation et la dernière tentative de l'étudiant."""
    exams = list(exams)
    enrollment_map = {e.exam_id: e for e in ExamEnrollment.objects.filter(student=user, exam__in=exams)}
    attempt_map = {}
    for attempt in Attempt.objects.filter(student=user, exam__in=exams).order_by("started_at"):
        attempt_map[attempt.exam_id] = attempt  # la plus récente écrase les précédentes
    for exam in exams:
        exam.student_enrollment = enrollment_map.get(exam.id)
        exam.student_attempt = attempt_map.get(exam.id)
    return exams


def _split_todo(exams):
    todo = [e for e in exams if not e.student_attempt or e.student_attempt.status == Attempt.IN_PROGRESS]
    done = [e for e in exams if e.student_attempt and e.student_attempt.status != Attempt.IN_PROGRESS]
    return todo, done


@login_required
def student_dashboard(request):
    """Accueil étudiant : les cartes de ses classes, avec les examens à faire de chacune."""
    if role(request.user) != "STUDENT":
        return HttpResponseForbidden("Accès réservé aux étudiants.")
    close_expired_attempts(Attempt.objects.filter(student=request.user))
    classrooms = [m.classroom for m in (ClassroomMembership.objects
                  .filter(user=request.user, role=ClassroomMembership.STUDENT, classroom__is_archived=False)
                  .select_related("classroom", "classroom__owner"))]
    todo, done = _split_todo(annotate_exams_for_student(request.user, visible_exams_for_student(request.user)))
    for c in classrooms:
        c.upcoming = [e for e in todo if e.classroom_id == c.id]
    return render(request, "qcm/student_dashboard.html", {
        "classrooms": classrooms,
        "other_todo": [e for e in todo if e.classroom_id is None],
        "todo_exams": todo, "done_exams": done,
    })


@login_required
def student_todo(request):
    """Page « À faire » : tous les examens de l'étudiant, attribués ou terminés."""
    if role(request.user) != "STUDENT":
        return redirect("teacher_todo")
    close_expired_attempts(Attempt.objects.filter(student=request.user))
    todo, done = _split_todo(annotate_exams_for_student(request.user, visible_exams_for_student(request.user)))
    tab = "termines" if request.GET.get("tab") == "termines" else "attribues"
    return render(request, "qcm/student_todo.html", {
        "tab": tab, "todo": todo, "done": done, "exams": done if tab == "termines" else todo,
    })


@login_required
def student_exam(request, exam_id):
    """Page d'un examen côté étudiant : consignes à gauche, carte « Vos travaux » à droite."""
    if role(request.user) != "STUDENT":
        return redirect("teacher_exam", exam_id=exam_id)
    close_expired_attempts(Attempt.objects.filter(student=request.user, exam_id=exam_id))
    exam = get_object_or_404(visible_exams_for_student(request.user).select_related("teacher"), pk=exam_id)
    exam = annotate_exams_for_student(request.user, [exam])[0]
    return render(request, "qcm/student_exam.html", {
        "exam": exam, "question_count": exam.questions.count(),
    })


@login_required
@require_POST
def join_exam_by_code(request):
    if role(request.user) != "STUDENT":
        return HttpResponseForbidden()
    code = request.POST.get("access_code", "").strip().upper()
    exam_id = request.POST.get("exam_id", "").strip()
    back = redirect_back(request, "student_dashboard")
    exam = (Exam.objects.filter(access_code=code, published=True, is_archived=False,
                                closed_at__isnull=True, pk=exam_id).first()
            if exam_id.isdigit() else None)
    if not exam:
        messages.error(request, "Code d'examen invalide ou examen non disponible.")
        return back
    profile = request.user.profile
    individual = ExamEnrollment.objects.filter(exam=exam, student=request.user, source="LIST").first()
    if individual:
        enrollment = individual
    elif exam.audience_mode == "LEVEL":
        if not exam.target_level or not profile.study_level or profile.study_level != exam.target_level:
            messages.error(request, "Cet examen n'est pas destiné à votre niveau d'études.")
            return back
        enrollment, _ = ExamEnrollment.objects.get_or_create(exam=exam, student=request.user, defaults={"source": "LEVEL"})
    elif exam.audience_mode == "CLASS":
        if not is_classroom_student(request.user, exam.classroom):
            messages.error(request, "Rejoignez d'abord la classe de cet examen.")
            return back
        enrollment, _ = ExamEnrollment.objects.get_or_create(exam=exam, student=request.user, defaults={"source": "CLASS"})
    else:
        enrollment = ExamEnrollment.objects.filter(exam=exam, student=request.user).first()
        if not enrollment:
            messages.error(request, "Vous ne figurez pas sur la liste des étudiants autorisés pour cet examen.")
            return back
    if not enrollment.code_verified:
        enrollment.code_verified = True
        if exam.audience_mode == "LEVEL" and not individual:
            enrollment.source = "CODE"
        enrollment.save(update_fields=["code_verified", "source"])
    messages.success(request, f"Code validé. Vous pouvez accéder à : {exam.title}.")
    return back
