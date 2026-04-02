#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  DOCKER_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DOCKER_CMD=(docker-compose)
else
  echo "[ERROR] Docker Compose was not found."
  exit 1
fi

echo "--------------------------------------------------------"
echo "Starting Med Recall Monitor with Docker..."
echo "--------------------------------------------------------"

"${DOCKER_CMD[@]}" down
"${DOCKER_CMD[@]}" up -d --build
"${DOCKER_CMD[@]}" ps

echo "Frontend: http://localhost:5173"
echo "Backend : http://localhost:8000"
echo "Swagger : http://localhost:8000/docs"
echo "Prometheus: http://localhost:9090"
echo "--------------------------------------------------------"
