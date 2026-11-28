"""
Espace administrateur / super-administrateur.

Règles conservées de la version d'origine pour le cycle de vie d'un examen :
- examen SANS tentative → suppression normale ;
- examen AVEC tentatives → archivage obligatoire (historique conservé) ;
- suppression définitive d'un examen archivé → export CSV confirmé + saisie « SUPPRIMER ».

Ajouts : création et gestion des rôles des comptes, vue d'ensemble des classes, journal des opérations.
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
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_POST, require_safe

from ..forms import AccountForm
from ..models import Profile, Exam, Attempt, AuditLog, Classroom
from ..permissions import role, is_admin, is_superadmin
from ..services import audit, enroll_student_in_level_exams
from .common import redirect_back


@login_required
def admin_dashboard(request):
    if not is_admin(request.user):
        return HttpResponseForbidden("Accès réservé à l'administration.")
    return render(request, "qcm/admin_dashboard.html", {
        "stats": {
            "users": User.objects.count(),
            "teachers": Profile.objects.filter(role="TEACHER").count(),
            "pending": Profile.objects.filter(role="PENDING", user__is_active=True).count(),
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
    if role_filter in dict(Profile.ROLE_CHOICES):
        users = users.filter(profile__role=role_filter)
    page = Paginator(users, 30).get_page(request.GET.get("page"))
    return render(request, "qcm/admin_users.html", {
        "page": page, "query": query, "role_filter": role_filter,
        "roles": Profile.ROLE_CHOICES, "levels": Profile.LEVEL_CHOICES,
        "pending": (User.objects.filter(profile__role="PENDING", is_active=True).order_by("date_joined")),
    })


@login_required
@require_POST
@transaction.atomic
def admin_teacher_request(request, user_id):
    """Valide ou refuse une demande de compte enseignant faite à l'inscription."""
    if not is_admin(request.user):
        return HttpResponseForbidden()
    target = get_object_or_404(User.objects.select_related("profile"), pk=user_id, profile__role="PENDING")
    profile = target.profile
    if request.POST.get("decision") == "approve":
        profile.role = "TEACHER"
        profile.save(update_fields=["role"])
        audit(request.user, "Demande enseignant acceptée", target)
        messages.success(request, f"{target.get_full_name() or target.username} est maintenant enseignant.")
    else:
        # Refus : le compte est désactivé (il n'a ni matricule ni niveau pour servir de compte étudiant).
        profile.role = "STUDENT"
        profile.save(update_fields=["role"])
        target.is_active = False
        target.save(update_fields=["is_active"])
        audit(request.user, "Demande enseignant refusée", target, "compte désactivé")
        messages.success(request, f"Demande de {target.username} refusée : le compte est désactivé.")
    return redirect_back(request, "admin_users")


@login_required
@transaction.atomic
def admin_create_user(request):
    if not is_admin(request.user):
        return HttpResponseForbidden("Accès réservé à l'administration.")
    initial = {"role": "TEACHER"} if request.GET.get("role") == "TEACHER" else None
    form = AccountForm(request.POST or None, creator=request.user, initial=initial)
    if form.is_valid():
        user = form.save()
        if user.profile.role == "STUDENT":
            enroll_student_in_level_exams(user)
        audit(request.user, "Compte créé", user, user.profile.get_role_display())
        messages.success(request, f"Compte {user.username} créé. Transmettez le mot de passe à la personne concernée.")
        return redirect(f"{reverse('admin_users')}?{urlencode({'q': user.username})}")
    return render(request, "qcm/admin_user_form.html", {"form": form})


@login_required
@require_safe
def admin_journal(request):
    if not is_admin(request.user):
        return HttpResponseForbidden("Accès réservé à l'administration.")
    query = request.GET.get("q", "").strip()
    entries = AuditLog.objects.all()
    if query:
        entries = entries.filter(Q(actor_name__icontains=query) | Q(action__icontains=query)
                                 | Q(target__icontains=query) | Q(details__icontains=query))
    return render(request, "qcm/admin_journal.html", {
        "page": Paginator(entries, 50).get_page(request.GET.get("page")), "query": query,
    })


@login_required
@require_POST
@transaction.atomic
def admin_set_role(request, user_id):
    if not is_admin(request.user):
        return HttpResponseForbidden()
    target = get_object_or_404(User.objects.select_related("profile"), pk=user_id)
    new_role = request.POST.get("role", "")
    if new_role not in dict(Profile.ROLE_CHOICES) or new_role == "PENDING":
        messages.error(request, "Rôle invalide.")
    elif target.pk == request.user.pk:
        messages.error(request, "Vous ne pouvez pas modifier votre propre rôle.")
    elif target.is_superuser:
        messages.error(request, "Le rôle d'un super-administrateur ne se modifie pas depuis l'application.")
    elif (new_role == "ADMIN" or role(target) == "ADMIN") and not is_superadmin(request.user):
        messages.error(request, "Seul le super-administrateur peut nommer ou révoquer un administrateur.")
    else:
        profile = target.profile
        old_label = profile.get_role_display()
        changed = profile.role != new_role
        profile.role = new_role
        profile.save(update_fields=["role"])
        if new_role != "ADMIN" and target.is_staff:
            target.is_staff = False
            target.save(update_fields=["is_staff"])
        if changed:
            audit(request.user, "Rôle modifié", target, f"{old_label} → {profile.get_role_display()}")
        messages.success(request, f"{target.username} est maintenant : {profile.get_role_display()}.")
    return redirect_back(request, "admin_users")


@login_required
@require_POST
@transaction.atomic
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
        audit(request.user, "Compte réactivé" if target.is_active else "Compte désactivé", target)
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
        copies = Attempt.objects.filter(exam=exam)
        audit(request.user, "Examen supprimé définitivement", exam, f"{copies.count()} copie(s) effacée(s)")
        copies.delete()
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
    with transaction.atomic():
        audit(request.user, "Examen supprimé", exam)
        exam.delete()
    messages.success(request, f"L’examen « {title} » a été supprimé.")
    return redirect("admin_dashboard")
