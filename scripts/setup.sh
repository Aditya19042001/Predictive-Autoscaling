#!/usr/bin/env bash
# setup.sh
# --------
# Full local setup: start minikube, build images, deploy all services.
# Run from the repo root: ./scripts/setup.sh
#
# Prerequisites: docker, minikube, kubectl must be on PATH.
# Tested on macOS (Docker Desktop) and Linux (docker driver).

set -euo pipefail

# ---- Colours ----
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[setup]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
die()   { echo -e "${RED}[error]${NC} $*"; exit 1; }

# ---- Check prerequisites ----
for cmd in docker minikube kubectl; do
  command -v "$cmd" &>/dev/null || die "$cmd not found on PATH"
done

# ---- Start Minikube ----
info "Starting Minikube..."
if minikube status | grep -q "Running"; then
  warn "Minikube already running — skipping start"
else
  minikube start \
    --cpus=4 \
    --memory=8192 \
    --driver=docker \
    --kubernetes-version=v1.28.0
fi

info "Enabling addons..."
minikube addons enable metrics-server
minikube addons enable ingress

# ---- Point Docker CLI at Minikube's daemon ----
# This means 'docker build' writes directly into Minikube's image cache —
# no registry push/pull needed, imagePullPolicy: Never works.
info "Configuring Docker to use Minikube daemon..."
eval "$(minikube docker-env)"

# ---- Build images ----
info "Building api-service image..."
docker build -t api-service:latest ./app

info "Building predictive-autoscaler image..."
docker build -t predictive-autoscaler:latest ./autoscaler

# ---- Deploy: order matters ----
# Prometheus must be up before the autoscaler tries to query it at startup.

info "Deploying Prometheus..."
kubectl apply -f k8s/prometheus/rbac.yaml
kubectl apply -f k8s/prometheus/pvc.yaml
kubectl apply -f k8s/prometheus/configmap.yaml
kubectl apply -f k8s/prometheus/deployment.yaml
kubectl apply -f k8s/prometheus/service.yaml
kubectl rollout status deployment/prometheus --timeout=120s

info "Deploying API service..."
kubectl apply -f k8s/app/deployment.yaml
kubectl apply -f k8s/app/service.yaml
kubectl rollout status deployment/api-service --timeout=120s

info "Deploying Predictive Autoscaler..."
kubectl apply -f k8s/autoscaler/service-account.yaml
kubectl apply -f k8s/autoscaler/cluster-role.yaml
kubectl apply -f k8s/autoscaler/cluster-role-binding.yaml
kubectl apply -f k8s/autoscaler/deployment.yaml
kubectl rollout status deployment/predictive-autoscaler --timeout=120s

info "Deploying Grafana..."
kubectl apply -f k8s/grafana/configmap-provisioning.yaml
kubectl create configmap grafana-dashboards \
  --from-file=k8s/grafana/dashboards/autoscaler-dashboard.json \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f k8s/grafana/deployment.yaml
kubectl apply -f k8s/grafana/service.yaml
kubectl rollout status deployment/grafana --timeout=120s

# ---- Print access URLs ----
echo ""
info "=== All services deployed ==="
echo ""
echo "  API service:  $(minikube service api-service --url)"
echo "  Grafana:      $(minikube service grafana --url)"
echo ""
echo "  Prometheus (port-forward): kubectl port-forward svc/prometheus 9090:9090"
echo ""
echo "  Start load test:  ./scripts/run-load-test.sh"
