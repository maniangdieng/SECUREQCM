# Mettre l'application en HTTPS

Un examen ne doit pas passer en HTTP : les mots de passe et les réponses circuleraient en clair.
Le fichier `docker-compose.https.yml` ajoute [Caddy](https://caddyserver.com/docs/) devant l'application.
Caddy reçoit les connexions HTTPS et les transmet à Django ; le port 8000 n'est plus publié.

## 1. Choisir l'adresse

`SITE_ADDRESS` contient **une seule adresse**, celle que les utilisateurs taperont.

| Situation | `SITE_ADDRESS` | Certificat |
|---|---|---|
| Nom de domaine public (ex. `qcm.exemple.sn`) | le nom de domaine | public, obtenu et renouvelé par Caddy. Le domaine doit pointer vers le serveur et les ports 80 et 443 doivent être ouverts depuis Internet. |
| Réseau local, par adresse IP (ex. `192.168.1.12`) | l'adresse IP | émis par l'autorité interne de Caddy : à installer sur chaque poste (§4) |
| Réseau local, par nom en `.local` ou `.internal` | le nom | autorité interne (§4) |
| Essai sur la machine elle-même | `localhost` | autorité interne |

Pour un autre nom réservé au réseau interne (ni public, ni `.local`, ni `.internal`), ajouter la ligne `tls internal`
dans le bloc du site de [`deploy/Caddyfile`](../deploy/Caddyfile).

## 2. Configurer `.env`

Partir de `.env.example` (`cp .env.example .env`), puis renseigner :

```ini
DJANGO_SECRET_KEY=une-longue-valeur-aleatoire
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=qcm.exemple.sn
DJANGO_CSRF_TRUSTED_ORIGINS=https://qcm.exemple.sn
DJANGO_SECURE_COOKIES=1
POSTGRES_PASSWORD=un-mot-de-passe-robuste
COMPOSE_FILE=docker-compose.yml:docker-compose.https.yml
SITE_ADDRESS=qcm.exemple.sn
```

- `DJANGO_ALLOWED_HOSTS` : le même nom (ou la même adresse IP) que `SITE_ADDRESS`.
- `DJANGO_CSRF_TRUSTED_ORIGINS` : la même adresse précédée de `https://`. Sans elle, les formulaires sont refusés (erreur 403).
- `COMPOSE_FILE` : sous Windows, le séparateur est `;` et non `:`.
- Clé secrète : `python -c "import secrets; print(secrets.token_urlsafe(50))"`.
- `POSTGRES_PASSWORD` se choisit **avant** le premier démarrage : le changer ensuite dans `.env` ne modifie pas la base existante.

## 3. Démarrer et vérifier

```bash
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py check --deploy
```

`check --deploy` signale deux avertissements, `security.W004` (HSTS) et `security.W008` (redirection HTTPS) :
Caddy s'en charge à la place de Django. Tout autre avertissement est à corriger.

Vérifications dans un navigateur :

1. `http://adresse` redirige vers `https://adresse`.
2. La page de connexion s'affiche sans alerte de certificat.
3. La connexion et un enregistrement (par exemple créer une classe) fonctionnent.
4. `http://adresse:8000` ne répond plus.

## 4. Réseau local : installer le certificat de l'autorité interne

Sans cette étape, chaque navigateur affiche une alerte. Récupérer le certificat racine sur le serveur :

```bash
docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-racine.crt
```

L'installer comme **autorité de certification de confiance** sur chaque poste (magasin de certificats de Windows,
Trousseau d'accès sur macOS, paramètres de certificats de Firefox, réglages d'Android ou d'iOS).
Ne distribuer que `root.crt`, jamais la clé privée.

Le volume `caddy_data` conserve cette autorité. `docker compose down -v` le supprime : un nouveau certificat est alors
créé et doit être réinstallé partout.

## 5. Après la mise en service

- `HTTPS_PORT` et `HTTP_PORT` changent les ports publiés (443 et 80 par défaut). La redirection depuis HTTP vise
  toujours le port 443 : garder les ports par défaut en production.
- HSTS est réglé sur une heure. Quand le certificat est définitif et que tout fonctionne, passer à `31536000`
  (un an) dans `deploy/Caddyfile`, puis `docker compose restart caddy`. Un navigateur qui a reçu cette consigne
  refusera le HTTP pendant toute la durée.
- `GUNICORN_CMD_ARGS="--workers 4"` dans `.env` règle le nombre de processus de l'application. Une option
  `--workers` écrite dans la commande de `docker-compose.yml` l'emporte sur cette variable.
- Planifier la clôture des tentatives expirées, chaque minute (cron du serveur, depuis le dossier du projet) :
  `* * * * * cd /chemin/du/projet && docker compose exec -T web python manage.py close_expired_attempts`

## Ce qui a été essayé

Sur une machine Linux, avec l'autorité interne de Caddy (voir [RAPPORT_VALIDATION.md](RAPPORT_VALIDATION.md)) :
parcours complet en HTTPS par `localhost` et par `127.0.0.1`, redirection HTTP, cookies sécurisés, refus d'une
origine étrangère, récupération du certificat racine. L'accès par une adresse IP du réseau et par un nom en `.local`
a été essayé avec Caddy seul.
**Non essayé** : certificat public sur un vrai nom de domaine, installation du certificat interne sur d'autres appareils.
