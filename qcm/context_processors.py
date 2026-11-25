from .permissions import role


def app_role(request):
    """Expose le rôle applicatif aux templates (navigation adaptée au rôle)."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"app_role": None}
    return {"app_role": role(user), "is_superadmin": user.is_superuser}
