from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.views.decorators.http import require_POST

from ..models import Exam, ExamEnrollment, Attempt, ClassroomMembership
from ..permissions import role, is_classroom_student
from ..services import visible_exams_for_student
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


@login_required
def student_dashboard(request):
    if role(request.user) != "STUDENT":
        return HttpResponseForbidden("Accès réservé aux étudiants.")
    memberships = (ClassroomMembership.objects
                   .filter(user=request.user, role=ClassroomMembership.STUDENT, classroom__is_archived=False)
                   .select_related("classroom", "classroom__owner"))
    exams = annotate_exams_for_student(request.user, visible_exams_for_student(request.user))
    todo = [e for e in exams if not e.student_attempt or e.student_attempt.status == Attempt.IN_PROGRESS]
    done = [e for e in exams if e.student_attempt and e.student_attempt.status != Attempt.IN_PROGRESS]
    return render(request, "qcm/student_dashboard.html", {
        "classrooms": [m.classroom for m in memberships],
        "todo_exams": todo,
        "done_exams": done,
    })


@login_required
@require_POST
def join_exam_by_code(request):
    if role(request.user) != "STUDENT":
        return HttpResponseForbidden()
    code = request.POST.get("access_code", "").strip().upper()
    exam_id = request.POST.get("exam_id", "").strip()
    back = redirect_back(request, "student_dashboard")
    exam = (Exam.objects.filter(access_code=code, published=True, is_archived=False, pk=exam_id).first()
            if exam_id.isdigit() else None)
    if not exam:
        messages.error(request, "Code d'examen invalide ou examen non disponible.")
        return back
    profile = request.user.profile
    if exam.audience_mode == "LEVEL":
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
        if exam.audience_mode == "LEVEL":
            enrollment.source = "CODE"
        enrollment.save(update_fields=["code_verified", "source"])
    messages.success(request, f"Code validé. Vous pouvez accéder à : {exam.title}.")
    return back
