"""Connexion et inscription avec Google (#47). Toutes ces pages répondent 404 sans les clés Google."""
from functools import wraps

from allauth.account.models import EmailAddress
from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.internal.flows.signup import (clear_pending_signup, complete_social_signup,
                                                         get_pending_signup)
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.google.views import oauth2_callback
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from ..forms import GoogleSignupForm, StudentCompletionForm
from ..google import google_account, needs_completion, recent_google_sign_in
from ..models import Profile
from ..permissions import is_admin
from ..services import audit, enroll_student_in_level_exams
from .auth import STUDENT_WELCOME, set_up_new_account


def google_enabled(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not settings.GOOGLE_LOGIN_ENABLED:
            raise Http404
        return view(request, *args, **kwargs)
    return wrapper


def _go_to_google(request, process, next_url=None):
    provider = get_adapter().get_provider(request, "google")
    return provider.redirect(request, process, next_url=next_url)


@google_enabled
@require_POST
def google_login(request):
    # Le sens du parcours et la page de retour sont fixés ici, jamais lus dans la requête.
    return _go_to_google(request, "login", reverse("profile") if request.user.is_authenticated else None)


@google_enabled
def google_callback(request):
    return oauth2_callback(request)


def _free_username(first_name, last_name):
    """« awa.ndiaye », puis « awa.ndiaye2 » si l'identifiant est pris."""
    base = ".".join(part for part in (slugify(first_name), slugify(last_name)) if part)[:140] or "compte"
    username, number = base, 1
    while User.objects.filter(username__iexact=username).exists():
        number += 1
        username = f"{base}{number}"
    return username


@google_enabled
def google_signup(request):
    """« Compléter mon profil » : rien n'est créé avant la validation de ce formulaire."""
    if request.user.is_authenticated:
        return redirect("home")
    sociallogin = get_pending_signup(request)
    if sociallogin is None:
        return redirect("login")
    if request.method == "POST" and "cancel" in request.POST:
        clear_pending_signup(request)
        return redirect("login")
    email = sociallogin.user.email
    if not email:
        clear_pending_signup(request)
        messages.error(request, "Google n'a pas transmis d'adresse e-mail : le compte ne peut pas être créé.")
        return redirect("login")
    form = GoogleSignupForm(request.POST or None, initial={
        "account_type": "STUDENT", "first_name": sociallogin.user.first_name[:150],
        "last_name": sociallogin.user.last_name[:150]})
    if request.method == "POST" and form.is_valid():
        response = _create_account(request, sociallogin, form.cleaned_data)
        if response:
            return response
        clear_pending_signup(request)
        messages.info(request, "Votre compte existe déjà peut-être : reconnectez-vous avec Google.")
        return redirect("login")
    return render(request, "registration/google_signup.html", {
        "form": form, "email": email, "levels": Profile.LEVEL_CHOICES,
        "email_in_use": User.objects.filter(email__iexact=email).exists()})


def _create_account(request, sociallogin, data):
    """Crée le compte et connecte la personne ; None si ce compte Google est déjà inscrit."""
    if SocialAccount.objects.filter(provider=sociallogin.account.provider, uid=sociallogin.account.uid).exists():
        return None
    is_teacher = data["account_type"] == "TEACHER"
    user = sociallogin.user
    user.first_name, user.last_name = data["first_name"], data["last_name"]
    user.username = _free_username(user.first_name, user.last_name)
    user.set_unusable_password()
    try:
        with transaction.atomic():
            sociallogin.save(request)
            # L'adresse est déjà sur le compte : pas de seconde copie dans les tables de la bibliothèque.
            EmailAddress.objects.filter(user=user).delete()
            set_up_new_account(user, is_teacher, data["student_number"], data["study_level"])
    except IntegrityError:  # double envoi simultané
        return None
    clear_pending_signup(request)
    if not is_teacher:
        messages.success(request, STUDENT_WELCOME)
    return complete_social_signup(request, sociallogin)


@google_enabled
@login_required
def google_complete(request):
    if not needs_completion(request):
        return redirect("home")
    profile = request.user.profile
    form = StudentCompletionForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        profile.student_number = form.cleaned_data["student_number"]
        profile.study_level = form.cleaned_data["study_level"]
        profile.save(update_fields=["student_number", "study_level"])
        enroll_student_in_level_exams(request.user)
        messages.success(request, "Votre profil est complet.")
        return redirect("home")
    return render(request, "registration/google_complete.html", {"form": form})


@google_enabled
@login_required
@require_POST
@sensitive_post_parameters("password")
def google_link(request):
    if is_admin(request.user):
        return HttpResponseForbidden()
    if google_account(request.user):
        messages.info(request, "Un compte Google est déjà lié à votre compte.")
    elif not request.user.check_password(request.POST.get("password", "")):
        messages.error(request, "Mot de passe actuel incorrect.")
    else:
        return _go_to_google(request, "connect", reverse("profile"))
    return redirect("profile")


@google_enabled
@login_required
@require_POST
def google_unlink(request):
    if is_admin(request.user):
        return HttpResponseForbidden()
    if not request.user.has_usable_password():
        messages.error(request, "Définissez d'abord un mot de passe : sans lui, vous ne pourriez plus vous "
                                "connecter.")
    elif account := google_account(request.user):
        account.delete()
        audit(request.user, "Compte Google dissocié", request.user)
        messages.success(request, "Votre compte Google n'est plus lié.")
    return redirect("profile")


@google_enabled
@login_required
@sensitive_post_parameters()
def password_set(request):
    """Premier mot de passe d'un compte créé avec Google."""
    if request.user.has_usable_password():
        return redirect("password_change")
    # Une session restée ouverte ne suffit pas : il faut revenir de Google à l'instant.
    if not recent_google_sign_in(request):
        messages.error(request, "Confirmez d'abord votre identité avec Google.")
        return redirect("profile")
    form = SetPasswordForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        audit(user, "Mot de passe défini", user)
        messages.success(request, "Votre mot de passe est enregistré.")
        return redirect("profile")
    return render(request, "registration/password_change_form.html",
                  {"form": form, "heading": "Définir un mot de passe"})
