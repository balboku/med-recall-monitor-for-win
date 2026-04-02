#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
VENV_DIR="$BACKEND_DIR/.venv"

if command -v python3.13 >/dev/null 2>&1; then
  PYTHON_BOOTSTRAP="python3.13"
elif command -v python3.12 >/dev/null 2>&1; then
  PYTHON_BOOTSTRAP="python3.12"
elif command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BOOTSTRAP="python3.11"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BOOTSTRAP="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BOOTSTRAP="python"
else
  echo "[ERROR] Python was not found. Install Python 3.10+ first."
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "[ERROR] npm was not found. Install Node.js 20+ first."
  exit 1
fi

echo "--------------------------------------------------------"
echo "Starting Med Recall Monitor in local mode..."
echo "--------------------------------------------------------"

if [ -x "$VENV_DIR/bin/python" ]; then
  if ! "$VENV_DIR/bin/python" -c "import sys, sysconfig; soabi = sysconfig.get_config_var('SOABI') or ''; raise SystemExit(0 if sys.version_info[:2] <= (3, 13) and 't' not in soabi else 1)" >/dev/null 2>&1; then
    echo "[INFO] Existing backend virtual environment uses an incompatible Python build."
    echo "[INFO] Recreating $VENV_DIR with $PYTHON_BOOTSTRAP ..."
    rm -rf "$VENV_DIR"
  fi
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "[1/4] Creating backend virtual environment..."
  "$PYTHON_BOOTSTRAP" -m venv "$VENV_DIR"
fi

PYTHON_BIN="$VENV_DIR/bin/python"

echo "[2/4] Installing backend dependencies..."
"$PYTHON_BIN" -m pip install -r "$BACKEND_DIR/requirements-local.txt"

if [ ! -f "$BACKEND_DIR/.env" ]; then
  echo "[INFO] backend/.env was not found. Copy backend/.env.example if you need AI keys."
fi

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  echo "[3/4] Installing frontend dependencies..."
  (
    cd "$FRONTEND_DIR"
    npm install
  )
else
  echo "[3/4] Frontend dependencies already present."
fi

echo "[4/4] Launching backend and frontend..."
(
  cd "$BACKEND_DIR"
  TASK_QUEUE_MODE=local PYTHONPATH="$BACKEND_DIR" PYTHONUTF8=1 PYTHONIOENCODING=utf-8 "$PYTHON_BIN" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
) &
BACKEND_PID=$!

cleanup() {
  kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "Frontend: http://localhost:5173"
echo "Backend : http://localhost:8000"
echo "Swagger : http://localhost:8000/docs"
echo "Docker mode is still available via restart_system_docker.command"
echo "--------------------------------------------------------"

cd "$FRONTEND_DIR"
VITE_API_PROXY_TARGET=http://localhost:8000 npm run dev -- --host 0.0.0.0
