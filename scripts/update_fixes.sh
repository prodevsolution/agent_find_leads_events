#!/bin/bash
set -e

# ============================================================
# update_fixes.sh — Run post-deployment fixes and maintenance
# ============================================================
# Usage: bash scripts/update_fixes.sh
#
# What it fixes:
#   1. Installs/updates Playwright browsers
#   2. Ensures Ollama model for structured output is pulled
#   3. Validates critical .env variables
#   4. Restarts the app on port 7860
# ============================================================

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=== [1/4] Installing Playwright browsers ==="
PLAYWRIGHT_SUCCESS=false
for i in 1 2 3; do
  if uv run playwright install --with-deps chromium 2>/dev/null; then
    PLAYWRIGHT_SUCCESS=true
    echo "   Playwright chromium installed."
    break
  fi
  echo "   Attempt $i failed, retrying in 10s..."
  sleep 10
done
if [ "$PLAYWRIGHT_SUCCESS" = false ]; then
  echo "   WARNING: Playwright install failed after 3 attempts."
fi

echo ""
echo "=== [2/4] Ensuring Ollama model is pulled ==="
OLLAMA_MODEL="${OLLAMA_MODEL:-$(grep -oP 'OLLAMA_MODEL=\K.*' .env 2>/dev/null || echo 'phi4-mini')}"
if command -v ollama &>/dev/null; then
  echo "   Pulling model: $OLLAMA_MODEL"
  ollama pull "$OLLAMA_MODEL" 2>&1 || echo "   WARNING: Could not pull $OLLAMA_MODEL"
else
  echo "   Ollama not installed. Skipping."
fi

echo ""
echo "=== [3/4] Validating .env configuration ==="
REQUIRED_KEYS="TAVILY_API_KEY SERPAPI_API_KEY"
if [ ! -f .env ]; then
  echo "   WARNING: .env file not found!"
else
  for key in $REQUIRED_KEYS; do
    val=$(grep -oP "^${key}=\K.*" .env 2>/dev/null || true)
    if [ -z "$val" ] || echo "$val" | grep -qi "^your_\|^<"; then
      echo "   WARNING: $key is missing or still a placeholder."
    else
      echo "   OK: $key is set."
    fi
  done
fi

echo ""
echo "=== [4/4] Restarting application on port 7860 ==="
APP_PID=$(lsof -ti:7860 2>/dev/null || true)
if [ -n "$APP_PID" ]; then
  echo "   Stopping existing process (PID: $APP_PID)..."
  kill -15 "$APP_PID" 2>/dev/null || true
  sleep 2
  kill -9 "$APP_PID" 2>/dev/null || true
  echo "   Stopped."
fi

echo "   Starting app in background..."
nohup uv run python app.py > server.log 2>&1 &
NEW_PID=$!
sleep 8

if ps -p "$NEW_PID" >/dev/null 2>&1; then
  echo "   App running with PID: $NEW_PID"
else
  echo "   ERROR: App failed to start. Logs:"
  tail -n 20 server.log
  exit 1
fi

echo ""
echo "=== All fixes applied successfully ==="
