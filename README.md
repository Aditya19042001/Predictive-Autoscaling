# Predictive Autoscaling for Kubernetes

> Preventing service outages using time-series load forecasting — demonstrated locally with Minikube.

---

## Table of Contents

- [Overview](#overview)
- [Problem Statement](#problem-statement)
- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Folder Structure](#folder-structure)
- [Technology Stack](#technology-stack)
- [Components](#components)
  - [Application Service](#application-service)
  - [Prometheus](#prometheus)
  - [Predictive Autoscaler](#predictive-autoscaler)
  - [Load Generator](#load-generator)
- [Forecasting Model](#forecasting-model)
- [Scaling Decision Algorithm](#scaling-decision-algorithm)
- [Scale-Down Strategy](#scale-down-strategy)
- [Local Setup](#local-setup)
  - [Prerequisites](#prerequisites)
  - [Start the Cluster](#start-the-cluster)
  - [Deploy Services](#deploy-services)
  - [Run Load Test](#run-load-test)
- [Kubernetes Manifests](#kubernetes-manifests)
- [Observability](#observability)
- [Load Testing Scenario](#load-testing-scenario)
- [Configuration Reference](#configuration-reference)
- [Future Improvements](#future-improvements)
- [Key Learnings](#key-learnings)

---

## Overview

Modern microservices rely on **Kubernetes Horizontal Pod Autoscaler (HPA)** which is inherently **reactive** — it scales only after a metric threshold is already breached.

This introduces a gap:

```
Load spike detected → HPA triggers → Pod scheduled → Image pulled → App starts → Pod ready
                                                                                      ↑
                                                               30–120 seconds of degraded service
```

This project implements a **Predictive Autoscaling Controller** that:

- Collects time-series metrics from Prometheus
- Forecasts future request load using Holt-Winters exponential smoothing
- Calculates required pod count **before** the spike hits
- Scales the Kubernetes deployment proactively via the Kubernetes API

The entire system runs locally on **Minikube**.

---

## Problem Statement

Reactive autoscaling reacts to what has already happened. During the startup window:

- Request queues build up
- Response latency increases
- Requests may be dropped
- SLAs are breached

For services with **predictable traffic patterns** (daily peaks, weekly cycles, scheduled batch jobs), this gap is entirely preventable. Predictive autoscaling closes it.

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────────┐
│  Every 60 seconds:                                                  │
│                                                                     │
│  1. Query Prometheus → last 20 min of request rate                  │
│  2. Fit Holt-Winters model → predict next 10 min RPS                │
│  3. pods_required = ceil(predicted_rps / pod_capacity)              │
│  4. If pods_required != current_pods → PATCH Kubernetes deployment  │
└─────────────────────────────────────────────────────────────────────┘
```

The autoscaler runs as an **independent service** — fully decoupled from the application it manages. It can fail, restart, or be updated without touching the application.

---

## Architecture

```
                    +---------------------+
                    |   Load Generator    |
                    |    (Locust / k6)    |
                    +----------+----------+
                               |  HTTP traffic
                               ▼
                    +----------------------+
                    | Python API Service   |
                    | (FastAPI)            |
                    | /metrics endpoint    |
                    +----------+-----------+
                               |  Prometheus scrape (every 5s)
                               ▼
                        +--------------+
                        |  Prometheus  |
                        |  Metrics DB  |
                        +------+-------+
                               |  PromQL queries
                               ▼
        +--------------------------------------------------+
        |        Predictive Autoscaler Service             |
        |--------------------------------------------------|
        |  Prometheus Client   →  Fetch raw time-series    |
        |  Holt-Winters Model  →  Forecast future RPS      |
        |  Decision Engine     →  Calculate pod count      |
        |  Kubernetes Client   →  PATCH deployment         |
        +-------------------+------------------------------+
                            |  Kubernetes API
                            ▼
                    +----------------------+
                    | Kubernetes           |
                    | Deployment Scaling   |
                    +----------------------+
```

---

## Folder Structure

```
predictive-autoscaler/
│
├── README.md                          # This file
│
├── app/                               # FastAPI application service
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                        # FastAPI app entry point
│   ├── metrics.py                     # Prometheus metric definitions
│   └── routers/
│       └── api.py                     # API route handlers
│
├── autoscaler/                        # Predictive autoscaler service
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                        # Autoscaler entry point (control loop)
│   ├── config.py                      # Config (Prometheus URL, thresholds, etc.)
│   ├── prometheus_client.py           # Prometheus query client
│   ├── forecaster.py                  # Holt-Winters forecasting model
│   ├── scaler.py                      # Scaling decision engine
│   └── k8s_client.py                  # Kubernetes API wrapper
│
├── load-generator/                    # Traffic simulation
│   ├── locustfile.py                  # Locust load test definition
│   ├── k6-script.js                   # k6 load test alternative
│   └── requirements.txt
│
├── k8s/                               # Kubernetes manifests
│   ├── namespace.yaml
│   ├── app/
│   │   ├── deployment.yaml            # FastAPI app deployment
│   │   ├── service.yaml               # ClusterIP / NodePort service
│   │   └── configmap.yaml
│   ├── autoscaler/
│   │   ├── deployment.yaml            # Autoscaler deployment
│   │   ├── service-account.yaml       # RBAC service account
│   │   ├── cluster-role.yaml          # RBAC: permission to patch deployments
│   │   └── cluster-role-binding.yaml
│   ├── prometheus/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   ├── configmap.yaml             # prometheus.yml scrape config
│   │   └── pvc.yaml                   # Persistent volume claim
│   ├── grafana/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   └── dashboards/
│   │       └── autoscaler-dashboard.json
│   └── load-generator/
│       └── job.yaml                   # Kubernetes Job for load test
│
├── dashboards/                        # Grafana dashboard exports
│   └── predictive-autoscaler.json
│
├── docs/                              # Additional documentation
│   ├── architecture.md
│   ├── forecasting-model.md
│   └── scaling-algorithm.md
│
├── scripts/                           # Utility scripts
│   ├── setup.sh                       # Full local setup script
│   ├── teardown.sh                    # Clean up all resources
│   ├── port-forward.sh                # Port-forward Prometheus + Grafana
│   └── run-load-test.sh               # Start Locust load test
│
├── tests/                             # Unit and integration tests
│   ├── unit/
│   │   ├── test_forecaster.py
│   │   ├── test_scaler.py
│   │   └── test_prometheus_client.py
│   └── integration/
│       └── test_autoscaler_loop.py
│
└── docker-compose.yaml                # Optional: run locally without Minikube
```

---

## Technology Stack

### Infrastructure

| Tool | Version | Purpose |
|------|---------|---------|
| Kubernetes | 1.28+ | Container orchestration |
| Minikube | 1.32+ | Local Kubernetes cluster |
| Docker | 24+ | Container runtime |
| kubectl | 1.28+ | Cluster CLI |

### Application & Autoscaler

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.11 | Primary language |
| FastAPI | 0.110+ | API service framework |
| Uvicorn | 0.29+ | ASGI server |
| Pandas | 2.2+ | Time-series data manipulation |
| NumPy | 1.26+ | Numerical computation |
| Statsmodels | 0.14+ | Holt-Winters forecasting |
| kubernetes | 29.0+ | Kubernetes Python client |

### Observability

| Tool | Purpose |
|------|---------|
| Prometheus | Metrics collection and storage |
| prometheus-client (Python) | Expose `/metrics` from FastAPI |
| Grafana | Dashboard visualization (optional) |

### Load Testing

| Tool | Purpose |
|------|---------|
| Locust | Python-based load generation |
| k6 | JavaScript-based load generation (alternative) |

---

## Components

### Application Service

Located in `app/`. A FastAPI service deployed in Kubernetes that:

- Handles incoming HTTP requests
- Simulates variable workload (CPU-bound operations on heavy endpoints)
- Exposes Prometheus metrics at `/metrics`

**Key metrics exposed:**

```
http_requests_total{method, endpoint, status}   # Request counter
request_latency_seconds{endpoint}               # Histogram
inflight_requests                               # Current active requests
cpu_usage_percent                               # Simulated CPU load
memory_usage_bytes                              # Memory consumption
```

**Example `metrics.py`:**

```python
from prometheus_client import Counter, Histogram, Gauge

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"]
)

REQUEST_LATENCY = Histogram(
    "request_latency_seconds",
    "Request latency",
    ["endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5]
)

INFLIGHT_REQUESTS = Gauge(
    "inflight_requests",
    "Current in-flight requests"
)
```

---

### Prometheus

Located in `k8s/prometheus/`. Configured to scrape the API service every 5 seconds.

**`prometheus.yml` (in ConfigMap):**

```yaml
global:
  scrape_interval: 5s
  evaluation_interval: 5s

scrape_configs:
  - job_name: "api-service"
    static_configs:
      - targets: ["api-service:8000"]
    metrics_path: /metrics
```

**Key PromQL queries used by the autoscaler:**

```promql
# Request rate over last 2 minutes
rate(http_requests_total[2m])

# 95th percentile latency
histogram_quantile(0.95, rate(request_latency_seconds_bucket[2m]))

# Current pod count (via kube_deployment_status_replicas)
kube_deployment_status_replicas{deployment="api-service"}
```

---

### Predictive Autoscaler

Located in `autoscaler/`. The core of the project. Runs a control loop every 60 seconds.

**`main.py` — control loop:**

```python
import time
from prometheus_client import fetch_request_rate
from forecaster import predict_rps
from scaler import calculate_pods
from k8s_client import get_current_replicas, scale_deployment

LOOP_INTERVAL = 60  # seconds

def run():
    while True:
        # 1. Fetch historical metrics
        history = fetch_request_rate(lookback_minutes=20)

        # 2. Forecast future load
        predicted_rps = predict_rps(history, horizon_minutes=10)

        # 3. Calculate required pods
        current_pods = get_current_replicas("api-service")
        target_pods = calculate_pods(predicted_rps, current_pods)

        # 4. Scale if needed
        if target_pods != current_pods:
            scale_deployment("api-service", target_pods)
            print(f"Scaled: {current_pods} → {target_pods} pods (predicted RPS: {predicted_rps:.1f})")

        time.sleep(LOOP_INTERVAL)

if __name__ == "__main__":
    run()
```

**`forecaster.py` — Holt-Winters model:**

```python
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

def predict_rps(history: list[float], horizon_minutes: int = 10) -> float:
    series = pd.Series(history)

    model = ExponentialSmoothing(
        series,
        trend="add",
        seasonal="add",
        seasonal_periods=12   # 12 × 5s scrapes = 1 minute season
    )
    fit = model.fit()
    forecast = fit.forecast(steps=horizon_minutes * 12)

    return float(forecast.max())   # Use peak predicted value
```

**`scaler.py` — scaling decision:**

```python
import math

POD_CAPACITY_RPS = 150   # Each pod handles up to 150 req/s
MIN_PODS = 1
MAX_PODS = 20
SCALE_DOWN_THRESHOLD = 0.6
COOLDOWN_SECONDS = 600   # 10 minutes

last_scale_down_time = 0

def calculate_pods(predicted_rps: float, current_pods: int) -> int:
    pods_required = math.ceil(predicted_rps / POD_CAPACITY_RPS)
    pods_required = max(MIN_PODS, min(MAX_PODS, pods_required))

    # Conservative scale-down with cooldown
    current_capacity = current_pods * POD_CAPACITY_RPS
    if predicted_rps < current_capacity * SCALE_DOWN_THRESHOLD:
        import time
        global last_scale_down_time
        now = time.time()
        if now - last_scale_down_time > COOLDOWN_SECONDS:
            last_scale_down_time = now
            return pods_required
        return current_pods  # Hold during cooldown

    return pods_required
```

**`k8s_client.py` — Kubernetes API:**

```python
from kubernetes import client, config

config.load_incluster_config()   # Use in-cluster credentials
apps_v1 = client.AppsV1Api()

NAMESPACE = "default"

def get_current_replicas(deployment_name: str) -> int:
    dep = apps_v1.read_namespaced_deployment(deployment_name, NAMESPACE)
    return dep.spec.replicas

def scale_deployment(deployment_name: str, replicas: int):
    body = {"spec": {"replicas": replicas}}
    apps_v1.patch_namespaced_deployment_scale(
        name=deployment_name,
        namespace=NAMESPACE,
        body=body
    )
```

---

### Load Generator

Located in `load-generator/`. Simulates realistic traffic patterns.

**`locustfile.py`:**

```python
from locust import HttpUser, task, between

class APIUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(8)
    def light_request(self):
        self.client.get("/api/v1/ping")

    @task(2)
    def heavy_request(self):
        self.client.post("/api/v1/process", json={"data": "payload"})
```

---

## Forecasting Model

The autoscaler uses **Holt-Winters exponential smoothing** (triple exponential smoothing) from `statsmodels`.

### Why Holt-Winters

| Property | Detail |
|----------|--------|
| **Trend** | Captures rising or falling request rates |
| **Seasonality** | Captures repeating daily/weekly traffic patterns |
| **Data requirement** | Works well on 20+ minutes of data |
| **Latency** | Fits in milliseconds — safe for a 60s control loop |
| **Library** | `statsmodels.tsa.holtwinters.ExponentialSmoothing` |

### Why Not LSTM / Deep Learning

- Requires large training datasets
- Training is slow and unstable
- Adds operational complexity (model serving, versioning)
- Not suited for a real-time control loop

### Input / Output

```
Input:  last 20 minutes of request rate (scraped at 5s intervals → 240 data points)
Output: predicted peak RPS over the next 10 minutes
```

### Alternative Models (Optional Experiments)

- **ARIMA** — better for non-seasonal series, requires manual order selection
- **Facebook Prophet** — excellent for daily/weekly seasonality, higher latency

---

## Scaling Decision Algorithm

```
predicted_rps = 420
pod_capacity  = 150 req/s per pod

pods_required = ceil(420 / 150) = 3

current_pods  = 1
action        = scale to 3
```

**Bounds:**

```
MIN_PODS = 1    # Never scale to zero
MAX_PODS = 20   # Never exceed cluster capacity
```

---

## Scale-Down Strategy

Aggressive scale-up, conservative scale-down.

```
Scale up:   Immediately, whenever pods_required > current_pods

Scale down: Only when:
            predicted_rps < current_capacity × 0.6
            AND cooldown period (10 min) has elapsed since last scale-down
```

This prevents thrashing — where a brief dip in predictions causes pods to be removed and then immediately re-added.

---

## Local Setup

### Prerequisites

Install the following tools:

```bash
# Docker
https://docs.docker.com/get-docker/

# Minikube
https://minikube.sigs.k8s.io/docs/start/

# kubectl
https://kubernetes.io/docs/tasks/tools/

# Python 3.11
https://www.python.org/downloads/
```

Verify installations:

```bash
docker --version
minikube version
kubectl version --client
python3 --version
```

---

### Start the Cluster

```bash
# Start Minikube with enough resources
minikube start --cpus=4 --memory=8g --driver=docker

# Enable required addons
minikube addons enable metrics-server
minikube addons enable ingress

# Point Docker CLI to Minikube's daemon (builds images directly into cluster)
eval $(minikube docker-env)

# Verify cluster is running
kubectl get nodes
```

---

### Deploy Services

```bash
# 1. Create namespace
kubectl apply -f k8s/namespace.yaml

# 2. Deploy Prometheus
kubectl apply -f k8s/prometheus/

# 3. Build and deploy the API service
docker build -t api-service:latest ./app
kubectl apply -f k8s/app/

# 4. Build and deploy the autoscaler
docker build -t predictive-autoscaler:latest ./autoscaler
kubectl apply -f k8s/autoscaler/

# 5. (Optional) Deploy Grafana
kubectl apply -f k8s/grafana/

# Verify all pods are running
kubectl get pods -n default
```

---

### Run Load Test

```bash
# Option A: Locust (web UI)
pip install locust
minikube service api-service --url   # Get the service URL
locust -f load-generator/locustfile.py --host=<SERVICE_URL>
# Open http://localhost:8089 → set users and spawn rate

# Option B: k6
k6 run load-generator/k6-script.js

# Option C: Run as Kubernetes Job
kubectl apply -f k8s/load-generator/job.yaml
kubectl logs -f job/load-generator
```

---

### Access Dashboards

```bash
# Prometheus UI
kubectl port-forward svc/prometheus 9090:9090
open http://localhost:9090

# Grafana (if deployed)
kubectl port-forward svc/grafana 3000:3000
open http://localhost:3000
# Default credentials: admin / admin

# API service directly
minikube service api-service
```

Or use the convenience script:

```bash
./scripts/port-forward.sh
```

---

## Kubernetes Manifests

### RBAC — the autoscaler needs permission to patch deployments

**`k8s/autoscaler/cluster-role.yaml`:**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: predictive-autoscaler-role
rules:
  - apiGroups: ["apps"]
    resources: ["deployments", "deployments/scale"]
    verbs: ["get", "list", "patch", "update"]
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list"]
```

**`k8s/autoscaler/deployment.yaml`:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: predictive-autoscaler
spec:
  replicas: 1
  selector:
    matchLabels:
      app: predictive-autoscaler
  template:
    metadata:
      labels:
        app: predictive-autoscaler
    spec:
      serviceAccountName: predictive-autoscaler-sa
      containers:
        - name: autoscaler
          image: predictive-autoscaler:latest
          imagePullPolicy: Never
          env:
            - name: PROMETHEUS_URL
              value: "http://prometheus:9090"
            - name: TARGET_DEPLOYMENT
              value: "api-service"
            - name: NAMESPACE
              value: "default"
            - name: POD_CAPACITY_RPS
              value: "150"
            - name: LOOP_INTERVAL_SECONDS
              value: "60"
```

---

## Observability

### Metrics to Watch

| Metric | Source | Description |
|--------|--------|-------------|
| `http_requests_total` | API service | Actual incoming request count |
| `request_latency_seconds` | API service | Response latency distribution |
| `inflight_requests` | API service | Current concurrent requests |
| `autoscaler_predicted_rps` | Autoscaler | Forecasted RPS (next 10 min) |
| `autoscaler_current_pods` | Autoscaler | Current replica count |
| `autoscaler_target_pods` | Autoscaler | Target replica count |

### Grafana Dashboard Panels

```
1. Actual RPS vs Predicted RPS          (line chart, time series)
2. Pod count over time                  (step chart)
3. Request latency p50/p95/p99          (line chart)
4. Inflight requests                    (gauge)
5. Scaling events log                   (table)
```

The dashboard JSON is exported to `dashboards/predictive-autoscaler.json` and auto-provisioned by Grafana on startup.

---

## Load Testing Scenario

The demonstration uses the following traffic pattern:

```
Phase           Duration    RPS     Pods Expected
──────────────────────────────────────────────────
Baseline        0–3 min     50      1
Spike           3–6 min     500     4
Cool-down       6–10 min    150     1
```

**Expected behaviour:**

```
t=2:00  Autoscaler detects rising trend in 20-min window
t=2:30  Forecaster predicts ~500 RPS at t=3:00
t=2:30  Decision engine calculates 4 pods required
t=2:30  Kubernetes deployment patched → replicas=4
t=3:00  Traffic spike arrives → pods already ready → no dropped requests
t=7:00  Predicted RPS drops below 60% threshold
t=7:00  Cooldown begins (10 min)
t=17:00 Scale-down executes → replicas=1
```

---

## Configuration Reference

All configuration is passed via environment variables to both services.

### Autoscaler (`autoscaler/config.py`)

| Variable | Default | Description |
|----------|---------|-------------|
| `PROMETHEUS_URL` | `http://prometheus:9090` | Prometheus endpoint |
| `TARGET_DEPLOYMENT` | `api-service` | Deployment to manage |
| `NAMESPACE` | `default` | Kubernetes namespace |
| `POD_CAPACITY_RPS` | `150` | Max RPS per pod |
| `MIN_PODS` | `1` | Minimum replica floor |
| `MAX_PODS` | `20` | Maximum replica ceiling |
| `LOOKBACK_MINUTES` | `20` | Historical data window |
| `HORIZON_MINUTES` | `10` | Forecast horizon |
| `LOOP_INTERVAL_SECONDS` | `60` | Control loop frequency |
| `SCALE_DOWN_THRESHOLD` | `0.6` | Scale-down trigger (fraction of capacity) |
| `COOLDOWN_SECONDS` | `600` | Scale-down cooldown period |

### API Service (`app/`)

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8000` | Uvicorn listen port |
| `WORKERS` | `1` | Uvicorn worker count |
| `LOG_LEVEL` | `info` | Logging verbosity |

---

## Future Improvements

| Improvement | Description |
|-------------|-------------|
| **Confidence-based scaling** | Use Holt-Winters prediction intervals to scale more aggressively when confident, more conservatively when uncertain |
| **Multi-metric forecasting** | Combine RPS, CPU, and memory trends for a more robust signal |
| **Cold-start fallback** | Fall back to HPA during the first N minutes before sufficient history is accumulated |
| **Anomaly detection** | Detect sudden unexpected spikes outside the forecast confidence interval and trigger emergency scaling |
| **Reinforcement learning** | Replace the rule-based decision engine with an RL policy that optimises for cost and availability jointly |
| **Predictive node scaling** | Extend beyond pod scaling to proactively add Kubernetes nodes before pod capacity is exhausted |
| **Cost-aware autoscaling** | Factor in per-pod cost and apply business-hours vs off-hours scaling policies |
| **KEDA integration** | Expose predictions as a custom KEDA scaler rather than bypassing HPA entirely |
| **Prometheus Operator** | Replace hand-rolled Prometheus manifests with the Prometheus Operator for production-grade deployment |

---

## Key Learnings

- **Reactive autoscaling has a structural latency floor** — the HPA startup gap (30–120s) is not a tuning problem; it is inherent to the detect-then-act model.
- **Holt-Winters is well-suited to this problem** — it captures trend and seasonality with minimal data and negligible computational overhead, making it safe for a real-time control loop.
- **The autoscaler must be a separate service** — coupling the prediction logic to the application creates a circular dependency and complicates independent iteration.
- **Scale-down conservatism prevents thrashing** — a cooldown window and a capacity threshold (not a hard RPS threshold) are the correct primitives for stable scale-down behaviour.
- **The Kubernetes Python client makes programmatic scaling straightforward** — `PATCH /apis/apps/v1/namespaces/{ns}/deployments/{name}/scale` is all that is needed.
- **RBAC is not optional** — the autoscaler service account must be explicitly granted permission to patch deployments; no implicit cluster-admin access should be used in any real deployment.

---

## License

MIT

---

## Author

Built as a demonstration of predictive infrastructure management using open-source tooling.

**Stack:** Kubernetes · Minikube · Prometheus · Python · FastAPI · Statsmodels · Docker
