"""Adresse IP du client pour django-axes (relecture de la PR #19).

Sans proxy, l'IP du client est `REMOTE_ADDR`. Derrière Caddy (HTTPS, `docker-compose.https.yml`),
toutes les requêtes arrivent avec l'IP de Caddy : le blocage « identifiant + IP » se réduirait alors à
« identifiant » et n'importe qui pourrait bloquer le compte d'un camarade. Caddy transmet la vraie IP
dans `X-Forwarded-For` ; on lit la DERNIÈRE valeur, c'est-à-dire celle ajoutée par Caddy lui-même
(les précédentes peuvent venir du navigateur et être falsifiées).

À n'activer (`AXES_BEHIND_PROXY=1`) QUE si l'application n'est joignable qu'à travers le proxy :
sinon un client pourrait envoyer lui-même un faux `X-Forwarded-For`.
"""


def client_ip_behind_proxy(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    hops = [ip.strip() for ip in forwarded.split(",") if ip.strip()]
    if hops:
        return hops[-1]
    return request.META.get("REMOTE_ADDR")
