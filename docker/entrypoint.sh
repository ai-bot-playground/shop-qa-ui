#!/usr/bin/env sh
# entrypoint.sh — uruchamia aplikację Streamlit, a dopóki kod nie jest wpięty,
# pokazuje stronę-placeholder. To czyni szkielet uruchamialnym od pierwszego dnia,
# zanim instancje T1–T5 dostarczą app.py / src/*.
set -e

APP="${APP_ENTRYPOINT:-app.py}"
PORT="${STREAMLIT_PORT:-8501}"

STREAMLIT_FLAGS="--server.port=${PORT} \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --browser.gatherUsageStats=false"

if [ -f "$APP" ]; then
  echo "[entrypoint] Uruchamiam aplikację: $APP"
  # shellcheck disable=SC2086
  exec streamlit run "$APP" $STREAMLIT_FLAGS
else
  echo "[entrypoint] Nie znaleziono '$APP' — uruchamiam placeholder (czekam na kod aplikacji)."
  # shellcheck disable=SC2086
  exec streamlit run /app/docker/placeholder_app.py $STREAMLIT_FLAGS
fi
