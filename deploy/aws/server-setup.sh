# Installation du serveur Secure QCM (Ubuntu 24.04). Exécuté une fois au premier démarrage par EC2
# (données utilisateur, en root), avec SITE_ADDRESS et REPO définis par deploy/aws/infra.sh.
# Voir docs/DEPLOIEMENT_AWS.md.
set -euxo pipefail
exec > >(tee -a /var/log/secureqcm-setup.log) 2>&1

APP=/opt/secureqcm
: "${SITE_ADDRESS:?}" "${REPO:?}"

export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q docker.io docker-compose-v2 git cron
systemctl enable --now docker

# Petite marge mémoire pour la construction de l'image.
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

[ -d "$APP/.git" ] || git clone "https://github.com/$REPO.git" "$APP"
cd "$APP"

# Configuration de production : les secrets sont générés ici et ne quittent pas le serveur.
if [ ! -f .env ]; then
  umask 077
  cat > .env <<EOF
DJANGO_SECRET_KEY=$(openssl rand -base64 48 | tr -d '\n/+=')
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=$SITE_ADDRESS
DJANGO_CSRF_TRUSTED_ORIGINS=https://$SITE_ADDRESS
DJANGO_SESSION_HOURS=8
DJANGO_SECURE_COOKIES=1
AXES_FAILURE_LIMIT=5
AXES_COOLOFF_MINUTES=15
POSTGRES_DB=secureqcm
POSTGRES_USER=secureqcm
POSTGRES_PASSWORD=$(openssl rand -hex 24)
POSTGRES_HOST=db
POSTGRES_PORT=5432
DJANGO_EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
COMPOSE_FILE=docker-compose.yml:docker-compose.https.yml
SITE_ADDRESS=$SITE_ADDRESS
GUNICORN_WORKERS=5
EOF
fi

docker compose up -d --build

# Clôture des tentatives expirées chaque minute ; sauvegarde de la base chaque nuit (14 jours gardés).
cat > /etc/cron.d/secureqcm <<EOF
* * * * * root cd $APP && docker compose exec -T web python manage.py close_expired_attempts -v 0 2>&1 | logger -t secureqcm-cloture
30 2 * * * root ($APP/deploy/sauvegarde.sh /var/backups/secureqcm && find /var/backups/secureqcm -name '*.dump' -mtime +14 -delete) 2>&1 | logger -t secureqcm-sauvegarde
EOF
chmod 644 /etc/cron.d/secureqcm
echo "Installation terminée : https://$SITE_ADDRESS"
