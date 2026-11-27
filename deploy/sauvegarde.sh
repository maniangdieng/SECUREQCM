#!/usr/bin/env bash
# Sauvegarde de la base PostgreSQL lancée par Docker Compose. Voir docs/SAUVEGARDE.md.
# Usage : deploy/sauvegarde.sh [dossier]   (par défaut : ~/sauvegardes-secureqcm)
set -euo pipefail
umask 077   # la sauvegarde contient des données personnelles : lisible par son seul auteur

dossier="${1:-$HOME/sauvegardes-secureqcm}"
mkdir -p "$dossier"
dossier=$(cd "$dossier" && pwd)
cd "$(dirname "$0")/.."

fichier="$dossier/secureqcm-$(date +%Y%m%d-%H%M%S).dump"
trap 'rm -f "$fichier.tmp"' EXIT   # pas de sauvegarde tronquée si pg_dump échoue
docker compose exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$fichier.tmp"
mv "$fichier.tmp" "$fichier"
echo "$fichier"
