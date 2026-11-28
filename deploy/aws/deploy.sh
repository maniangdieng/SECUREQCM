#!/usr/bin/env bash
# Met en service la version déjà extraite dans /opt/secureqcm (appelé par .github/workflows/deploy.yml,
# après « git checkout <commit> »). Ordre : image, sauvegarde, migrations à part, puis bascule du conteneur web.
set -euo pipefail
cd "$(dirname "$0")/../.."

echo "Version : $(git log -1 --format='%h %s')"

# 1. Construire la nouvelle image pendant que l'ancienne version sert toujours le site.
docker compose build web

# 2. Sauvegarder la base avant toute migration (gardée 14 jours avec celles de la nuit).
deploy/sauvegarde.sh /var/backups/secureqcm

# 3. Migrations dans un conteneur à part : si l'une échoue, on s'arrête ici et l'ancienne version reste en ligne.
#    (Sous PostgreSQL, une migration qui échoue est annulée.)
if ! docker compose run --rm --no-deps web python manage.py migrate --noinput; then
  echo "Migration en échec : l'ancienne version reste en service. Sauvegarde dans /var/backups/secureqcm." >&2
  exit 1
fi

# 4. Bascule : seul le conteneur web est recréé (quelques secondes). Caddy relit sa configuration sans coupure.
docker compose up -d --no-build --remove-orphans
docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile \
  || docker compose restart caddy
docker image prune -f >/dev/null

# Attendre que l'application réponde (migrations comprises), sinon échec visible dans GitHub Actions.
for _ in $(seq 1 60); do
  # Host autorisé (DJANGO_ALLOWED_HOSTS), sinon Django répond 400.
  if docker compose exec -T web python -c "
import os, urllib.request
host = os.environ['DJANGO_ALLOWED_HOSTS'].split(',')[0].strip()
urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/accounts/login/', headers={'Host': host}), timeout=5)
" 2>/dev/null; then
    docker compose ps
    echo "Déploiement réussi."
    exit 0
  fi
  sleep 5
done
# Pas de journaux de l'application ici : cette sortie est recopiée dans GitHub Actions, public pour ce dépôt,
# et les journaux peuvent contenir des données personnelles ou des liens de réinitialisation de mot de passe.
docker compose ps
echo "L'application ne répond pas après 5 minutes. Sur le serveur : docker compose logs --tail 100 web" >&2
exit 1
