#!/bin/bash
# Local Voice Studio — stop script.
set -uo pipefail

if [ -f /tmp/voice_studio_backend.pid ]; then
  kill "$(cat /tmp/voice_studio_backend.pid)" 2>/dev/null && echo "Backend stopped."
  rm -f /tmp/voice_studio_backend.pid
fi
if [ -f /tmp/voice_studio_frontend.pid ]; then
  kill "$(cat /tmp/voice_studio_frontend.pid)" 2>/dev/null && echo "Frontend stopped."
  rm -f /tmp/voice_studio_frontend.pid
fi
# Stop the Pocket TTS subprocess if still around.
pkill -f "pocket-tts-3.3.0-x86_64-apple-darwin/pocket-tts serve" 2>/dev/null && echo "Pocket TTS stopped." || true
echo "Done."
