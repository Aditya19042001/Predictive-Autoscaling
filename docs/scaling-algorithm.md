# Scaling Algorithm Reference

## Pod Sizing Formula

  pods_required = ceil(predicted_peak_rps / pod_capacity_rps)

pod_capacity_rps should be measured empirically via load testing.
The recommended approach:
  1. Deploy a single pod of api-service
  2. Run k6 with a ramping arrival rate from 0 → 500 RPS
  3. Find the RPS at which p95 latency crosses your SLO threshold
  4. Set pod_capacity_rps to 80% of that value (safety margin)

## Scale-Up Decision

Fires immediately when pods_required > current_pods.
No cooldown. No threshold. Fast path always wins.

Rationale: the cost of an unnecessary extra pod for 10 minutes is trivial.
The cost of a 2-minute service degradation during a traffic spike is not.

## Scale-Down Guards

Two sequential guards must both pass before a scale-down executes:

Guard 1 — Utilisation threshold:
  predicted_rps < current_capacity × scale_down_threshold (default 0.6)

  Example: 4 pods × 150 RPS = 600 RPS capacity.
  Scale-down only triggers when predicted RPS < 360 (60% of 600).
  This prevents oscillation at the boundary.

Guard 2 — Cooldown window (default 600s):
  time_since_last_scale_down > cooldown_seconds

  Prevents rapid successive scale-downs if traffic is slowly declining.
  Scale-up always resets the cooldown (by implication — scale-up does NOT
  update _last_scale_down_at, only a completed scale-down does).

## Bounds

min_pods (default 1): Never scale to zero. A deployment with 0 pods
  has no readiness to serve even low baseline traffic.

max_pods (default 20): Hard ceiling to prevent runaway scaling from
  a bad forecast (e.g., Prometheus returns corrupted data with huge values).
  Set this to a value your cluster can actually schedule.
