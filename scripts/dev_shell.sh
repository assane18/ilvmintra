#!/bin/bash
# Bascule sur la base de développement (intranet_dev) pour toute manipulation
# manuelle — flask shell, scripts ponctuels, tests exploratoires — sans jamais
# risquer de toucher la vraie base de production (intranet_db).
#
# intranet_dev a la même structure que la prod (schéma cloné, migrations à
# jour) mais est VIDE : aucune donnée réelle n'y transite. À peupler soi-même
# si besoin (comptes de test, `python seed_pilot_forms.py`, etc.).
#
# Usage :
#   ./scripts/dev_shell.sh                  -> ouvre un flask shell sur intranet_dev
#   ./scripts/dev_shell.sh flask db upgrade -> applique les migrations sur intranet_dev
#   ./scripts/dev_shell.sh python mon_script.py
#
# Le .env de prod n'est JAMAIS modifié par ce script — DATABASE_URL n'est
# écrasée que pour la durée de la commande lancée ici.

set -euo pipefail

PROJECT_DIR="/var/www/intranet"
cd "$PROJECT_DIR"

set -a
source .env
set +a

export DATABASE_URL="${DATABASE_URL%/*}/intranet_dev"

echo "[dev_shell] Connecté à : ${DATABASE_URL##*/} (base de développement, pas la prod)"

if [ $# -eq 0 ]; then
    exec venv/bin/flask shell
else
    exec "$@"
fi
