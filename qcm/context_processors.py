from django.conf import settings
from django.db.models import Q

from .models import Classroom, ClassroomMembership, Profile
from .permissions import role


def app_role(request):
    """
    Expose aux templates le rôle applicatif et les classes affichées dans le menu
    latéral (comme le tiroir de Google Classroom : « Enseignement » / « Inscrit »).
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"app_role": None, "google_login_enabled": settings.GOOGLE_LOGIN_ENABLED}
    current_role = role(user)
    context = {"app_role": current_role, "is_superadmin": user.is_superuser,
               "google_login_enabled": settings.GOOGLE_LOGIN_ENABLED}
    if current_role in ("TEACHER", "ADMIN"):
        context["nav_teaching"] = list(
            Classroom.objects.filter(Q(owner=user) | Q(memberships__user=user, memberships__role=ClassroomMembership.TEACHER),
                                     is_archived=False).distinct().only("id", "name", "section", "color"))
        # Choix du formulaire « Créer une classe », accessible depuis le bouton + de la barre du haut.
        context["class_levels"] = Profile.LEVEL_CHOICES
        context["class_colors"] = Classroom.COLOR_CHOICES
    else:
        context["nav_enrolled"] = list(
            Classroom.objects.filter(memberships__user=user, memberships__role=ClassroomMembership.STUDENT,
                                     is_archived=False).only("id", "name", "section", "color"))
    return context
