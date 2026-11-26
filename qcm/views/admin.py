"""
Espace administrateur / super-administrateur.

Règles conservées de la version d'origine pour le cycle de vie d'un examen :
- examen SANS tentative → suppression normale ;
- examen AVEC tentatives → archivage obligatoire (historique conservé) ;
- suppression définitive d'un examen archivé → export CSV confirmé + saisie « SUPPRIMER ».

Ajouts : gestion des rôles des comptes et vue d'ensemble des classes.
Seul le super-administrateur (is_superuser) peut nommer ou révoquer un administrateur.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import Profile, Exam, Attempt, Classroom
from ..permissions import role, is_admin, is_superadmin
from .common import redirect_back


@login_required
def admin_dashboard(request):
    if not is_admin(request.user):
        return HttpResponseForbidden("Accès réservé à l'administration.")
    return render(request, "qcm/admin_dashboard.html", {
        "stats": {
            "users": User.objects.count(),
            "teachers": Profile.objects.filter(role="TEACHER").count(),
            "students": Profile.objects.filter(role="STUDENT").count(),
            "classrooms": Classroom.objects.filter(is_archived=False).count(),
            "exams": Exam.objects.filter(is_archived=False).count(),
            "attempts": Attempt.objects.count(),
        },
        "managed_exams": (Exam.objects.select_related("teacher", "classroom")
                          .annotate(attempts_count=Count("attempts"))
                          .order_by("is_archived", "-created_at")),
        "classrooms": (Classroom.objects.select_related("owner")
                       .annotate(student_count=Count("memberships", filter=Q(memberships__role="STUDENT")),
                                 exam_count=Count("exams", distinct=True))),
    })


@login_required
def admin_users(request):
    if not is_admin(request.user):
        return HttpResponseForbidden("Accès réservé à l'administration.")
    query = request.GET.get("q", "").strip()
    role_filter = request.GET.get("role", "")
    users = User.objects.select_related("profile").order_by("-is_superuser", "last_name", "username")
    if query:
        users = users.filter(Q(username__icontains=query) | Q(first_name__icontains=query) | Q(last_name__icontains=query)
                             | Q(email__icontains=query) | Q(profile__student_number__icontains=query))
    if role_filter in ("ADMIN", "TEACHER", "STUDENT"):
        users = users.filter(profile__role=role_filter)
    page = Paginator(users, 30).get_page(request.GET.get("page"))
    return render(request, "qcm/admin_users.html", {
        "page": page, "query": query, "role_filter": role_filter,
        "roles": Profile.ROLE_CHOICES, "levels": Profile.LEVEL_CHOICES,
    })


@login_required
@require_POST
def admin_set_role(request, user_id):
    if not is_admin(request.user):
        return HttpResponseForbidden()
    target = get_object_or_404(User.objects.select_related("profile"), pk=user_id)
    new_role = request.POST.get("role", "")
    if new_role not in dict(Profile.ROLE_CHOICES):
        messages.error(request, "Rôle invalide.")
    elif target.pk == request.user.pk:
        messages.error(request, "Vous ne pouvez pas modifier votre propre rôle.")
    elif target.is_superuser:
        messages.error(request, "Le rôle d'un super-administrateur ne se modifie pas depuis l'application.")
    elif (new_role == "ADMIN" or role(target) == "ADMIN") and not is_superadmin(request.user):
        messages.error(request, "Seul le super-administrateur peut nommer ou révoquer un administrateur.")
    else:
        profile = target.profile
        profile.role = new_role
        profile.save(update_fields=["role"])
        if new_role != "ADMIN" and target.is_staff:
            target.is_staff = False
            target.save(update_fields=["is_staff"])
        messages.success(request, f"{target.username} est maintenant : {profile.get_role_display()}.")
    return redirect_back(request, "admin_users")


@login_required
@require_POST
def admin_toggle_active(request, user_id):
    if not is_admin(request.user):
        return HttpResponseForbidden()
    target = get_object_or_404(User, pk=user_id)
    if target.pk == request.user.pk or target.is_superuser:
        messages.error(request, "Ce compte ne peut pas être désactivé depuis l'application.")
    elif role(target) == "ADMIN" and not is_superadmin(request.user):
        messages.error(request, "Seul le super-administrateur peut désactiver un administrateur.")
    else:
        target.is_active = not target.is_active
        target.save(update_fields=["is_active"])
        messages.success(request, f"Compte {target.username} {'réactivé' if target.is_active else 'désactivé'}.")
    return redirect_back(request, "admin_users")


@login_required
@require_POST
def admin_delete_exam(request, exam_id):
    if not is_admin(request.user):
        return HttpResponseForbidden("Suppression définitive réservée à l'administration.")
    exam = get_object_or_404(Exam, pk=exam_id)
    confirmation = request.POST.get("confirmation", "").strip()
    export_confirmed = request.POST.get("export_confirmed") == "yes"
    if confirmation != "SUPPRIMER" or not export_confirmed:
        messages.error(request, "Confirmation invalide. Exportez d’abord les résultats, cochez la confirmation et saisissez SUPPRIMER.")
        return redirect("admin_dashboard")
    if Attempt.objects.filter(exam=exam).exists() and not exam.is_archived:
        messages.error(request, "Archivez d’abord cet examen avant sa suppression définitive.")
        return redirect("admin_dashboard")
    title = exam.title
    with transaction.atomic():
        # Attempt.exam est en PROTECT : suppression explicite de l’historique uniquement après confirmation admin.
        Attempt.objects.filter(exam=exam).delete()
        exam.delete()
    messages.success(request, f"L’examen « {title} » et toutes ses données associées ont été définitivement supprimés.")
    return redirect("admin_dashboard")


@login_required
@require_POST
def admin_normal_delete_exam(request, exam_id):
    if not is_admin(request.user):
        return HttpResponseForbidden("Action réservée à l'administration.")
    exam = get_object_or_404(Exam, pk=exam_id)
    if Attempt.objects.filter(exam=exam).exists():
        messages.error(request, "Cet examen possède des tentatives : archivez-le au lieu de le supprimer normalement.")
        return redirect("admin_dashboard")
    title = exam.title
    exam.delete()
    messages.success(request, f"L’examen « {title} » a été supprimé.")
    return redirect("admin_dashboard")
