# Running the Predictive Autoscaler — Complete Beginner's Guide

This guide takes you from a fresh laptop to a running demo where you can **watch
pods scale up before a traffic spike hits** and see the prediction vs actual RPS
side by side in Grafana.

Read every section in order the first time. Each step builds on the previous one.

---

## Table of Contents

1. [What You Will See](#1-what-you-will-see)
2. [How the System Works — Plain English](#2-how-the-system-works--plain-english)
3. [Prerequisites — What You Need to Install](#3-prerequisites--what-you-need-to-install)
   - [macOS](#macos)
   - [Linux (Ubuntu / Debian)](#linux-ubuntu--debian)
   - [Windows](#windows)
4. [Verify Your Installation](#4-verify-your-installation)
5. [Get the Code](#5-get-the-code)
6. [Choose Your Mode](#6-choose-your-mode)
7. [Mode A — Docker Compose (Easiest, No Kubernetes)](#7-mode-a--docker-compose-easiest-no-kubernetes)
   - [Start Everything](#start-everything)
   - [Open the Dashboards](#open-the-dashboards)
   - [Run the Load Test](#run-the-load-test)
   - [Watch What Happens](#watch-what-happens)
   - [Stop Everything](#stop-everything)
8. [Mode B — Minikube (Full Kubernetes Demo)](#8-mode-b--minikube-full-kubernetes-demo)
   - [Start Minikube](#start-minikube)
   - [Build and Deploy with One Script](#build-and-deploy-with-one-script)
   - [Open the Dashboards](#open-the-dashboards-1)
   - [Run the Load Test](#run-the-load-test-1)
   - [Watch What Happens](#watch-what-happens-1)
   - [Watch Pods Scale in Real Time](#watch-pods-scale-in-real-time)
   - [Stop Everything](#stop-everything-1)
9. [Running the Tests](#9-running-the-tests)
10. [Understanding the Grafana Dashboard](#10-understanding-the-grafana-dashboard)
11. [Understanding the Autoscaler Logs](#11-understanding-the-autoscaler-logs)
12. [Tuning and Experimenting](#12-tuning-and-experimenting)
13. [Troubleshooting](#13-troubleshooting)
14. [What Each File Does — Quick Reference](#14-what-each-file-does--quick-reference)

---

## 1. What You Will See

By the end of this guide you will have:

```
Browser tab 1 — Grafana dashboard
  ┌─────────────────────────────────────────────────┐
  │  Actual RPS ──────   Predicted RPS - - - - -    │
  │                                                 │
  │       /‾‾‾‾‾‾‾‾\                               │
  │      /  spike   \    predicted line rises       │
  │_____/  500 RPS   \___  BEFORE the spike hits    │
  └─────────────────────────────────────────────────┘

Browser tab 2 — Pod count
  t=0:00  pods = 1
  t=2:30  pods = 4  ← autoscaler scaled UP before the spike
  t=3:00  spike arrives → all 4 pods already ready, no dropped requests
  t=7:00  pods = 1  ← autoscaler scaled back down after cooldown

Terminal — autoscaler logs
  [autoscaler] Fetched 240 data points (current RPS: 87.3)
  [autoscaler] Decision: SCALE | predicted=423.1 RPS | current=1 pods | target=3 pods
  [autoscaler] Reason: Scale UP: predicted 423.1 RPS requires 3 pods ...
  [autoscaler] Patched default/api-service → 3 replicas
```

---

## 2. How the System Works — Plain English

There are four pieces:

**1. API Service** — A small web server (FastAPI) that handles HTTP requests and
reports metrics like "how many requests per second am I getting?" to Prometheus.
Think of it as the service you are trying to protect from traffic spikes.

**2. Prometheus** — A database that scrapes the API service every 5 seconds and
stores those metrics. It is the autoscaler's source of truth.

**3. Predictive Autoscaler** — This is the interesting part. Every 60 seconds it:
- Asks Prometheus: "what was the request rate for the last 20 minutes?"
- Feeds those numbers into a forecasting algorithm (Holt-Winters)
- Predicts what the request rate will be 10 minutes from now
- Calculates how many pods are needed to handle that predicted load
- If the number differs from today's pod count, it tells Kubernetes to scale

**4. Grafana** — A dashboard that plots actual vs predicted RPS and pod count so
you can see the autoscaler's decisions visually.

The key difference from Kubernetes' built-in autoscaler (HPA) is that HPA waits
for a spike to happen, then scales. This autoscaler sees the spike coming and
scales **before** it arrives — usually 1–2 minutes early.

---

## 3. Prerequisites — What You Need to Install

You need four tools. Install them for your operating system below.

| Tool | What it does | Minimum version |
|------|-------------|-----------------|
| Docker | Runs containers | 24.0 |
| Python | Runs the load test | 3.11 |
| Minikube | Local Kubernetes cluster (Mode B only) | 1.32 |
| kubectl | Talk to Kubernetes (Mode B only) | 1.28 |

> **Mode A (Docker Compose) only needs Docker and Python.**
> You can skip Minikube and kubectl if you just want to see the forecasting
> and load test without real Kubernetes scaling.

---

### macOS

Open **Terminal** and run these commands one by one.

**Install Homebrew** (if you do not have it):
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

**Install Docker Desktop:**
```bash
brew install --cask docker
```
Then open Docker Desktop from your Applications folder and wait for it to say
"Docker Desktop is running" in the menu bar icon.

**Install Python 3.11:**
```bash
brew install python@3.11
```

**Install Minikube (Mode B only):**
```bash
brew install minikube
```

**Install kubectl (Mode B only):**
```bash
brew install kubectl
```

---

### Linux (Ubuntu / Debian)

Open a terminal and run:

**Install Docker:**
```bash
# Remove old versions if any
sudo apt-get remove docker docker-engine docker.io containerd runc 2>/dev/null

# Install
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release

sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Allow your user to run Docker without sudo
sudo usermod -aG docker $USER
newgrp docker
```

**Install Python 3.11:**
```bash
sudo apt-get install -y python3.11 python3.11-pip python3.11-venv
```

**Install Minikube (Mode B only):**
```bash
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
rm minikube-linux-amd64
```

**Install kubectl (Mode B only):**
```bash
curl -LO "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
rm kubectl
```

---

### Windows

On Windows the easiest path is **WSL 2** (Windows Subsystem for Linux) with
Docker Desktop.

1. Open PowerShell as Administrator and run:
   ```powershell
   wsl --install
   ```
2. Restart your machine.
3. Download and install **Docker Desktop for Windows** from
   https://www.docker.com/products/docker-desktop/
   — enable the WSL 2 backend when prompted.
4. Open the **Ubuntu** app from the Start menu.
5. Inside Ubuntu, follow the **Linux (Ubuntu / Debian)** instructions above.

> All commands in the rest of this guide should be run inside the Ubuntu WSL
> terminal, not in PowerShell or Command Prompt.

---

## 4. Verify Your Installation

Run these commands and check the versions match or exceed the minimums:

```bash
docker --version
# Expected: Docker version 24.x.x or higher

docker compose version
# Expected: Docker Compose version v2.x.x

python3 --version
# Expected: Python 3.11.x

# Mode B only:
minikube version
# Expected: minikube version: v1.32.x or higher

kubectl version --client
# Expected: Client Version: v1.28.x or higher
```

If any command says "command not found", go back to Section 3 and install
the missing tool.

---

## 5. Get the Code

```bash
# Clone the repository
git clone https://github.com/your-org/predictive-autoscaler.git

# Move into the project folder — ALL commands from here on are run from here
cd predictive-autoscaler

# Confirm you are in the right place
ls
# You should see: app/  autoscaler/  k8s/  load-generator/  scripts/  docker-compose.yaml
```

> **If you received a zip file instead of a git URL:**
> ```bash
> unzip predictive-autoscaler.zip
> cd predictive-autoscaler
> ```

---

## 6. Choose Your Mode

| | Mode A — Docker Compose | Mode B — Minikube |
|---|---|---|
| **Setup time** | ~5 minutes | ~15 minutes |
| **Requirements** | Docker + Python | Docker + Python + Minikube + kubectl |
| **What you get** | Forecasting + Grafana + load test | Everything + real Kubernetes pod scaling |
| **Autoscaler actually scales pods?** | No (logs decisions only) | Yes |
| **Good for** | Learning the forecasting logic | Full end-to-end demo |

**Recommendation for first-timers:** Start with Mode A to see the forecasting
and Grafana dashboard. Once that works, try Mode B to see real Kubernetes
scaling in action.

---

## 7. Mode A — Docker Compose (Easiest, No Kubernetes)

### Start Everything

One command starts all four services (API, Prometheus, Grafana, Autoscaler):

```bash
docker compose up --build
```

**What you will see in the terminal:**

```
[+] Building api-service...
[+] Building autoscaler...
[+] Running 4/4
 ✔ Container prometheus    Started
 ✔ Container api-service   Started
 ✔ Container autoscaler    Started
 ✔ Container grafana       Started

autoscaler  | 2024-01-15T10:00:00 [INFO] autoscaler — Autoscaler started
autoscaler  | 2024-01-15T10:00:00 [INFO] autoscaler — Self-metrics server started on :9091
prometheus  | level=info msg="Server is ready to receive web requests."
api-service | INFO:     Application startup complete.
grafana     | logger=http.server t=... msg="HTTP Server Listen" address=[::]:3000
```

Wait until you see **all four** services show startup messages (about 30 seconds).

> **First run takes longer** because Docker needs to download the base images
> (Python, Prometheus, Grafana). Subsequent runs are fast.

---

### Open the Dashboards

Open these URLs in your browser:

| Service | URL | What it shows |
|---------|-----|---------------|
| **Grafana** | http://localhost:3000 | Main dashboard — use this during the demo |
| **API service** | http://localhost:8000/docs | Interactive API docs |
| **API metrics** | http://localhost:8000/metrics | Raw Prometheus metrics |
| **Prometheus** | http://localhost:9090 | Query interface (advanced) |

**Setting up Grafana for the first time:**

1. Go to http://localhost:3000
2. You will land directly on the dashboard (anonymous access is enabled, no login needed)
3. Click the menu icon (☰) → **Dashboards** → **Predictive Autoscaler**
4. You should see the dashboard with empty graphs (no traffic yet — that is fine)

---

### Run the Load Test

Install Locust (the load testing tool) and point it at the API service:

```bash
# Install Locust (one time only)
pip3 install locust==2.24.1

# Start the load test
locust -f load-generator/locustfile.py --host=http://localhost:8000
```

Now open **http://localhost:8089** in a new browser tab. You will see the
Locust web interface.

Fill in:
- **Number of users**: `50`
- **Spawn rate**: `5`
- **Host**: `http://localhost:8000` (pre-filled)

Click **Start swarming**.

> **What these numbers mean:**
> - 50 users = 50 simulated people hitting the API simultaneously
> - Spawn rate 5 = add 5 new users every second until we reach 50
> - This generates roughly 100–500 requests per second

---

### Watch What Happens

Go back to **Grafana** (http://localhost:3000) and watch the dashboard.

Within the first **2–3 minutes** you will see:

1. **Actual RPS** (solid line) — rises as Locust ramps up traffic
2. **Predicted RPS** (dashed orange line) — the autoscaler's forecast; rises
   slightly ahead of actual because it is projecting the trend forward

In the **autoscaler terminal output** you will see messages like:

```
[autoscaler] Fetched 48 data points (current RPS: 43.2)
[autoscaler] Decision: HOLD | predicted=67.1 RPS | current=1 pods | target=1 pods
[autoscaler] Reason: No change: 1 pods at 67.1/150.0 RPS

... 60 seconds later ...

[autoscaler] Fetched 60 data points (current RPS: 112.7)
[autoscaler] Decision: SCALE | predicted=198.4 RPS | current=1 pods | target=2 pods
[autoscaler] Reason: Scale UP: predicted 198.4 RPS requires 2 pods (current: 1, capacity: 150 RPS)
```

> **In Docker Compose mode the autoscaler logs the decision but does not
> actually patch a Kubernetes deployment** (there is no Kubernetes running).
> To see real pod scaling, use Mode B.

**To trigger a clear spike during the test:** Go back to Locust
(http://localhost:8089) and click **Edit** → change users to `200` → click
**Update**. Watch the Actual RPS jump and the Predicted RPS respond.

---

### Stop Everything

```bash
# In the terminal where docker compose is running, press:
Ctrl + C

# Then remove the containers:
docker compose down

# To also remove all stored Prometheus data:
docker compose down -v
```

---

## 8. Mode B — Minikube (Full Kubernetes Demo)

This mode runs the exact same system inside a real Kubernetes cluster on your
laptop. The autoscaler will actually patch Kubernetes deployments and you will
watch pods appear and disappear.

### Start Minikube

```bash
minikube start \
  --cpus=4 \
  --memory=6144 \
  --driver=docker \
  --kubernetes-version=v1.28.0
```

**What you will see:**

```
😄  minikube v1.32.0
✨  Using the docker driver based on user configuration
📌  Using Docker driver with root privileges
👍  Starting control plane node minikube in cluster minikube
🚜  Pulling base image ...
🔥  Creating docker container (CPUs=4, Memory=8192MB) ...
🐳  Preparing Kubernetes v1.28.0 on Docker 24.0.7 ...
🔎  Verifying Kubernetes components...
✅  kubectl is now configured to use "minikube" cluster
```

This takes **2–5 minutes** the first time (downloads the Kubernetes images).

**Verify the cluster is healthy:**

```bash
kubectl get nodes
# Expected output:
# NAME       STATUS   ROLES           AGE   VERSION
# minikube   Ready    control-plane   30s   v1.28.0
```

If the status says `Ready`, you are good. If it says `NotReady`, wait 30 more
seconds and run the command again.

---

### Build and Deploy with One Script

One script handles everything: building Docker images, applying all Kubernetes
manifests, and waiting for pods to be ready.

```bash
chmod +x scripts/setup.sh
./scripts/setup.sh
```

**What the script does, step by step:**

```
[setup] Starting Minikube...              ← checks if cluster is running
[setup] Enabling addons...               ← enables metrics-server
[setup] Configuring Docker to use Minikube daemon...
[setup] Building api-service image...    ← builds inside Minikube (no registry needed)
[setup] Building predictive-autoscaler image...
[setup] Deploying Prometheus...          ← applies k8s/prometheus/*.yaml
[setup] Deploying API service...         ← applies k8s/app/*.yaml
[setup] Deploying Predictive Autoscaler... ← applies k8s/autoscaler/*.yaml (RBAC first)
[setup] Deploying Grafana...             ← applies k8s/grafana/*.yaml
[setup] Waiting for all pods to be ready...
[setup] === All services deployed ===

  API service:  http://192.168.49.2:30800
  Grafana:      http://192.168.49.2:30300

  Prometheus (port-forward): kubectl port-forward svc/prometheus 9090:9090

  Start load test:  ./scripts/run-load-test.sh
```

The whole script takes **3–5 minutes** on first run.

> **If the script fails** with "imagePullBackOff" or "ErrImageNeverPull":
> It means Docker images were not built into Minikube's cache.
> Run `eval $(minikube docker-env)` and then re-run `./scripts/setup.sh`.

**Verify all pods are running:**

```bash
kubectl get pods
```

Expected output (all should say `Running`):

```
NAME                                     READY   STATUS    RESTARTS   AGE
api-service-7d4b8c9f6-xk2p9             1/1     Running   0          2m
grafana-6f9d4b7c8-mn3q1                 1/1     Running   0          1m
predictive-autoscaler-5c8b7d6f4-lp8r2   1/1     Running   0          1m
prometheus-8d5c6b4f7-wz9k4              1/1     Running   0          2m
```

If any pod says `Pending` or `CrashLoopBackOff`, see the
[Troubleshooting](#13-troubleshooting) section.

---

### Open the Dashboards

The setup script printed URLs at the end. If you missed them, run:

```bash
# Get all service URLs
minikube service api-service --url
minikube service grafana --url

# Prometheus needs a port-forward (it has no NodePort in the k8s setup)
# Run this in a separate terminal and leave it running:
kubectl port-forward svc/prometheus 9090:9090
```

Or use the convenience script that opens all forwards at once:

```bash
# Run in a separate terminal and leave it running
./scripts/port-forward.sh
```

| Service | URL | Notes |
|---------|-----|-------|
| **Grafana** | `minikube service grafana --url` | Main dashboard |
| **API service** | `minikube service api-service --url` | Base URL for load test |
| **Prometheus** | http://localhost:9090 | Needs port-forward running |

**In Grafana:**
1. Go to the URL from `minikube service grafana --url`
2. Click ☰ → **Dashboards** → **Predictive Autoscaler**
3. The dashboard auto-refreshes every 5 seconds

---

### Run the Load Test

```bash
./scripts/run-load-test.sh
```

This script automatically gets the Minikube service URL and starts Locust.

Then open **http://localhost:8089** and set:
- **Number of users**: `50`
- **Spawn rate**: `5`

Click **Start swarming**.

---

### Watch What Happens

Open three windows side by side:

**Window 1 — Grafana dashboard** (http://localhost:3000 or minikube URL)

Watch the "Actual vs Predicted Request Rate" panel. The dashed orange line
(predicted) should start rising **before** the solid line (actual) during ramp-up.

**Window 2 — Pod count (live terminal)**

```bash
# Watch pod count update every 2 seconds
watch -n 2 kubectl get pods
```

You will see something like this as the autoscaler fires:

```
# Before load test:
NAME                                     READY   STATUS    RESTARTS   AGE
api-service-7d4b8c9f6-xk2p9             1/1     Running   0          5m

# ~2 minutes after starting load test (autoscaler detected rising trend):
NAME                                     READY   STATUS    RESTARTS   AGE
api-service-7d4b8c9f6-xk2p9             1/1     Running   0          7m
api-service-7d4b8c9f6-ab3c4             1/1     Running   0          15s
api-service-7d4b8c9f6-de5f6             1/1     Running   0          15s
```

**Window 3 — Autoscaler logs (live)**

```bash
kubectl logs -f deployment/predictive-autoscaler
```

You will see the decision log every 60 seconds:

```
2024-01-15T10:02:00 [INFO] autoscaler — Fetched 240 data points (current RPS: 87.3)
2024-01-15T10:02:00 [INFO] autoscaler — Decision: SCALE | predicted=423.1 RPS | current=1 pods | target=3 pods
2024-01-15T10:02:00 [INFO] autoscaler — Reason: Scale UP: predicted 423.1 RPS requires 3 pods (current: 1, capacity: 150 RPS)
2024-01-15T10:02:00 [INFO] autoscaler — Patched default/api-service → 3 replicas
```

---

### Watch Pods Scale in Real Time

To see the full demo lifecycle, increase the load sharply after 3 minutes:

1. In Locust (http://localhost:8089) click **Edit** → set users to `200` → **Update**
2. Wait 60 seconds (one autoscaler cycle)
3. Watch `kubectl get pods` — you should see new pods appear
4. In Locust, click **Stop** to drop traffic to zero
5. Wait 10+ minutes — watch pods scale back down (the cooldown is 10 minutes)

**The expected timeline:**

```
t=0:00  Load test starts — 50 users
t=0:00  Pods: 1
t=1:00  Autoscaler cycle 1: predicts rise, may scale to 2
t=2:00  Autoscaler cycle 2: predicts higher, scales to 3–4
t=3:00  Traffic fully ramped — pods already ready, no latency spike
t=5:00  Increase to 200 users in Locust
t=6:00  Autoscaler scales to 4–5 pods
t=7:00  Stop load test in Locust
t=7:00  Pods: still 4–5 (cooldown protects against immediate scale-down)
t=17:00 Cooldown elapsed — autoscaler scales back to 1 pod
```

---

### Stop Everything

```bash
# Remove all Kubernetes resources
./scripts/teardown.sh

# Also stop Minikube:
./scripts/teardown.sh --stop

# Or just stop Minikube (keeps resources, faster to restart):
minikube stop
```

---

## 9. Running the Tests

The project has unit tests and integration tests. They run without any
running services — everything is mocked.

**Install test dependencies:**

```bash
# Create a virtual environment (keeps dependencies isolated)
python3 -m venv venv
source venv/bin/activate       # macOS / Linux
# venv\Scripts\activate        # Windows

# Install all autoscaler dependencies
pip install -r autoscaler/requirements.txt

# Install test runner
pip install pytest==8.1.1
```

**Run all tests:**

```bash
pytest
```

**Expected output:**

```
=================== test session starts ====================
platform linux -- Python 3.11.8
collected 32 items

tests/unit/test_forecaster.py::TestForecasterNormal::test_returns_forecast_result PASSED
tests/unit/test_forecaster.py::TestForecasterNormal::test_peak_is_non_negative PASSED
tests/unit/test_forecaster.py::TestForecasterNormal::test_forecast_horizon_length PASSED
tests/unit/test_forecaster.py::TestForecasterNormal::test_stable_traffic_predicts_similar_value PASSED
tests/unit/test_forecaster.py::TestForecasterNormal::test_rising_trend_predicts_higher_than_current PASSED
tests/unit/test_forecaster.py::TestForecasterEdgeCases::test_all_zeros_does_not_crash PASSED
...
tests/unit/test_scaler.py::TestScaleUp::test_scale_up_when_predicted_exceeds_capacity PASSED
tests/unit/test_scaler.py::TestScaleDown::test_scale_down_blocked_by_cooldown PASSED
...
tests/integration/test_autoscaler_loop.py::TestPreSpike::test_scale_up_before_spike PASSED
...

=================== 32 passed in 4.23s ====================
```

All 32 tests should pass. If any fail, check that you installed the
dependencies correctly.

**Run only unit tests:**

```bash
pytest tests/unit/
```

**Run only a specific test file:**

```bash
pytest tests/unit/test_forecaster.py -v
```

**Run with detailed output (useful for understanding what each test does):**

```bash
pytest -v --tb=long
```

---

## 10. Understanding the Grafana Dashboard

The dashboard has three rows of panels.

---

### Row 1 — Traffic

**Panel: "Actual vs Predicted Request Rate"** (the most important one)

```
Y axis: requests per second (RPS)
X axis: time

Solid line   = actual incoming requests right now (from Prometheus)
Dashed line  = what the autoscaler predicted 10 minutes ago

If the dashed line rises BEFORE the solid line →
the autoscaler correctly anticipated the spike.
```

**Panel: "Pod Count — Current vs Target"**

```
Green line  = current number of running pods
Orange line = the number of pods the autoscaler wants

When they diverge → a scaling event is about to happen or is in progress.
```

---

### Row 2 — Latency

**Panel: "Request Latency Percentiles"**

```
p50 = 50% of requests are faster than this   (median)
p95 = 95% of requests are faster than this   (good SLA target)
p99 = 99% of requests are faster than this   (tail latency)

During a spike with reactive autoscaling: p95 and p99 shoot up
During a spike with predictive autoscaling: p95 and p99 stay flat
```

**Panel: "Inflight Requests"**

Shows how many requests are being processed simultaneously. Spikes here mean
the service is under pressure.

---

### Row 3 — System

Shows CPU usage, memory usage, and a count of scale-up / scale-down events
over the last 10 minutes.

---

### Changing the Time Window

The default window is the last 30 minutes. To zoom in on the spike:

1. Click the time range selector in the top right (shows "Last 30 minutes")
2. Select "Last 5 minutes" to see just the spike period up close
3. Or drag to select a region on any graph to zoom in

---

## 11. Understanding the Autoscaler Logs

Every 60 seconds the autoscaler prints a structured log line. Here is how to
read it:

```
[autoscaler] Fetched 240 data points (current RPS: 87.3)
```
→ Successfully got 20 minutes of data from Prometheus (240 points at 5s intervals)

```
[autoscaler] Decision: SCALE | predicted=423.1 RPS | current=1 pods | target=3 pods
```
→ The model predicted 423 RPS, current capacity (1 pod × 150) is 150 RPS,
  so 3 pods are needed

```
[autoscaler] Reason: Scale UP: predicted 423.1 RPS requires 3 pods (current: 1, capacity: 150 RPS)
```
→ Human-readable explanation of the decision

```
[autoscaler] Patched default/api-service → 3 replicas
```
→ Successfully told Kubernetes to scale

**Other log messages you may see:**

```
Decision: HOLD | ...
Reason: Hold: in scale-down cooldown for another 423s
```
→ Traffic has dropped but the 10-minute cooldown has not elapsed yet

```
Decision: HOLD | ...
Reason: Hold: predicted utilisation 65% is above scale-down threshold 60%
```
→ Traffic dropped but not enough to justify scaling down (still above 60% capacity)

```
WARNING — Forecast used fallback heuristic: Only 18 data points (need >= 24)
```
→ Not enough history yet (first 2 minutes after startup). Using the last
  observed maximum as a conservative estimate instead.

---

## 12. Tuning and Experimenting

All autoscaler settings are environment variables. You can change them without
rebuilding any images.

### In Docker Compose

Edit `docker-compose.yaml` and find the `autoscaler` service's `environment` block:

```yaml
autoscaler:
  environment:
    POD_CAPACITY_RPS: "150"      # ← change this to make scaling more/less aggressive
    LOOP_INTERVAL_SECONDS: "60"  # ← change to 30 for faster reactions
    COOLDOWN_SECONDS: "600"      # ← change to 120 to see faster scale-down
```

Then restart just the autoscaler:
```bash
docker compose up -d autoscaler
```

### In Kubernetes (Mode B)

Edit `k8s/autoscaler/deployment.yaml` and find the `env` block. Change any value,
then apply:

```bash
kubectl apply -f k8s/autoscaler/deployment.yaml
kubectl rollout restart deployment/predictive-autoscaler
```

---

### Interesting Experiments to Try

**Experiment 1 — Make it scale faster**

Change `LOOP_INTERVAL_SECONDS` from `60` to `15`. The autoscaler will now check
every 15 seconds instead of every minute. You will see much more frequent
log output and faster reactions.

**Experiment 2 — Adjust pod capacity**

Change `POD_CAPACITY_RPS` from `150` to `50`. Now the autoscaler thinks each
pod can only handle 50 RPS. At 300 RPS it will scale to 6 pods instead of 2.
This lets you see larger scaling events with modest traffic.

**Experiment 3 — Disable the cooldown**

Change `COOLDOWN_SECONDS` from `600` to `30`. Stop the load test and watch
pods scale down within 30 seconds. Then restart the load test and watch them
scale back up. This shows the "thrashing" problem that the cooldown prevents.

**Experiment 4 — Aggressive spike**

In Locust, use the StagesShape mode (headless, no browser):
```bash
locust -f load-generator/locustfile.py \
  --host=http://localhost:8000 \
  --headless \
  --run-time=10m
```
This runs the pre-programmed 3-phase pattern automatically (50 RPS → 500 RPS → 150 RPS).

---

## 13. Troubleshooting

### Docker Compose Issues

**Problem:** `docker compose up` fails with "port already in use"
```
Error: bind: address already in use (port 3000 or 9090 or 8000)
```
**Fix:** Something else is using that port. Find and stop it:
```bash
# Find what's using port 3000
lsof -i :3000
# Kill it (replace PID with the number shown)
kill -9 <PID>
```

---

**Problem:** Grafana shows "No data" on all panels
```
No data
```
**Fix:** Prometheus has not scraped enough data yet. Wait 1–2 minutes after
starting the load test, then check Prometheus is running:
```bash
# Docker Compose:
docker compose ps
# All four should show "running"
```
If Prometheus is not running: `docker compose up -d prometheus`

---

**Problem:** `docker compose up --build` hangs for more than 10 minutes

**Fix:** Your internet connection may be slow pulling base images. Check
Docker Desktop is not paused and has disk space:
```bash
docker system df
```
If disk usage is over 90%, free space:
```bash
docker system prune -f
```

---

### Minikube Issues

**Problem:** `minikube start` fails with "Exiting due to PROVIDER_DOCKER_ERROR"
```
Exiting due to PROVIDER_DOCKER_ERROR: Failed to start docker container
```
**Fix:** Docker Desktop is not running. Open Docker Desktop and wait for the
whale icon in the menu bar to stop animating.

---

**Problem:** Pod is stuck in `Pending` status
```bash
kubectl get pods
# NAME                       READY   STATUS    RESTARTS   AGE
# api-service-xxx            0/1     Pending   0          5m
```
**Fix:** Not enough resources. Check what is wrong:
```bash
kubectl describe pod <pod-name>
# Look for "Events:" at the bottom — it will say why the pod is Pending
```
Common cause: Minikube started with too little memory. Restart with more:
```bash
minikube stop
minikube start --cpus=4 --memory=8192 --driver=docker
```

---

**Problem:** Pod is in `ErrImageNeverPull` or `ImagePullBackOff`
```
api-service   0/1   ErrImageNeverPull   0   2m
```
**Fix:** The image was not built inside Minikube's Docker daemon. Run:
```bash
eval $(minikube docker-env)
docker build -t api-service:latest ./app
docker build -t predictive-autoscaler:latest ./autoscaler
kubectl rollout restart deployment/api-service
kubectl rollout restart deployment/predictive-autoscaler
```

---

**Problem:** `./scripts/setup.sh` fails with "Permission denied"
```
bash: ./scripts/setup.sh: Permission denied
```
**Fix:**
```bash
chmod +x scripts/setup.sh scripts/teardown.sh scripts/port-forward.sh scripts/run-load-test.sh
./scripts/setup.sh
```

---

**Problem:** Autoscaler logs show "Prometheus unreachable"
```
WARNING — Prometheus unreachable: ConnectionRefusedError
```
**Fix:** Prometheus is not running or the URL is wrong. Check:
```bash
# In Kubernetes:
kubectl get pods | grep prometheus
# Should show 1/1 Running

kubectl logs deployment/prometheus | tail -20
# Look for errors

# Verify the autoscaler can reach Prometheus
kubectl exec deployment/predictive-autoscaler -- \
  curl -s http://prometheus:9090/-/healthy
# Should return "Prometheus Server is Healthy."
```

---

**Problem:** `minikube service grafana --url` returns nothing or an error

**Fix:**
```bash
kubectl get svc grafana
# If it doesn't exist, Grafana was not deployed:
kubectl apply -f k8s/grafana/deployment.yaml
kubectl apply -f k8s/grafana/service.yaml
```

---

**Problem:** Tests fail with `ModuleNotFoundError: No module named 'autoscaler'`

**Fix:** You need to run pytest from the project root and with the venv activated:
```bash
cd predictive-autoscaler   # make sure you're in the project root
source venv/bin/activate
pip install -r autoscaler/requirements.txt
pytest
```

---

**Problem:** Locust says "ConnectionRefusedError" when starting the load test

**Fix:** The API service is not reachable. Check the URL:
```bash
# Docker Compose — should be:
locust -f load-generator/locustfile.py --host=http://localhost:8000

# Minikube — URL changes each time:
locust -f load-generator/locustfile.py --host=$(minikube service api-service --url)
```

---

## 14. What Each File Does — Quick Reference

```
predictive-autoscaler/
│
├── app/                        THE API SERVICE
│   ├── main.py                 FastAPI app — mounts /metrics, starts background threads
│   ├── metrics.py              All Prometheus metrics defined here (counters, histograms, gauges)
│   ├── routers/api.py          Three routes: /ping, /process, /status
│   ├── requirements.txt        Python dependencies: fastapi, uvicorn, prometheus-client
│   └── Dockerfile              Builds the api-service container image
│
├── autoscaler/                 THE BRAIN — reads metrics, forecasts, scales
│   ├── main.py                 Control loop (runs every 60s), exposes self-metrics on :9091
│   ├── config.py               All settings as env vars with defaults — change these to tune
│   ├── prometheus_client.py    Fetches request rate time-series from Prometheus via HTTP
│   ├── forecaster.py           Holt-Winters model — takes history, returns predicted peak RPS
│   ├── scaler.py               Pure logic — takes predicted RPS, returns target pod count
│   ├── k8s_client.py           Kubernetes API wrapper — reads + patches deployment replicas
│   ├── requirements.txt        Python deps: kubernetes, statsmodels, pandas, numpy
│   └── Dockerfile              Builds the autoscaler container image
│
├── load-generator/             TRAFFIC SIMULATION
│   ├── locustfile.py           Locust test — 3-phase traffic (baseline→spike→cooldown)
│   └── k6-script.js            k6 alternative with same traffic profile
│
├── k8s/                        KUBERNETES MANIFESTS
│   ├── app/                    API service Deployment + Service (NodePort 30800)
│   ├── autoscaler/             Autoscaler Deployment + RBAC (ServiceAccount, Role, Binding)
│   ├── prometheus/             Prometheus Deployment + Service + ConfigMap (scrape config)
│   ├── grafana/                Grafana Deployment + Service + dashboard auto-provisioning
│   └── load-generator/         Kubernetes Job to run Locust inside the cluster
│
├── tests/
│   ├── unit/
│   │   ├── test_forecaster.py        Tests the Holt-Winters model in isolation
│   │   ├── test_scaler.py            Tests scale-up/down/hold decisions in isolation
│   │   └── test_prometheus_client.py Tests HTTP parsing with mocked Prometheus responses
│   └── integration/
│       └── test_autoscaler_loop.py   Tests the full pipeline with mocked K8s + Prometheus
│
├── scripts/
│   ├── setup.sh                One-shot: start Minikube + build images + deploy everything
│   ├── teardown.sh             Remove all Kubernetes resources (--stop also kills Minikube)
│   ├── port-forward.sh         Background port-forwards for Prometheus + Grafana + metrics
│   └── run-load-test.sh        Auto-detect Minikube URL + start Locust
│
├── docs/
│   ├── forecasting-model.md    Why Holt-Winters, how seasonal periods work, limitations
│   └── scaling-algorithm.md    Pod sizing formula, scale-up/down rules, example walkthrough
│
├── docker-compose.yaml         Run everything without Kubernetes (Mode A)
├── docker/prometheus.yml       Prometheus scrape config for Docker Compose mode
└── pytest.ini                  Test runner configuration
```

---

## Quick Command Reference

```bash
# ── Docker Compose (Mode A) ──────────────────────────────────
docker compose up --build          # Start everything
docker compose down                # Stop everything
docker compose logs -f autoscaler  # Watch autoscaler logs
docker compose ps                  # Check all containers are running

# ── Minikube (Mode B) ────────────────────────────────────────
minikube start --cpus=4 --memory=8192 --driver=docker
./scripts/setup.sh                 # Build + deploy everything
./scripts/teardown.sh              # Remove all resources
./scripts/teardown.sh --stop       # Remove + stop Minikube
./scripts/port-forward.sh          # Open all port-forwards

# ── kubectl (Mode B) ─────────────────────────────────────────
kubectl get pods                            # See all pods + status
kubectl get pods -w                         # Watch pods update live
kubectl logs -f deployment/predictive-autoscaler  # Autoscaler logs live
kubectl logs -f deployment/api-service      # API service logs
kubectl describe pod <name>                 # Debug a specific pod
kubectl get events --sort-by=.lastTimestamp # Recent cluster events

# ── Load Test ────────────────────────────────────────────────
pip install locust==2.24.1
locust -f load-generator/locustfile.py --host=http://localhost:8000
# Then open http://localhost:8089

# ── Tests ────────────────────────────────────────────────────
pip install pytest
pytest                        # Run all 32 tests
pytest tests/unit/            # Unit tests only
pytest -v                     # Verbose output

# ── Useful one-liners ────────────────────────────────────────
# Get Minikube service URLs
minikube service list

# Reload Prometheus config without restarting
curl -X POST http://localhost:9090/-/reload

# Force autoscaler to restart and pick up config changes
kubectl rollout restart deployment/predictive-autoscaler

# Scale api-service manually (useful for testing)
kubectl scale deployment api-service --replicas=3
```

---

*If you get stuck, the most common fixes are:*
*1. Make sure Docker Desktop is running*
*2. Make sure you are in the project root directory (`ls` should show `app/`, `autoscaler/`, etc.)*
*3. For Minikube image issues, run `eval $(minikube docker-env)` before building*