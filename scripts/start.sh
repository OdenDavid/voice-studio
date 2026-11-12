#!/bin/bash
# Local Voice Studio — start script.
# Usage: scripts/start.sh [dev]
#   dev  → run backend (uvicorn) + frontend (vite dev server) separately
set -euo pipefail

cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

if [ ! -d .venv ]; then
  echo "error: .venv missing. Run scripts/install.sh first."
  exit 1
fi

source .venv/bin/activate

mkdir -p logs data/voices data/generations data/meta

if [ "${1:-}" = "dev" ]; then
  echo "Starting backend on http://127.0.0.1:8200 ..."
  uvicorn app.backend.main:app --host 127.0.0.1 --port 8200 &
  BACKEND_PID=$!
  echo $BACKEND_PID > /tmp/voice_studio_backend.pid
  echo "Starting frontend dev server on http://localhost:5173 ..."
  (cd app/frontend && npm run dev) &
  echo $! > /tmp/voice_studio_frontend.pid
  echo "Frontend: http://localhost:5173   Backend: http://127.0.0.1:8200"
  wait
else
  # Production: serve the built frontend from FastAPI.
  if [ ! -d app/frontend/dist ]; then
    echo "Frontend not built yet — building now..."
    (cd app/frontend && npm install --no-audit --no-fund && npm run build)
  fi
  echo "Starting Local Voice Studio on http://127.0.0.1:8200 ..."
  nohup uvicorn app.backend.main:app --host 127.0.0.1 --port 8200 \
    > logs/voice-studio.log 2>&1 &
  echo $! > /tmp/voice_studio_backend.pid
  echo "Started (PID $(cat /tmp/voice_studio_backend.pid))."
  echo "Open http://127.0.0.1:8200 in your browser."
  echo "Logs: logs/voice-studio.log — Stop with scripts/stop.sh"
fi
