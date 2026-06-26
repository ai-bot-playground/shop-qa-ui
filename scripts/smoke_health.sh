#!/usr/bin/env bash
# smoke_health.sh — start the app image, wait for the Streamlit GUI health
# endpoint to report ready, print the container logs, then clean up.
#
# Engine-agnostic: set CONTAINER_CLI=docker (CI) or leave default podman (local).
#   bash scripts/smoke_health.sh [image]
# Returns 0 only if the GUI becomes healthy.
set -u

CLI="${CONTAINER_CLI:-podman}"
IMAGE="${1:-localhost/legacy-documenter:ci}"
PORT="${STREAMLIT_PORT:-8501}"
NAME="lcd-smoke-$$"

cleanup() { "$CLI" rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

"$CLI" rm -f "$NAME" >/dev/null 2>&1 || true
"$CLI" run -d --name "$NAME" -e REPO_PATH=sample -e PYTHONUTF8=1 \
  -p "${PORT}:${PORT}" "$IMAGE" >/dev/null

ok=no
i=0
for i in $(seq 1 45); do
  if ! "$CLI" ps --format '{{.Names}}' | grep -q "^${NAME}$"; then
    echo "container exited early"; break
  fi
  if "$CLI" exec "$NAME" python -c \
      "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:${PORT}/_stcore/health',timeout=2).status==200 else 1)" \
      >/dev/null 2>&1; then
    ok=yes; break
  fi
  sleep 2
done

echo "HEALTH_OK=${ok} (after ~$((i * 2))s)"
echo "--- container logs (tail) ---"
"$CLI" logs --tail 20 "$NAME" 2>&1 || true

[ "$ok" = yes ]
