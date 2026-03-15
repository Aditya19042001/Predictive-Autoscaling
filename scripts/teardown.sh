#!/usr/bin/env bash
# teardown.sh
# -----------
# Remove all deployed resources and optionally stop Minikube.
#
# Usage:
#   ./scripts/teardown.sh           # delete k8s resources, keep cluster
#   ./scripts/teardown.sh --stop    # delete resources AND stop minikube

set -euo pipefail

STOP_MINIKUBE=${1:-""}

echo "[teardown] Removing Kubernetes resources..."

kubectl delete -f k8s/grafana/          --ignore-not-found=true
kubectl delete -f k8s/load-generator/   --ignore-not-found=true
kubectl delete -f k8s/autoscaler/       --ignore-not-found=true
kubectl delete -f k8s/app/              --ignore-not-found=true
kubectl delete -f k8s/prometheus/       --ignore-not-found=true

# ConfigMaps created dynamically by setup.sh
kubectl delete configmap grafana-dashboards --ignore-not-found=true
kubectl delete configmap locustfile-config  --ignore-not-found=true

echo "[teardown] All resources removed."

if [ "$STOP_MINIKUBE" = "--stop" ]; then
  echo "[teardown] Stopping Minikube..."
  minikube stop
  echo "[teardown] Minikube stopped."
fi
