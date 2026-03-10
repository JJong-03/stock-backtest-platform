# Operations Guide

> Operational procedures for the Stock Backtesting Platform.
> For architecture and design decisions, see `CLAUDE.md` (source of truth) and `RETROSPECTIVE.md`.

---

## Prometheus Metrics Verification

The web Service exposes application metrics at `/metrics`.
Prometheus scrapes this endpoint via a **ServiceMonitor** (`k8s/web-servicemonitor.yaml`).

Metrics scraping is cluster-internal only. `/metrics` is NOT exposed via Ingress.

### 1. Verify ServiceMonitor Resource

```bash
kubectl get servicemonitor web -n stock-backtest
```

Expected: the resource exists with `AGE` indicating it has been applied.

Inspect labels to confirm the `release` label is present:

```bash
kubectl get servicemonitor web -n stock-backtest --show-labels
```

Expected labels include `app=web` and `release=kube-prometheus-stack`.

### 2. Verify Service Labels Match ServiceMonitor Selector

The ServiceMonitor selects Services with `app: web`. Confirm the web Service has this label:

```bash
kubectl get svc web -n stock-backtest --show-labels
```

Expected: `app=web` label is present.

### 3. Verify Service Port Name

The ServiceMonitor references port `http` by name. Confirm the Service defines this port:

```bash
kubectl get svc web -n stock-backtest -o jsonpath='{.spec.ports[0].name}'
```

Expected output: `http`

### 4. Verify Prometheus Target Discovery

Port-forward to the Prometheus UI:

```bash
kubectl port-forward svc/<prometheus-service-name> 9090:9090 -n <monitoring-namespace>
```

> **Note:** Prometheus is typically installed in a namespace such as `monitoring`.
> The exact Prometheus service name and namespace depend on the installation method.
> For kube-prometheus-stack, the service is commonly named
> `kube-prometheus-stack-prometheus` in the `monitoring` namespace.

Open `http://localhost:9090/targets` in a browser.

Look for a target matching `serviceMonitor/stock-backtest/web`.
The target status should be **UP**.

### 5. Verify Metrics with PromQL Queries

Navigate to `http://localhost:9090/graph` and run the following queries:

**Request rate (QPS):**

```promql
rate(http_requests_total[5m])
```

**Backtest request rate by rule type:**

```promql
rate(backtest_requests_total[5m])
```

**Average request latency:**

> **Note on histogram metrics:** `http_request_duration_seconds` is registered as a Prometheus
> **Histogram**. The Prometheus client library automatically exposes three sub-series:
> `_bucket` (distribution buckets for `histogram_quantile()`),
> `_sum` (total accumulated duration), and
> `_count` (total number of observations).
> The latency queries below rely on these sub-series.

```promql
sum(rate(http_request_duration_seconds_sum[5m]))
/
sum(rate(http_request_duration_seconds_count[5m]))
```

**Latency histogram (for Grafana heatmaps or histogram_quantile):**

```promql
rate(http_request_duration_seconds_bucket[5m])
```

**5xx error rate:**

```promql
rate(http_requests_total{status=~"5.."}[5m])
```

**Job launch success/failure:**

```promql
rate(job_launch_success_total[5m])
rate(job_launch_failure_total[5m])
```

### 6. Direct Endpoint Verification

To verify the `/metrics` endpoint is responding from within the cluster:

```bash
kubectl run curl-test --rm -it --image=curlimages/curl -- \
  curl -s http://web.stock-backtest.svc.cluster.local/metrics | head -20
```

Expected: Prometheus text format output with metric names such as
`http_requests_total`, `backtest_requests_total`, `http_request_duration_seconds_bucket`.

### Troubleshooting

If the target does not appear in Prometheus:

1. **ServiceMonitor missing:** Verify it exists with `kubectl get servicemonitor web -n stock-backtest`.
2. **Label mismatch:** Verify the Service has `app: web` label matching the ServiceMonitor selector.
3. **Namespace not watched:** Ensure the Prometheus instance is configured to watch the `stock-backtest` namespace via `serviceMonitorNamespaceSelector`.
4. **Release label mismatch:** The ServiceMonitor's `release` label must match the Prometheus Operator's `serviceMonitorSelector`. For kube-prometheus-stack, this defaults to the Helm release name. Check with:
   ```bash
   kubectl get prometheus -n <monitoring-namespace> -o jsonpath='{.items[0].spec.serviceMonitorSelector}'
   ```
5. **Port name mismatch:** Confirm the ServiceMonitor `port: http` matches the Service port name exactly.
6. **Pod not ready:** Ensure the web Pod is Running and Ready (`kubectl get pods -l app=web -n stock-backtest`).
