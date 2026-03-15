/**
 * k6-script.js
 * ------------
 * k6 equivalent of the Locust three-phase traffic pattern.
 * Use this if you prefer a Go-based load tool with built-in thresholds.
 *
 * Run:
 *   k6 run --env BASE_URL=http://$(minikube ip):30800 k6-script.js
 *
 * The `scenarios` block drives the same three phases as locustfile.py.
 * SLO thresholds are defined at the bottom — the run fails if p95 > 500ms
 * or error rate > 1%.
 */

import http from "k6/http";
import { check, sleep } from "k6";
import { Rate } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:30800";
const errorRate = new Rate("errors");

// ---------------------------------------------------------------------------
// Three-phase traffic shape
// ---------------------------------------------------------------------------

export const options = {
  scenarios: {
    baseline: {
      executor: "constant-arrival-rate",
      rate: 50,
      timeUnit: "1s",
      duration: "3m",
      preAllocatedVUs: 20,
      maxVUs: 100,
    },
    spike: {
      executor: "ramping-arrival-rate",
      startRate: 50,
      timeUnit: "1s",
      startTime: "3m",
      stages: [
        { target: 500, duration: "30s" },   // ramp up fast
        { target: 500, duration: "2m30s" }, // hold
      ],
      preAllocatedVUs: 100,
      maxVUs: 600,
    },
    cooldown: {
      executor: "constant-arrival-rate",
      rate: 150,
      timeUnit: "1s",
      startTime: "6m",
      duration: "4m",
      preAllocatedVUs: 50,
      maxVUs: 200,
    },
  },

  // SLO thresholds — CI fails if these are breached
  thresholds: {
    http_req_duration: ["p(95)<500"],    // p95 latency under 500ms
    errors: ["rate<0.01"],               // error rate under 1%
    http_req_failed: ["rate<0.01"],
  },
};

// ---------------------------------------------------------------------------
// Virtual user behaviour (mirrors Locust tasks)
// ---------------------------------------------------------------------------

export default function () {
  const roll = Math.random();

  if (roll < 0.8) {
    // 80%: lightweight ping
    const res = http.get(`${BASE_URL}/api/v1/ping`);
    errorRate.add(res.status !== 200);
    check(res, { "ping 200": (r) => r.status === 200 });

  } else if (roll < 0.95) {
    // 15%: CPU-bound process
    const payload = JSON.stringify({
      data: `load-test-${Math.floor(Math.random() * 10000)}`,
      item_type: ["typeA", "typeB", "typeC"][Math.floor(Math.random() * 3)],
      complexity: [1, 2, 3, 5][Math.floor(Math.random() * 4)],
    });
    const res = http.post(`${BASE_URL}/api/v1/process`, payload, {
      headers: { "Content-Type": "application/json" },
    });
    errorRate.add(res.status !== 200);
    check(res, { "process 200": (r) => r.status === 200 });

  } else {
    // 5%: status check
    http.get(`${BASE_URL}/api/v1/status`);
  }

  sleep(Math.random() * 0.15);
}
