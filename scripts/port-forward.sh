#!/usr/bin/env bash
# port-forward.sh
# ---------------
# Opens port-forwards for Prometheus and autoscaler self-metrics in the background.
# Grafana and the API service use NodePort so they don't need port-forwarding.
#
# Usage: ./scripts/port-forward.sh
# Stop:  ./scripts/port-forward.sh stop

set -euo pipefail

PF_PIDS_FILE="/tmp/predictive-autoscaler-pf.pids"

start() {
  echo "[port-forward] Starting port-forwards..."

  kubectl port-forward svc/prometheus 9090:9090 &>/tmp/pf-prometheus.log &
  echo $! >> "$PF_PIDS_FILE"
  echo "[port-forward] Prometheus  → http://localhost:9090"

  kubectl port-forward deployment/predictive-autoscaler 9091:9091 &>/tmp/pf-autoscaler.log &
  echo $! >> "$PF_PIDS_FILE"
  echo "[port-forward] Autoscaler metrics → http://localhost:9091/metrics"

  echo ""
  echo "[port-forward] PIDs written to $PF_PIDS_FILE"
  echo "[port-forward] Stop with: ./scripts/port-forward.sh stop"
}

stop() {
  if [ ! -f "$PF_PIDS_FILE" ]; then
    echo "No PID file found at $PF_PIDS_FILE"
    exit 0
  fi
  while read -r pid; do
    kill "$pid" 2>/dev/null && echo "Killed PID $pid" || true
  done < "$PF_PIDS_FILE"
  rm -f "$PF_PIDS_FILE"
  echo "[port-forward] All port-forwards stopped."
}

case "${1:-start}" in
  start) start ;;
  stop)  stop  ;;
  *)     echo "Usage: $0 [start|stop]"; exit 1 ;;
esac
