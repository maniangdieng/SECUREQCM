"""Backend d'authentification django-axes (limitation des tentatives de connexion).

Toutes les connexions de l'application passent par des vues qui fournissent la
requête HTTP (page de connexion unifiée, /admin/) : elles sont donc protégées.
`authenticate()` appelé sans requête (cas de `self.client.login()` dans les tests)
ne peut pas être compté par axes : on laisse alors la main au backend Django
standard au lieu de lever une erreur.
"""
from axes.backends import AxesStandaloneBackend


class AxesBackend(AxesStandaloneBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if request is None:
            return None
        return super().authenticate(request, username=username, password=password, **kwargs)
