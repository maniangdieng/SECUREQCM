from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme


def redirect_back(request, fallback, *args, **kwargs):
    """Redirige vers le champ `next` du formulaire s'il est sûr, sinon vers `fallback`."""
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect(fallback, *args, **kwargs)


def class_tab(classroom_id, tab):
    """Redirection vers un onglet précis d'une classe (sans `?tab=`, la page ouvre le Flux)."""
    return redirect(f"{reverse('classroom_detail', args=[classroom_id])}?tab={tab}")
