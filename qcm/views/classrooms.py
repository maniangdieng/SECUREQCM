"""
Organisation en classes, inspirée de Google Classroom :
- un enseignant crée une classe → il en est propriétaire ;
- il peut ajouter des co-enseignants ;
- les étudiants rejoignent la classe avec son code (ou sont ajoutés par matricule) ;
- les examens d'une classe peuvent cibler toute la classe (mode CLASS).
"""
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from ..models import Attempt, Classroom, ClassroomMembership, Profile, Exam, generate_class_code
from ..permissions import (role, is_admin, is_teacher_or_admin, can_manage_classroom,
                           is_classroom_student)
from ..services import (enroll_student_in_class_exams, final_grades, unenroll_student_from_class_exams,
                        visible_exams_for_student)
from .common import redirect_back
from .student import annotate_exams_for_student
from .teacher import manageable_classrooms


def _classroom_fields(request):
    data = {
        "name": request.POST.get("name", "").strip()[:120],
        "section": request.POST.get("section", "").strip()[:120],
        "subject": request.POST.get("subject", "").strip()[:120],
        "description": request.POST.get("description", "").strip(),
        "study_level": request.POST.get("study_level", "").strip(),
        "color": request.POST.get("color", "teal").strip(),
    }
    if data["study_level"] not in dict(Profile.LEVEL_CHOICES):
        data["study_level"] = ""
    if data["color"] not in dict(Classroom.COLOR_CHOICES):
        data["color"] = "teal"
    return data


@login_required
@require_POST
def create_classroom(request):
    if not is_teacher_or_admin(request.user):
        return HttpResponseForbidden("Seuls les enseignants peuvent créer une classe.")
    data = _classroom_fields(request)
    if not data["name"]:
        messages.error(request, "Donnez un nom à la classe.")
        return redirect("teacher_dashboard")
    with transaction.atomic():
        classroom = Classroom.objects.create(owner=request.user, **data)
        ClassroomMembership.objects.create(classroom=classroom, user=request.user, role=ClassroomMembership.TEACHER)
    messages.success(request, f"Classe « {classroom} » créée. Code à communiquer aux étudiants : {classroom.join_code}")
    return redirect("classroom_detail", classroom_id=classroom.id)


TEACHER_TABS = ("flux", "travaux", "personnes", "notes", "parametres")
STUDENT_TABS = ("flux", "travaux", "personnes")


def _grade_book(classroom, students, exams):
    """Onglet « Notes » : une ligne par étudiant, une colonne par examen publié (dernière tentative)."""
    published = [e for e in exams if e.published]
    latest = {}
    for attempt in (Attempt.objects.filter(exam__in=published, student__in=[m.user_id for m in students])
                    .order_by("started_at")):
        latest[(attempt.student_id, attempt.exam_id)] = attempt  # la plus récente écrase
    grades = final_grades(a for a in latest.values() if a.status != Attempt.IN_PROGRESS)
    rows, column_values = [], {e.id: [] for e in published}
    for m in students:
        cells, values = [], []
        for e in published:
            attempt = latest.get((m.user_id, e.id))
            grade = grades.get(attempt.id) if attempt else None
            cells.append({"attempt": attempt, "grade": grade})
            if grade is not None:
                values.append(grade)
                column_values[e.id].append(grade)
        rows.append({"member": m, "cells": cells,
                     "average": (sum(values) / len(values)) if values else None})
    averages = [(sum(v) / len(v)) if v else None for v in column_values.values()]
    return {"exams": published, "rows": rows, "averages": averages}


@login_required
def classroom_detail(request, classroom_id):
    classroom = get_object_or_404(Classroom.objects.select_related("owner"), pk=classroom_id)
    teachers = (ClassroomMembership.objects.filter(classroom=classroom, role=ClassroomMembership.TEACHER)
                .select_related("user").order_by("joined_at"))
    students = list(ClassroomMembership.objects.filter(classroom=classroom, role=ClassroomMembership.STUDENT)
                    .select_related("user", "user__profile").order_by("user__last_name", "user__first_name"))
    tab = request.GET.get("tab", "flux")
    context = {"classroom": classroom, "teachers": teachers, "students": students}

    if can_manage_classroom(request.user, classroom):
        if tab not in TEACHER_TABS:
            tab = "flux"
        exams = list(Exam.objects.filter(classroom=classroom).select_related("teacher")
                     .annotate(question_count=Count("questions", distinct=True),
                               assigned_count=Count("enrollments", distinct=True),
                               turned_in_count=Count("attempts__student", distinct=True,
                                                     filter=~Q(attempts__status=Attempt.IN_PROGRESS)))
                     .order_by("is_archived", "-created_at"))
        context.update({
            "tab": tab, "exams": exams, "levels": Profile.LEVEL_CHOICES, "colors": Classroom.COLOR_CHOICES,
            "is_owner": classroom.owner_id == request.user.id or is_admin(request.user),
            "stream": [e for e in exams if e.published],
        })
        if tab == "notes":
            context["book"] = _grade_book(classroom, students, exams)
        return render(request, "qcm/classroom_teacher.html", context)

    if is_classroom_student(request.user, classroom):
        if tab not in STUDENT_TABS:
            tab = "flux"
        exams = annotate_exams_for_student(request.user, visible_exams_for_student(request.user, classroom=classroom))
        context.update({
            "tab": tab, "exams": exams, "stream": exams,
            "upcoming": [e for e in exams if not e.student_attempt or e.student_attempt.status == Attempt.IN_PROGRESS],
        })
        return render(request, "qcm/classroom_student.html", context)
    return HttpResponseForbidden("Vous n'êtes pas membre de cette classe.")


@login_required
def archived_classrooms(request):
    """Page « Classes archivées » du menu latéral."""
    if is_teacher_or_admin(request.user):
        classrooms = manageable_classrooms(request.user).filter(is_archived=True)
    else:
        classrooms = Classroom.objects.filter(memberships__user=request.user, is_archived=True)
    classrooms = classrooms.select_related("owner").annotate(
        student_count=Count("memberships", filter=Q(memberships__role=ClassroomMembership.STUDENT), distinct=True))
    return render(request, "qcm/archived_classrooms.html", {"classrooms": classrooms})


@login_required
@require_POST
def update_classroom(request, classroom_id):
    classroom = get_object_or_404(Classroom, pk=classroom_id)
    if not can_manage_classroom(request.user, classroom):
        return HttpResponseForbidden()
    data = _classroom_fields(request)
    if not data["name"]:
        messages.error(request, "Le nom de la classe est obligatoire.")
        return redirect("classroom_detail", classroom_id=classroom.id)
    for field, value in data.items():
        setattr(classroom, field, value)
    classroom.join_enabled = request.POST.get("join_enabled") == "on"
    classroom.save()
    messages.success(request, "Paramètres de la classe enregistrés.")
    return redirect(f"/classes/{classroom.id}/?tab=parametres")


@login_required
@require_POST
def regenerate_class_code(request, classroom_id):
    classroom = get_object_or_404(Classroom, pk=classroom_id)
    if not can_manage_classroom(request.user, classroom):
        return HttpResponseForbidden()
    classroom.join_code = generate_class_code()
    classroom.save(update_fields=["join_code"])
    messages.success(request, f"Nouveau code de classe : {classroom.join_code}. L'ancien code ne fonctionne plus.")
    return redirect_back(request, "classroom_detail", classroom_id=classroom.id)


@login_required
@require_POST
def archive_classroom(request, classroom_id):
    classroom = get_object_or_404(Classroom, pk=classroom_id)
    if not (is_admin(request.user) or classroom.owner_id == request.user.id):
        return HttpResponseForbidden("Seul le propriétaire de la classe ou un administrateur peut l'archiver.")
    classroom.is_archived = not classroom.is_archived
    classroom.save(update_fields=["is_archived"])
    messages.success(request, "Classe archivée." if classroom.is_archived else "Classe restaurée.")
    return redirect_back(request, "teacher_dashboard")


@login_required
@require_POST
def delete_classroom(request, classroom_id):
    classroom = get_object_or_404(Classroom, pk=classroom_id)
    if not (is_admin(request.user) or classroom.owner_id == request.user.id):
        return HttpResponseForbidden()
    if classroom.exams.exists():
        messages.error(request, "Suppression impossible : la classe contient des examens. Archivez-la plutôt.")
        return redirect_back(request, "classroom_detail", classroom_id=classroom.id)
    name = str(classroom)
    classroom.delete()
    messages.success(request, f"La classe « {name} » a été supprimée.")
    return redirect("admin_dashboard" if is_admin(request.user) else "teacher_dashboard")


@login_required
@require_POST
def add_coteacher(request, classroom_id):
    classroom = get_object_or_404(Classroom, pk=classroom_id)
    if not (is_admin(request.user) or classroom.owner_id == request.user.id):
        return HttpResponseForbidden("Seul le propriétaire de la classe peut inviter un co-enseignant.")
    ident = request.POST.get("identifier", "").strip()
    user = User.objects.filter(Q(username__iexact=ident) | Q(email__iexact=ident)).first() if ident else None
    if not user or role(user) not in ("TEACHER", "ADMIN"):
        messages.error(request, "Aucun compte enseignant ne correspond à cet identifiant ou e-mail.")
    else:
        membership, created = ClassroomMembership.objects.get_or_create(
            classroom=classroom, user=user, defaults={"role": ClassroomMembership.TEACHER})
        if not created and membership.role != ClassroomMembership.TEACHER:
            membership.role = ClassroomMembership.TEACHER
            membership.save(update_fields=["role"])
        messages.success(request, f"{user.get_full_name() or user.username} est maintenant co-enseignant.")
    return redirect(f"/classes/{classroom.id}/?tab=personnes")


@login_required
@require_POST
def add_students_to_classroom(request, classroom_id):
    """Ajoute des étudiants existants à partir d'une liste de matricules (un par ligne, ou séparés par , ;)."""
    classroom = get_object_or_404(Classroom, pk=classroom_id)
    if not can_manage_classroom(request.user, classroom):
        return HttpResponseForbidden()
    raw = request.POST.get("student_numbers", "")
    numbers = [n for n in re.split(r"[\s,;]+", raw) if n]
    added, unknown = 0, []
    for number in numbers:
        profile = Profile.objects.select_related("user").filter(student_number=number, role="STUDENT").first()
        if not profile:
            unknown.append(number)
            continue
        _, created = ClassroomMembership.objects.get_or_create(
            classroom=classroom, user=profile.user, defaults={"role": ClassroomMembership.STUDENT})
        if created:
            enroll_student_in_class_exams(profile.user, classroom)
            added += 1
    messages.success(request, f"{added} étudiant(s) ajouté(s) à la classe.")
    if unknown:
        messages.warning(request, "Matricules non reconnus (compte inexistant) : " + ", ".join(unknown[:20]))
    return redirect(f"/classes/{classroom.id}/?tab=personnes")


@login_required
@require_POST
def remove_classroom_member(request, classroom_id, membership_id):
    classroom = get_object_or_404(Classroom, pk=classroom_id)
    membership = get_object_or_404(ClassroomMembership, pk=membership_id, classroom=classroom)
    if membership.user_id == classroom.owner_id:
        messages.error(request, "Le propriétaire de la classe ne peut pas être retiré.")
        return redirect(f"/classes/{classroom.id}/?tab=personnes")
    if membership.role == ClassroomMembership.TEACHER:
        allowed = is_admin(request.user) or classroom.owner_id == request.user.id
    else:
        allowed = can_manage_classroom(request.user, classroom)
    if not allowed:
        return HttpResponseForbidden()
    if membership.role == ClassroomMembership.STUDENT:
        unenroll_student_from_class_exams(membership.user, classroom)
    membership.delete()
    messages.success(request, "Membre retiré de la classe.")
    return redirect(f"/classes/{classroom.id}/?tab=personnes")


@login_required
@require_POST
def join_classroom(request):
    if role(request.user) != "STUDENT":
        return HttpResponseForbidden("Seuls les étudiants rejoignent une classe par code.")
    code = request.POST.get("join_code", "").strip().upper()
    classroom = Classroom.objects.filter(join_code=code, is_archived=False).first() if code else None
    if not classroom or not classroom.join_enabled:
        messages.error(request, "Code de classe invalide ou inscriptions fermées.")
        return redirect("student_dashboard")
    _, created = ClassroomMembership.objects.get_or_create(
        classroom=classroom, user=request.user, defaults={"role": ClassroomMembership.STUDENT})
    if created:
        enroll_student_in_class_exams(request.user, classroom)
        messages.success(request, f"Vous avez rejoint la classe « {classroom} ».")
    else:
        messages.info(request, "Vous êtes déjà membre de cette classe.")
    return redirect("classroom_detail", classroom_id=classroom.id)


@login_required
@require_POST
def leave_classroom(request, classroom_id):
    classroom = get_object_or_404(Classroom, pk=classroom_id)
    membership = ClassroomMembership.objects.filter(
        classroom=classroom, user=request.user, role=ClassroomMembership.STUDENT).first()
    if membership:
        unenroll_student_from_class_exams(request.user, classroom)
        membership.delete()
        messages.success(request, f"Vous avez quitté la classe « {classroom} ».")
    return redirect("student_dashboard")
