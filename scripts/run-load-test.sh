#!/usr/bin/env bash
# run-load-test.sh
# ----------------
# Starts the Locust load test against the Minikube API service.
# Opens the Locust web UI in your browser, OR runs headless if --headless is passed.
#
# Usage:
#   ./scripts/run-load-test.sh            # interactive web UI on :8089
#   ./scripts/run-load-test.sh --headless # runs the three-phase shape immediately

set -euo pipefail

HEADLESS=${1:-""}
LOCUST_FILE="load-generator/locustfile.py"

# Get the API service URL from minikube
API_URL=$(minikube service api-service --url 2>/dev/null) || {
  echo "Could not get api-service URL. Is Minikube running?"
  exit 1
}

echo "[load-test] Target: $API_URL"

if [ "$HEADLESS" = "--headless" ]; then
  echo "[load-test] Running headless three-phase pattern (10 min total)..."
  locust \
    --headless \
    --host="$API_URL" \
    --locustfile="$LOCUST_FILE" \
    --run-time=10m \
    --csv=/tmp/locust-results
  echo "[load-test] Done. CSV results at /tmp/locust-results*.csv"
else
  echo "[load-test] Starting Locust web UI at http://localhost:8089"
  echo "[load-test] Open your browser and set host to: $API_URL"
  locust \
    --host="$API_URL" \
    --locustfile="$LOCUST_FILE" \
    --web-port=8089
fi
