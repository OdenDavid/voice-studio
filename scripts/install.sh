#!/bin/bash
# Local Voice Studio — one-time environment setup (user-local only).
# Creates the Python venv, installs backend deps, and builds the frontend.
set -euo pipefail

cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

echo "== Checking uv =="
if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv (user-local, ~/.local/bin)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
uv --version

echo "== Python 3.12 =="
uv python install 3.12 || true

echo "== Backend venv =="
if [ ! -d .venv ]; then
  uv venv --python 3.12 .venv
fi
uv pip install --python .venv/bin/python \
  fastapi "uvicorn[standard]" python-multipart pydantic \
  "onnxruntime==1.23.2" "sentencepiece<0.2.3" \
  soundfile scipy numpy \
  imageio-ffmpeg

echo "== Frontend =="
if [ ! -d node_modules ] && [ -d app/frontend ]; then
  (cd app/frontend && npm install --no-audit --no-fund)
fi
(cd app/frontend && npm run build)

echo ""
echo "Setup complete."
echo "Next: scripts/download_models.sh   (download weights)"
echo "Then: scripts/start.sh             (run the app)"
