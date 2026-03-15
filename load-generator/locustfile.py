"""
locustfile.py
-------------
Locust load test that simulates the three-phase traffic pattern
described in the design doc:

  Phase 1 (0–3 min):   Low baseline  — 50 RPS
  Phase 2 (3–6 min):   Spike         — 500 RPS  ← autoscaler must pre-scale for this
  Phase 3 (6–10 min):  Cool-down     — 150 RPS

How phase-based traffic is achieved:
  Locust's --users and --spawn-rate are set from the CLI (or the web UI).
  This file implements the phase logic via a custom LoadTestShape class,
  which overrides user count at each tick — no manual CLI changes needed.

Running locally (against minikube):
  minikube service api-service --url   # prints the NodePort URL
  locust -f locustfile.py --host=http://<MINIKUBE_IP>:30800

Running headless (CI / k8s Job):
  locust -f locustfile.py --headless --host=http://api-service:8000
    --run-time=10m --users=500 --spawn-rate=50

Endpoints exercised:
  GET  /api/v1/ping     (80% of requests — lightweight, drives RPS counter)
  POST /api/v1/process  (20% of requests — CPU-bound, drives latency/CPU metrics)
  GET  /api/v1/status   (occasional — for human observers during demo)
"""

import random
from locust import HttpUser, task, between, LoadTestShape


# ---------------------------------------------------------------------------
# User behaviour
# ---------------------------------------------------------------------------

class APIUser(HttpUser):
    """
    Simulates a single virtual user hitting the API service.

    wait_time: between 50ms and 200ms between requests.
    At 500 concurrent users this gives roughly 2500–10000 RPS —
    well within the spike range we want to demonstrate.
    """
    wait_time = between(0.05, 0.2)

    @task(8)
    def ping(self):
        """
        Lightweight GET. Drives http_requests_total counter in Prometheus.
        High weight (8) so this dominates the RPS signal the autoscaler reads.
        """
        with self.client.get(
            "/api/v1/ping",
            name="/api/v1/ping",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(2)
    def process(self):
        """
        CPU-bound POST. Drives cpu_usage_percent and request_latency_seconds.
        complexity is randomised to create a realistic latency distribution.
        """
        complexity = random.choices([1, 2, 3, 5], weights=[40, 30, 20, 10])[0]
        with self.client.post(
            "/api/v1/process",
            json={
                "data": f"load-test-{random.randint(0, 9999)}",
                "item_type": random.choice(["typeA", "typeB", "typeC"]),
                "complexity": complexity,
            },
            name="/api/v1/process",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                pass
            elif resp.status_code == 429:
                resp.failure("Rate limited")
            else:
                resp.failure(f"Status {resp.status_code}: {resp.text[:80]}")

    @task(1)
    def status(self):
        """Low-frequency status check — useful to watch pod rotation during demo."""
        self.client.get("/api/v1/status", name="/api/v1/status")


# ---------------------------------------------------------------------------
# Traffic shape: three-phase load pattern
# ---------------------------------------------------------------------------

class ThreePhaseShape(LoadTestShape):
    """
    Defines the user-count over time to produce the three-phase pattern.

    tick() is called every second by Locust.
    Return (user_count, spawn_rate) to change the load, or None to stop.

    Phase timeline (matches design doc section 13):
      0 – 180s   : baseline    50  users → ~50  RPS
      180 – 360s : spike       500 users → ~500 RPS
      360 – 600s : cool-down   150 users → ~150 RPS
      600s+      : stop
    """

    stages = [
        {"duration": 180, "users": 50,  "spawn_rate": 10},   # baseline
        {"duration": 360, "users": 500, "spawn_rate": 50},   # spike
        {"duration": 600, "users": 150, "spawn_rate": 20},   # cool-down
    ]

    def tick(self):
        run_time = self.get_run_time()

        for stage in self.stages:
            if run_time < stage["duration"]:
                return stage["users"], stage["spawn_rate"]

        return None   # stop after all stages complete
