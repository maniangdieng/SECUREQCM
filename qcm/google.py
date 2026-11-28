"""
Connexion avec Google (#47) : les règles de l'application autour de django-allauth.

La bibliothèque fait l'échange avec Google et retrouve le compte lié. Ce module décide qui a le droit
d'entrer par cette porte, ce qui est conservé et ce qui doit être complété ensuite.
"""
import logging
import time

from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.authentication import get_authentication_records
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.base import AuthError, AuthProcess
from allauth.socialaccount.signals import social_account_added
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.shortcuts import redirect
from django.urls import reverse

from .permissions import is_admin, role
from .services import audit

logger = logging.getLogger(__name__)

# Durée pendant laquelle une connexion Google permet de définir un premier mot de passe.
RECENT_SIGN_IN_SECONDS = 5 * 60


def google_account(user):
    return SocialAccount.objects.filter(user=user, provider="google").first()


def google_sign_ins(request):
    """Connexions Google enregistrées dans la session de la personne connectée."""
    return [record for record in get_authentication_records(request, request.user)
            if record.get("method") == "socialaccount"]


def recent_google_sign_in(request):
    return any(time.time() - record["at"] <= RECENT_SIGN_IN_SECONDS for record in google_sign_ins(request))


def needs_completion(request):
    """Étudiant connecté avec Google dont le matricule ou le niveau manque."""
    user = request.user
    if not (settings.GOOGLE_LOGIN_ENABLED and user.is_authenticated and google_sign_ins(request)):
        return False
    return role(user) == "STUDENT" and not (user.profile.student_number and user.profile.study_level)


class ProfileCompletionMiddleware:
    """Profil incomplet : seules répondent la page de complément, la déconnexion et la confidentialité."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        open_pages = (reverse("google_complete"), reverse("logout"), reverse("privacy"))
        if needs_completion(request) and request.path not in open_pages:
            return redirect("google_complete")
        return self.get_response(request)


class AccountAdapter(DefaultAccountAdapter):
    def is_safe_url(self, url):
        # La page de retour est choisie par l'application : un « next » reçu dans la requête est ignoré.
        return False

    def login(self, request, user):
        # Même backend que l'inscription par formulaire : django-axes ne sert qu'aux mots de passe.
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")


class GoogleAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        """Appelé au retour de Google, avant toute connexion ou liaison."""
        # Le jeton d'accès ne sert plus : sans cette ligne, il attendrait en session avec le formulaire.
        sociallogin.token = None
        current = request.user
        if sociallogin.state.get("process") == AuthProcess.CONNECT:
            if current.is_authenticated:
                if is_admin(current):
                    _refuse(request, "Les comptes d'administration ne peuvent pas être liés à Google.", "profile")
                linked = google_account(current)
                if linked and linked.uid != sociallogin.account.uid:
                    _refuse(request, "Un compte Google est déjà lié à votre compte.", "profile")
            return
        # Déjà connecté : le retour de Google ne sert qu'à confirmer son identité, jamais à changer de compte.
        if current.is_authenticated and not (sociallogin.is_existing and sociallogin.user == current):
            _refuse(request, "Ce compte Google n'est pas celui lié à votre compte.", "profile")
        if sociallogin.is_existing:
            if is_admin(sociallogin.user):
                _refuse(request, "Les comptes d'administration se connectent avec leur identifiant et leur "
                                 "mot de passe.", "login")
            if not sociallogin.user.is_active:
                _refuse(request, "Ce compte est désactivé. Contactez l'administration.", "login")

    def get_connect_redirect_url(self, request, socialaccount):
        return reverse("profile")

    def on_authentication_error(self, request, provider, error=None, exception=None, extra_context=None):
        if error == AuthError.CANCELLED:
            messages.info(request, "Connexion avec Google annulée.")
        else:
            # Le type de l'erreur suffit au diagnostic ; son texte peut contenir un jeton.
            logger.warning("Échec de la connexion avec Google : %s (%s)", error, type(exception).__name__)
            messages.error(request, "La connexion avec Google a échoué. Réessayez.")
        raise ImmediateHttpResponse(redirect("profile" if request.user.is_authenticated else "home"))


def _refuse(request, text, target):
    messages.error(request, text)
    raise ImmediateHttpResponse(redirect(target))


@receiver(pre_save, sender=SocialAccount)
def keep_only_email(sender, instance, **kwargs):
    """De tout ce que Google renvoie, seule l'adresse e-mail est conservée avec le compte lié."""
    email = (instance.extra_data or {}).get("email")
    instance.extra_data = {"email": email} if email else {}


@receiver(social_account_added)
def log_link(sender, request, sociallogin, **kwargs):
    audit(request.user, "Compte Google lié", request.user)
