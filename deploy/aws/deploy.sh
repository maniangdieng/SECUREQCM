#!/usr/bin/env bash
# Met en service la version déjà extraite dans /opt/secureqcm (appelé par .github/workflows/deploy.yml,
# après « git checkout <commit> »). Les migrations sont appliquées au démarrage du conteneur web.
set -euo pipefail
cd "$(dirname "$0")/../.."

echo "Version : $(git log -1 --format='%h %s')"
docker compose up -d --build --remove-orphans
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
