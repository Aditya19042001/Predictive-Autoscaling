# Architecture Deep-Dive

## Why an Independent Service?

The autoscaler runs as a completely separate Kubernetes Deployment from
the application it manages. This is the most important architectural decision.

Consequences of this choice:
- The autoscaler can crash, restart, or be updated without touching api-service
- The forecasting model can be iterated on independently (different release cycle)
- Multiple deployments could be managed by a single autoscaler instance
  (add a target list to Config)
- The autoscaler's own metrics are scrape-able independently

## Control Loop Design

The loop is synchronous and single-threaded. Each iteration:

  1. Blocks on Prometheus HTTP (timeout: 10s)
  2. Fits the Holt-Winters model in-process (< 50ms for 240 points)
  3. Blocks on Kubernetes PATCH API (timeout: 30s default)
  4. Sleeps for the remainder of the 60s interval

Why not async?
  - The loop wakes up once per minute. There is no benefit to async I/O
    when all three operations are sequential and the total wall time is
    well under 1 second.
  - Synchronous code is far easier to reason about in error scenarios.

## Holt-Winters Parameter Choices

seasonal_periods = 12 (12 × 5s scrapes = 1 minute season)

This means the model looks for repeating patterns with a 1-minute period.
HTTP traffic commonly has sub-minute bursts (e.g., scheduled jobs, batch
endpoints). If your traffic has longer seasonality (hourly, daily), increase
seasonal_periods accordingly — but you'll need more historical data.

initialization_method = "estimated"
  Statsmodels estimates initial level/trend/seasonal components from
  the data rather than requiring a burn-in period. This means the model
  starts making reasonable forecasts after just 2× seasonal_periods of data
  (24 points = 2 minutes at 5s scrape interval).

## RBAC Minimum Permissions

The autoscaler service account has exactly:
  GET/LIST on deployments          — to read current replica count
  PATCH/UPDATE on deployments/scale — to set new replica count
  GET/LIST on pods                  — optional, for observability logging

It does NOT have:
  - cluster-admin
  - Access to secrets
  - Access to other namespaces
  - Ability to create/delete resources

This follows the principle of least privilege. In production, scope the
ClusterRole to a Role (namespace-scoped) if the autoscaler only ever
manages one namespace.
