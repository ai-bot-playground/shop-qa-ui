#!/usr/bin/env sh
# entrypoint.sh — uruchamia aplikację Streamlit.
set -e

APP="${APP_ENTRYPOINT:-app.py}"
PORT="${STREAMLIT_PORT:-8501}"

STREAMLIT_FLAGS="--server.port=${PORT} \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --browser.gatherUsageStats=false"

if [ ! -f "$APP" ]; then
  echo "[entrypoint] BŁĄD: nie znaleziono '$APP'." >&2
  exit 1
fi

echo "[entrypoint] Uruchamiam aplikację: $APP"
# shellcheck disable=SC2086
exec streamlit run "$APP" $STREAMLIT_FLAGS
