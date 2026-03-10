"""Prometheus metrics instrumentation for the Flask web application.

Exposes application-level metrics via /metrics endpoint (Section 12, CLAUDE.md).
All metrics are in-memory only — no filesystem writes (Rule 4 compliant).

Gunicorn multiprocess limitation:
    This implementation uses the default in-process Prometheus registry.
    Each Gunicorn worker maintains its own counters and histograms in memory.
    When Prometheus scrapes /metrics, it reaches one worker at a time, so
    metrics reflect that single worker's observations only.

    For accurate aggregation across multiple Gunicorn workers, configure
    PROMETHEUS_MULTIPROC_DIR and use prometheus_client.MultiProcessCollector.
    That filesystem-based multiprocess mode is NOT configured in this task.
"""

from __future__ import annotations

import logging
import time

from flask import Flask, Response, request
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metric definitions (initialized once at import time)
# ---------------------------------------------------------------------------

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests by method, endpoint, and status code",
    ["method", "endpoint", "status"],
)

HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "Duration of HTTP requests",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

BACKTEST_REQUESTS_TOTAL = Counter(
    "backtest_requests_total",
    "Backtest submissions by rule type and outcome",
    ["rule_type", "outcome"],
)

JOB_LAUNCH_SUCCESS_TOTAL = Counter(
    "job_launch_success_total",
    "Successful K8s Job creations by rule type",
    ["rule_type"],
)

JOB_LAUNCH_FAILURE_TOTAL = Counter(
    "job_launch_failure_total",
    "Failed K8s Job creation attempts by rule type",
    ["rule_type"],
)

# ---------------------------------------------------------------------------
# Request attribute constants — used with setattr/getattr on flask.request
# ---------------------------------------------------------------------------
_REQUEST_START_TIME_ATTR = "_prom_start_time"
_REQUEST_RECORDED_ATTR = "_prom_recorded"

# ---------------------------------------------------------------------------
# Known rule_type values for label cardinality bounding
# ---------------------------------------------------------------------------
_KNOWN_RULE_TYPES = frozenset({"RSI", "MACD", "RSI_MACD"})


def sanitize_rule_type(raw_value: str | None) -> str:
    """Normalize rule_type to a bounded set of known values.

    Returns the uppercase rule_type if it matches a known value,
    otherwise returns "unknown". This prevents unbounded label
    cardinality from raw user input.
    """
    if raw_value is None:
        return "unknown"
    normalized = str(raw_value).strip().upper()
    if normalized in _KNOWN_RULE_TYPES:
        return normalized
    return "unknown"


def _is_metrics_path() -> bool:
    """Check if the current request targets the /metrics endpoint.

    Handles optional trailing slash to avoid instrumentation gaps.
    """
    return request.path.rstrip("/") == "/metrics"


def _get_endpoint_label() -> str:
    """Return normalized endpoint label using Flask route template.

    Uses request.url_rule (the matched route pattern) to avoid
    high-cardinality labels from resolved paths like /status/<uuid>.
    Returns 'unmatched_route' for 404s where no rule matched.
    """
    if request.url_rule is not None:
        return request.url_rule.rule
    return "unmatched_route"


def init_metrics(app: Flask) -> None:
    """Register metrics hooks and /metrics endpoint on the Flask app."""

    # NOTE: The /metrics endpoint exposes operational data (counters,
    # histograms) and should be restricted at the ingress or network
    # policy layer. External access must not be allowed in production.
    # Authentication is not implemented here; access control is an
    # infrastructure concern handled via K8s NetworkPolicy or Ingress rules.
    @app.route("/metrics")
    def metrics_endpoint():
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

    @app.before_request
    def _before_request():
        if _is_metrics_path():
            return
        setattr(request, _REQUEST_START_TIME_ATTR, time.monotonic())

    @app.after_request
    def _after_request(response):
        if _is_metrics_path():
            return response

        start = getattr(request, _REQUEST_START_TIME_ATTR, None)
        endpoint = _get_endpoint_label()
        method = request.method
        status = str(response.status_code)

        HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status=status).inc()

        if start is not None:
            duration = time.monotonic() - start
            HTTP_REQUEST_DURATION.labels(method=method, endpoint=endpoint).observe(duration)

        # Mark as recorded so teardown_request doesn't double-count
        setattr(request, _REQUEST_RECORDED_ATTR, True)

        return response

    @app.teardown_request
    def _teardown_request(exc):
        """Last-resort fallback for metric recording.

        Flask's after_request hook runs for most responses, including
        normal 500 error responses returned by error handlers. This
        teardown fallback covers rare edge cases where after_request
        did not execute or failed to record metrics (e.g., an exception
        raised inside after_request itself, or a WSGI-level failure
        before Flask could build a response). Assumes status=500.
        """
        if _is_metrics_path():
            return
        if getattr(request, _REQUEST_RECORDED_ATTR, False):
            return

        logger.warning("teardown_request metrics fallback triggered")

        start = getattr(request, _REQUEST_START_TIME_ATTR, None)
        endpoint = _get_endpoint_label()
        method = request.method

        HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status="500").inc()

        if start is not None:
            duration = time.monotonic() - start
            HTTP_REQUEST_DURATION.labels(method=method, endpoint=endpoint).observe(duration)
