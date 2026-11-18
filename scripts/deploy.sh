#!/bin/bash
# Atualiza o robô na VPS com a última versão do GitHub.
#   bash scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only
docker compose up -d --build
docker image prune -f >/dev/null
docker compose ps
