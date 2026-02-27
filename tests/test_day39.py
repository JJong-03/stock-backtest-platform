"""
Day 3.9 Tests: Extended API Schema and Adapter Layer
Updated for Phase 3: Web → K8s Job Orchestration

Phase 3 Web API contract:
- POST /run_backtest (valid)  → 202 {run_id, status:"PENDING", started_at:null, completed_at:null, error_message:null}
- POST /run_backtest (user_error) → 400 {run_id, status:"FAILED", ..., error_message:"..."}
- POST /run_backtest (system_error) → 500 {run_id, status:"FAILED", ..., error_message:"..."}
- GET  /status/<run_id>       → 200 {run_id, status, started_at, completed_at, error_message}
- GET  /status/<run_id> 404   → 404 {error:"Run not found"}
- GET  /health                → 200 {status:"ok"}

IMPORTANT: System errors are simulated via monkeypatch/mock only.
No application code modifications for error simulation.
"""

import pytest
import json
import uuid
import matplotlib
matplotlib.use("Agg")  # Rule 5: must precede pyplot import
import matplotlib.pyplot as plt
from unittest.mock import patch, MagicMock
import pandas as pd

# Adapter layer tests (can run without Flask app context)
from adapters.adapter import (
    derive_drawdown_curve,
    normalize_trades,
    safe_iso8601_utc,
    build_equity_curve,
    render_drawdown_chart,
    render_orders_chart,
    render_trade_pnl_chart,
    render_cumulative_return_chart,
)


# ═══════════════════════════════════════════════════════════════
# ADAPTER LAYER TESTS
# ═══════════════════════════════════════════════════════════════

class TestDeriveDrawdownCurve:
    """Test drawdown curve derivation from equity curve.

    SPECIFICATION (AUTHORITATIVE):
    Drawdown values are NON-POSITIVE (<= 0.0).
    - A value of 0.0 is valid and EXPECTED at new equity peaks.
    - Negative values represent drawdowns below the peak.
    """

    def test_empty_equity_curve(self):
        """Empty input returns empty output."""
        result = derive_drawdown_curve([])
        assert result == []

    def test_single_point(self):
        """Single data point has zero drawdown (it is its own peak)."""
        equity = [{"date": "2020-01-01", "equity": 100000}]
        result = derive_drawdown_curve(equity)
        # Anti-false-confidence: verify we have data to check
        assert len(result) == 1
        assert result[0]["date"] == "2020-01-01"
        # At peak, drawdown is exactly 0.0
        assert result[0]["drawdown_pct"] == 0.0

    def test_monotonic_increasing_no_drawdown(self):
        """Monotonically increasing equity has zero drawdown throughout.

        Each point is a new peak, so drawdown = 0.0 at every point.
        """
        equity = [
            {"date": "2020-01-01", "equity": 100000},
            {"date": "2020-01-02", "equity": 101000},
            {"date": "2020-01-03", "equity": 102000},
            {"date": "2020-01-04", "equity": 103000},
        ]
        result = derive_drawdown_curve(equity)

        # Anti-false-confidence: verify list is non-empty before loop
        assert len(result) == 4, "Expected 4 drawdown points"
        for point in result:
            # All points are peaks, so drawdown is exactly 0.0
            assert point["drawdown_pct"] == 0.0

    def test_mixed_up_down_equity(self):
        """Mixed equity correctly computes drawdown percentages."""
        equity = [
            {"date": "2020-01-01", "equity": 100000},  # Peak = 100000, DD = 0
            {"date": "2020-01-02", "equity": 110000},  # Peak = 110000, DD = 0
            {"date": "2020-01-03", "equity": 99000},   # Peak = 110000, DD = -10%
            {"date": "2020-01-04", "equity": 105000},  # Peak = 110000, DD = -4.55%
            {"date": "2020-01-05", "equity": 115000},  # Peak = 115000, DD = 0
        ]
        result = derive_drawdown_curve(equity)

        # Anti-false-confidence: verify list is non-empty
        assert len(result) == 5, "Expected 5 drawdown points"
        # Peaks have exactly 0.0 drawdown
        assert result[0]["drawdown_pct"] == 0.0
        assert result[1]["drawdown_pct"] == 0.0
        # Below peak: negative drawdown
        assert result[2]["drawdown_pct"] == pytest.approx(-10.0, abs=0.01)
        assert result[3]["drawdown_pct"] == pytest.approx(-4.55, abs=0.01)
        # New peak: exactly 0.0 drawdown
        assert result[4]["drawdown_pct"] == 0.0

    def test_continuous_decline(self):
        """Continuous decline shows increasing drawdown magnitude."""
        equity = [
            {"date": "2020-01-01", "equity": 100000},
            {"date": "2020-01-02", "equity": 90000},   # -10%
            {"date": "2020-01-03", "equity": 80000},   # -20%
            {"date": "2020-01-04", "equity": 70000},   # -30%
        ]
        result = derive_drawdown_curve(equity)

        # Anti-false-confidence: verify list is non-empty
        assert len(result) == 4, "Expected 4 drawdown points"
        # First point is peak, exactly 0.0
        assert result[0]["drawdown_pct"] == 0.0
        # Subsequent points are below peak, negative values
        assert result[1]["drawdown_pct"] == pytest.approx(-10.0, abs=0.01)
        assert result[2]["drawdown_pct"] == pytest.approx(-20.0, abs=0.01)
        assert result[3]["drawdown_pct"] == pytest.approx(-30.0, abs=0.01)

    def test_no_division_by_zero(self):
        """Handles zero equity without division error."""
        equity = [
            {"date": "2020-01-01", "equity": 0},
            {"date": "2020-01-02", "equity": 100},
        ]
        # Should not raise ZeroDivisionError
        result = derive_drawdown_curve(equity)
        # Anti-false-confidence: verify list is non-empty
        assert len(result) == 2, "Expected 2 drawdown points"
        # When peak is 0, drawdown is 0 (edge case handling)
        assert result[0]["drawdown_pct"] == 0.0

    def test_drawdown_values_are_non_positive(self):
        """SPEC CORRECTION: Drawdown values are NON-POSITIVE (<= 0.0).

        This test verifies the corrected specification:
        - Values below peak are strictly negative (< 0)
        - Values at peak are exactly zero (== 0.0)
        """
        equity = [
            {"date": "2020-01-01", "equity": 100000},  # Peak
            {"date": "2020-01-02", "equity": 95000},   # 5% below peak
        ]
        result = derive_drawdown_curve(equity)

        # Anti-false-confidence: verify list is non-empty
        assert len(result) == 2, "Expected 2 drawdown points"

        # At peak: drawdown is exactly 0.0 (NON-POSITIVE, valid)
        assert result[0]["drawdown_pct"] == 0.0

        # Below peak: drawdown is strictly negative (NON-POSITIVE)
        assert result[1]["drawdown_pct"] <= 0, "Drawdown must be non-positive"
        assert result[1]["drawdown_pct"] == pytest.approx(-5.0, abs=0.01)

    def test_peak_produces_exactly_zero_drawdown(self):
        """EXPLICIT TEST: New equity peak produces drawdown_pct == 0.0 exactly.

        This is the authoritative test for the corrected specification.
        Zero drawdown at peaks is mathematically correct, not an error.
        """
        equity = [
            {"date": "2020-01-01", "equity": 100000},  # Initial peak
            {"date": "2020-01-02", "equity": 90000},   # Drawdown
            {"date": "2020-01-03", "equity": 110000},  # NEW PEAK
            {"date": "2020-01-04", "equity": 120000},  # NEW PEAK
        ]
        result = derive_drawdown_curve(equity)

        # Anti-false-confidence: verify list is non-empty
        assert len(result) == 4, "Expected 4 drawdown points"

        # Verify peaks have EXACTLY 0.0 drawdown
        assert result[0]["drawdown_pct"] == 0.0, "Initial peak must be 0.0"
        assert result[2]["drawdown_pct"] == 0.0, "New peak at day 3 must be 0.0"
        assert result[3]["drawdown_pct"] == 0.0, "New peak at day 4 must be 0.0"

        # Verify non-peak has negative drawdown
        assert result[1]["drawdown_pct"] < 0, "Below peak must be negative"
        assert result[1]["drawdown_pct"] == pytest.approx(-10.0, abs=0.01)

    def test_all_drawdown_values_are_non_positive(self):
        """Verify ALL drawdown values satisfy the NON-POSITIVE (<= 0.0) constraint.

        This test iterates over results to ensure no positive values exist.
        Anti-false-confidence: asserts list is non-empty before looping.
        """
        equity = [
            {"date": "2020-01-01", "equity": 100000},
            {"date": "2020-01-02", "equity": 95000},
            {"date": "2020-01-03", "equity": 105000},
            {"date": "2020-01-04", "equity": 102000},
            {"date": "2020-01-05", "equity": 110000},
        ]
        result = derive_drawdown_curve(equity)

        # Anti-false-confidence: verify list is non-empty before loop
        assert len(result) > 0, "Drawdown curve must not be empty"
        assert len(result) == len(equity), "Drawdown curve length must match equity curve"

        # Verify ALL values are non-positive (no epsilon hack)
        for i, point in enumerate(result):
            assert point["drawdown_pct"] <= 0.0, \
                f"Drawdown at index {i} must be non-positive, got {point['drawdown_pct']}"

    def test_no_epsilon_hack_at_peaks(self):
        """REGRESSION TEST: Detect epsilon hacks (artificial tiny negatives at peaks).

        This test MUST FAIL if someone adds an epsilon hack like:
            if drawdown_pct == 0.0: drawdown_pct = -1e-12

        IMPORTANT: We patch `round` to a no-op so we can observe RAW drawdown
        values before rounding. Without this, rounding would erase tiny epsilons
        and the test would be ineffective.

        Uses monotonic non-decreasing equity where every point is a peak.
        At peaks, raw drawdown_pct must be EXACTLY 0.0.
        """
        # Monotonic non-decreasing: every point is a new peak or equal to peak
        equity = [
            {"date": "2020-01-01", "equity": 100000},
            {"date": "2020-01-02", "equity": 100000},  # Equal to peak
            {"date": "2020-01-03", "equity": 105000},  # New peak
            {"date": "2020-01-04", "equity": 105000},  # Equal to peak
            {"date": "2020-01-05", "equity": 110000},  # New peak
            {"date": "2020-01-06", "equity": 115000},  # New peak
        ]

        # Patch round to return value unchanged (no-op) so we see raw values
        # This allows detection of epsilon hacks that would be erased by rounding
        def noop_round(x, ndigits=None):
            return x

        # MAINTENANCE NOTE: Patch target is "adapters.adapter.round" because
        # derive_drawdown_curve uses the module-level `round` builtin.
        # If rounding implementation changes (e.g., builtins.round, numpy.round),
        # this patch target MUST be updated accordingly.
        with patch("adapters.adapter.round", side_effect=noop_round):
            result = derive_drawdown_curve(equity)

        # Anti-false-confidence: verify we have data
        assert len(result) == 6, "Expected 6 drawdown points"

        # Every point is at or above peak, so RAW drawdown must be EXACTLY 0.0
        for i, point in enumerate(result):
            dd = point["drawdown_pct"]

            # Must be exactly 0.0 (not -1e-12 or any tiny negative)
            # This assertion will FAIL if an epsilon hack is introduced
            assert dd == 0.0, \
                f"Peak at index {i} has raw drawdown {dd!r}, expected exactly 0.0 (epsilon hack detected)"


class TestNormalizeTrades:
    """Test trade normalization to extended schema."""

    def test_empty_trades(self):
        """Empty trades list returns empty."""
        result = normalize_trades([])
        assert result == []

    def test_single_round_trip(self):
        """Single buy-sell pair is normalized correctly."""
        raw_trades = [
            {
                "date": "2020-01-15",
                "action": "buy",
                "quantity": 100,
                "price": 150.00,
                "effective_price": 150.30,
                "commission": 15.03,
                "total_cost": 15045.03,
            },
            {
                "date": "2020-03-15",
                "action": "sell",
                "quantity": 100,
                "price": 165.00,
                "effective_price": 164.67,
                "commission": 16.47,
                "net_proceeds": 16450.33,
            },
        ]

        result = normalize_trades(raw_trades, fee_rate=0.001)

        assert len(result) == 1
        trade = result[0]

        assert trade["trade_no"] == 0
        assert trade["side"] == "BUY"
        assert trade["size"] == 100
        assert trade["entry_price"] == 150.00
        assert trade["exit_price"] == 165.00
        assert "entry_timestamp" in trade
        assert "exit_timestamp" in trade
        assert "pnl_abs" in trade
        assert "pnl_pct" in trade
        assert "holding_period" in trade

    def test_multiple_trades(self):
        """Multiple round-trip trades are numbered correctly."""
        raw_trades = [
            {"date": "2020-01-01", "action": "buy", "quantity": 50, "price": 100, "commission": 5},
            {"date": "2020-02-01", "action": "sell", "quantity": 50, "price": 110, "commission": 5.5},
            {"date": "2020-03-01", "action": "buy", "quantity": 60, "price": 105, "commission": 6.3},
            {"date": "2020-04-01", "action": "sell", "quantity": 60, "price": 95, "commission": 5.7},
        ]

        result = normalize_trades(raw_trades, fee_rate=0.001)

        assert len(result) == 2
        assert result[0]["trade_no"] == 0
        assert result[1]["trade_no"] == 1

    def test_open_position_excluded(self):
        """Open position (buy without sell) is excluded."""
        raw_trades = [
            {"date": "2020-01-01", "action": "buy", "quantity": 100, "price": 150, "commission": 15},
            # No corresponding sell
        ]

        result = normalize_trades(raw_trades, fee_rate=0.001)

        # No complete round-trip, so empty
        assert result == []


class TestSafeIso8601Utc:
    """Test ISO8601 UTC timestamp conversion."""

    def test_date_string(self):
        """Date-only string gets 21:00 UTC timestamp."""
        result = safe_iso8601_utc("2020-01-15")
        assert result == "2020-01-15T21:00:00+00:00"

    def test_datetime_naive(self):
        """Naive datetime gets 21:00 UTC timestamp."""
        ts = pd.Timestamp("2020-01-15 10:30:00")
        result = safe_iso8601_utc(ts)
        # Naive timestamp -> assign 21:00 UTC
        assert result == "2020-01-15T21:00:00+00:00"

    def test_datetime_utc_aware(self):
        """UTC-aware timestamp is preserved."""
        ts = pd.Timestamp("2020-01-15 14:30:00", tz="UTC")
        result = safe_iso8601_utc(ts)
        assert result == "2020-01-15T14:30:00+00:00"

    def test_datetime_other_tz(self):
        """Non-UTC timezone is converted to UTC."""
        # 10:00 Eastern = 15:00 UTC (during EST)
        ts = pd.Timestamp("2020-01-15 10:00:00", tz="US/Eastern")
        result = safe_iso8601_utc(ts)
        # Should be converted to UTC
        assert "+00:00" in result


# ═══════════════════════════════════════════════════════════════
# FLASK APP TESTS (require app context)
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def app():
    """Create test Flask application."""
    from app import app as flask_app
    flask_app.config["TESTING"] = True
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    return flask_app


@pytest.fixture
def client(app):
    """Create test client with backtest_results table.

    NOTE: backtest_results is managed via raw SQL in app.py (not an ORM model),
    so it must be created explicitly here. If app.py's INSERT/SELECT columns
    change, this DDL must be updated to match. See Phase 4-2 TODO for
    migrating to a proper migration script.
    """
    with app.test_client() as c:
        with app.app_context():
            from extensions import db
            from sqlalchemy import text
            db.create_all()
            # Raw SQL table — not managed by SQLAlchemy ORM
            db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS backtest_results (
                    run_id      VARCHAR(36)  PRIMARY KEY,
                    ticker      VARCHAR(10),
                    rule_type   VARCHAR(50),
                    rule_id     VARCHAR(100),
                    params_json TEXT,
                    metrics_json TEXT,
                    equity_curve_json TEXT,
                    trades_json TEXT,
                    status      VARCHAR(20)  DEFAULT 'PENDING',
                    error_message TEXT,
                    created_at  DATETIME,
                    started_at  DATETIME,
                    completed_at DATETIME
                )
            """))
            db.session.commit()
        yield c


@pytest.fixture(autouse=True)
def reset_cached_job_launcher():
    """Reset the module-level _job_launcher cache between tests.

    HIGH-1 FIX: Always reset to None on both setup AND teardown.
    Previously restored `original` which could be a stale/contaminated value
    from a prior test. Now unconditionally sets None so every test starts
    with a clean cache regardless of execution order.
    """
    import app as app_module
    app_module._job_launcher = None
    yield
    app_module._job_launcher = None


def _mock_launcher():
    """Return a MagicMock launcher that succeeds silently."""
    m = MagicMock()
    m.mode = "LOCAL"
    m.launch.return_value = None
    return m


def _make_valid_payload():
    """Build a minimal valid /run_backtest payload (AAPL.csv must exist in data/)."""
    return {
        "ticker": "AAPL.csv",
        "rule_type": "RSI",
        "params": {"period": 14, "oversold": 30, "overbought": 70},
        "start_date": "2020-01-01",
        "end_date": "2023-12-31",
        "initial_capital": 100000,
        "fee_rate": 0.001,
    }


class TestRunBacktestResponseSchema:
    """Phase 3: Test /run_backtest response schema."""

    def test_success_response_has_all_required_fields(self, client):
        """Phase 3: Valid request returns 202 PENDING with required fields."""
        with patch("app.create_job_launcher", return_value=_mock_launcher()):
            response = client.post(
                "/run_backtest",
                data=json.dumps(_make_valid_payload()),
                content_type="application/json",
            )

        assert response.status_code == 202
        data = response.get_json()

        # Phase 3 minimal response contract
        assert "run_id" in data
        assert data["status"] == "PENDING"
        assert "started_at" in data
        assert "completed_at" in data
        assert "error_message" in data
        assert data["started_at"] is None
        assert data["completed_at"] is None
        assert data["error_message"] is None

    def test_error_response_has_all_required_fields(self, client):
        """400 error includes run_id, status FAILED, and error_message."""
        payload = {
            "ticker": "NONEXISTENT.csv",
            "rule_type": "RSI",
            "params": {},
            "start_date": "2020-01-01",
            "end_date": "2023-12-31",
        }

        response = client.post(
            "/run_backtest",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.get_json()

        assert "run_id" in data
        assert data["status"] == "FAILED"
        assert "error_message" in data
        assert data["error_message"] is not None

    def test_num_trades_equals_len_trades(self, client):
        """Phase 3: trades are populated by the Worker; Web only returns PENDING."""
        with patch("app.create_job_launcher", return_value=_mock_launcher()):
            response = client.post(
                "/run_backtest",
                data=json.dumps(_make_valid_payload()),
                content_type="application/json",
            )

        assert response.status_code == 202
        data = response.get_json()
        # In Phase 3 the web returns PENDING immediately; trades are worker output.
        assert data["status"] == "PENDING"


class TestInputValidation:
    """Test HTTP 400 errors for invalid user input."""

    def test_missing_ticker_returns_400(self, client):
        """Missing ticker field returns 400."""
        payload = {
            "rule_type": "RSI",
            "params": {},
            "start_date": "2020-01-01",
            "end_date": "2023-12-31",
        }

        response = client.post(
            "/run_backtest",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "run_id" in data
        assert data["status"] == "FAILED"

    def test_missing_dates_returns_400(self, client):
        """Missing date parameters return 400."""
        payload = {
            "ticker": "AAPL.csv",
            "rule_type": "RSI",
            "params": {},
        }

        response = client.post(
            "/run_backtest",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_null_start_date_returns_400(self, client):
        """FIX #2: null start_date returns 400, not 500."""
        payload = {
            "ticker": "AAPL.csv",
            "rule_type": "RSI",
            "params": {},
            "start_date": None,  # Explicit null
            "end_date": "2023-12-31",
        }

        response = client.post(
            "/run_backtest",
            data=json.dumps(payload),
            content_type="application/json",
        )

        # Must be 400 (input error), NOT 500 (system error)
        assert response.status_code == 400
        data = response.get_json()
        assert data["status"] == "FAILED"
        assert "start_date" in data["error_message"].lower()

    def test_null_end_date_returns_400(self, client):
        """FIX #2: null end_date returns 400, not 500."""
        payload = {
            "ticker": "AAPL.csv",
            "rule_type": "RSI",
            "params": {},
            "start_date": "2020-01-01",
            "end_date": None,  # Explicit null
        }

        response = client.post(
            "/run_backtest",
            data=json.dumps(payload),
            content_type="application/json",
        )

        # Must be 400 (input error), NOT 500 (system error)
        assert response.status_code == 400
        data = response.get_json()
        assert data["status"] == "FAILED"
        assert "end_date" in data["error_message"].lower()

    def test_empty_string_start_date_returns_400(self, client):
        """FIX #2: Empty string start_date returns 400."""
        payload = {
            "ticker": "AAPL.csv",
            "rule_type": "RSI",
            "params": {},
            "start_date": "",  # Empty string
            "end_date": "2023-12-31",
        }

        response = client.post(
            "/run_backtest",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_empty_string_end_date_returns_400(self, client):
        """FIX #2: Empty string end_date returns 400."""
        payload = {
            "ticker": "AAPL.csv",
            "rule_type": "RSI",
            "params": {},
            "start_date": "2020-01-01",
            "end_date": "",  # Empty string
        }

        response = client.post(
            "/run_backtest",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_unknown_strategy_returns_400(self, client):
        """Unknown strategy (rule_type) returns 400."""
        payload = {
            "ticker": "AAPL.csv",
            "strategy": "UNKNOWN_STRATEGY",
            "params": {},
            "start_date": "2020-01-01",
            "end_date": "2023-12-31",
        }

        response = client.post(
            "/run_backtest",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 400


class TestSlippageContract:
    """Phase 3: slippage_bps is forwarded as-is to the job launcher payload.

    Bps→decimal conversion is the Worker's responsibility.
    These tests verify that the Web layer correctly passes slippage_bps
    through to the job payload without alteration.
    """

    def test_slippage_bps_forwarded_to_launcher(self, client):
        """slippage_bps value is included in the payload sent to the job launcher."""
        payload = {
            "ticker": "AAPL.csv",
            "rule_type": "RSI",
            "params": {},
            "start_date": "2020-01-01",
            "end_date": "2023-12-31",
            "slippage_bps": 20,
        }

        captured = []
        mock = _mock_launcher()
        mock.launch.side_effect = lambda p: captured.append(dict(p))

        with patch("app.create_job_launcher", return_value=mock):
            response = client.post(
                "/run_backtest",
                data=json.dumps(payload),
                content_type="application/json",
            )

        assert response.status_code == 202
        assert len(captured) == 1
        assert captured[0]["slippage_bps"] == 20

    def test_default_slippage_bps_is_none_when_not_provided(self, client):
        """When slippage_bps is absent from the request, payload has slippage_bps=None."""
        payload = {
            "ticker": "AAPL.csv",
            "rule_type": "RSI",
            "params": {},
            "start_date": "2020-01-01",
            "end_date": "2023-12-31",
            # slippage_bps not provided
        }

        captured = []
        mock = _mock_launcher()
        mock.launch.side_effect = lambda p: captured.append(dict(p))

        with patch("app.create_job_launcher", return_value=mock):
            response = client.post(
                "/run_backtest",
                data=json.dumps(payload),
                content_type="application/json",
            )

        assert response.status_code == 202
        assert len(captured) == 1
        assert captured[0]["slippage_bps"] is None

    def test_zero_slippage_bps_forwarded_to_launcher(self, client):
        """slippage_bps=0 is explicitly forwarded as 0 (not as None or missing)."""
        payload = {
            "ticker": "AAPL.csv",
            "rule_type": "RSI",
            "params": {},
            "start_date": "2020-01-01",
            "end_date": "2023-12-31",
            "slippage_bps": 0,
        }

        captured = []
        mock = _mock_launcher()
        mock.launch.side_effect = lambda p: captured.append(dict(p))

        with patch("app.create_job_launcher", return_value=mock):
            response = client.post(
                "/run_backtest",
                data=json.dumps(payload),
                content_type="application/json",
            )

        assert response.status_code == 202
        assert len(captured) == 1
        assert captured[0]["slippage_bps"] == 0


class TestSharpeRatioCompliance:
    """Phase 3: Sharpe Ratio is computed by the Worker, not the Web layer.

    The Web layer only accepts the request and returns 202 PENDING.
    Sharpe Ratio computation is verified in worker tests (Phase 4-2).
    """

    def test_valid_request_accepted_and_pending(self, client):
        """Valid backtest request returns 202 PENDING; metrics are Worker's concern."""
        with patch("app.create_job_launcher", return_value=_mock_launcher()):
            response = client.post(
                "/run_backtest",
                data=json.dumps(_make_valid_payload()),
                content_type="application/json",
            )

        assert response.status_code == 202
        data = response.get_json()
        assert data["status"] == "PENDING"
        assert "run_id" in data


class TestErrorResponseSchema:
    """Phase 3: Test error response schema structure."""

    def test_400_error_has_correct_structure(self, client):
        """Phase 3: 400 error response has correct minimal structure."""
        payload = {
            "ticker": "NONEXISTENT.csv",
            "rule_type": "RSI",
            "params": {},
            "start_date": "2020-01-01",
            "end_date": "2023-12-31",
        }

        response = client.post(
            "/run_backtest",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "run_id" in data
        assert data["status"] == "FAILED"
        assert "error_message" in data
        assert data["error_message"] is not None

    def test_500_error_has_correct_structure(self, client):
        """Phase 3: 500 error (job launch failure) has correct minimal structure."""
        mock = _mock_launcher()
        mock.launch.side_effect = RuntimeError("Simulated job launch failure")

        with patch("app.create_job_launcher", return_value=mock):
            response = client.post(
                "/run_backtest",
                data=json.dumps(_make_valid_payload()),
                content_type="application/json",
            )

        assert response.status_code == 500
        data = response.get_json()
        assert "run_id" in data
        assert data["status"] == "FAILED"
        assert "error_message" in data
        assert data["error_message"] is not None


class TestSystemErrors:
    """Test HTTP 500 errors for system failures.

    IMPORTANT: System errors are simulated via monkeypatch ONLY.
    No application code modifications for error simulation.
    """

    def test_engine_crash_returns_500(self, client):
        """Phase 3: Job launch failure returns 500.

        (Formerly patched app.BacktestEngine — engine runs in worker.py.
        In Phase 3, a Web-level 500 is triggered by job launcher failure.)
        """
        mock = _mock_launcher()
        mock.launch.side_effect = RuntimeError("Simulated job launch failure")

        with patch("app.create_job_launcher", return_value=mock):
            response = client.post(
                "/run_backtest",
                data=json.dumps(_make_valid_payload()),
                content_type="application/json",
            )

        assert response.status_code == 500
        data = response.get_json()
        assert "run_id" in data
        assert data["status"] == "FAILED"
        assert "error_message" in data
        # Error message must reference the launch failure (no raw stack trace)
        assert "Job launch failed" in data["error_message"]

    def test_csv_parse_error_returns_500(self, client):
        """Phase 3: DB insert failure returns 500.

        (Formerly patched app.pd.read_csv — pandas is no longer in app.py.
        In Phase 3, a Web-level 500 can be triggered by DB insert failure.)
        """
        with patch("app.db.session.execute", side_effect=Exception("Simulated DB failure")):
            response = client.post(
                "/run_backtest",
                data=json.dumps(_make_valid_payload()),
                content_type="application/json",
            )

        assert response.status_code == 500
        data = response.get_json()
        assert data["status"] == "FAILED"
        assert "error_message" in data


class TestBackwardCompatibility:
    """Test backward compatibility with existing API.

    MED-3 FIX: All tests now verify status_code explicitly.
    """

    def test_old_request_format_works(self, client):
        """Request with 'strategy' (old field) instead of 'rule_type' still works.

        MED-3 FIX: Must assert 202 + PENDING to verify strategy→rule_type fallback.
        Previously missing status_code assertion allowed silent 400 pass-through.
        """
        payload = {
            "ticker": "AAPL.csv",
            "strategy": "RSI",
            "params": {"period": 14, "oversold": 30, "overbought": 70},
            "start_date": "2020-01-01",
            "end_date": "2023-12-31",
        }

        with patch("app.create_job_launcher", return_value=_mock_launcher()):
            response = client.post(
                "/run_backtest",
                data=json.dumps(payload),
                content_type="application/json",
            )

        # Must be 202, not 400 — backward compat requires strategy→rule_type fallback
        assert response.status_code == 202, \
            f"strategy→rule_type fallback broken: got {response.status_code}, body={response.get_json()}"
        data = response.get_json()
        assert "run_id" in data
        assert data["status"] == "PENDING"

    def test_strategy_fallback_launches_job(self, client):
        """MED-3: Verify strategy→rule_type fallback actually reaches the launcher.

        This ensures the fallback isn't just silently accepted but actually
        results in a job launch with the correct rule_type.
        """
        payload = {
            "ticker": "AAPL.csv",
            "strategy": "MACD",  # Use old field name
            "params": {"fast": 12, "slow": 26, "signal": 9},
            "start_date": "2020-01-01",
            "end_date": "2023-12-31",
        }

        captured = []
        mock = _mock_launcher()
        mock.launch.side_effect = lambda p: captured.append(dict(p))

        with patch("app.create_job_launcher", return_value=mock):
            response = client.post(
                "/run_backtest",
                data=json.dumps(payload),
                content_type="application/json",
            )

        assert response.status_code == 202
        assert len(captured) == 1, "Job launcher must be called exactly once"
        assert captured[0]["rule_type"] == "MACD", \
            f"strategy→rule_type fallback yielded wrong rule_type: {captured[0].get('rule_type')}"

    def test_chart_image_backward_compat(self, client):
        """Phase 3: run_id and status always present regardless of request format."""
        with patch("app.create_job_launcher", return_value=_mock_launcher()):
            response = client.post(
                "/run_backtest",
                data=json.dumps(_make_valid_payload()),
                content_type="application/json",
            )

        assert response.status_code == 202
        data = response.get_json()
        assert "run_id" in data
        assert data["status"] == "PENDING"


class TestHealthEndpoint:
    """Test /health endpoint."""

    def test_health_returns_ok(self, client):
        """Health endpoint returns status ok."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"


class TestPortfolioCurveOnError:
    """Phase 3: Error responses have correct minimal structure.

    (Formerly tested portfolio_curve / chart_image keys — those are Worker
    output and do not appear in the Phase 3 Web response.)
    """

    def test_400_error_has_correct_structure(self, client):
        """Phase 3: 400 error has run_id, FAILED status, and error_message."""
        payload = {
            "ticker": "NONEXISTENT.csv",
            "rule_type": "RSI",
            "params": {},
            "start_date": "2020-01-01",
            "end_date": "2023-12-31",
        }

        response = client.post(
            "/run_backtest",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "run_id" in data
        assert data["status"] == "FAILED"
        assert data["error_message"] is not None

    def test_500_error_has_correct_structure(self, client):
        """Phase 3: 500 error (job launch failure) has correct structure."""
        mock = _mock_launcher()
        mock.launch.side_effect = RuntimeError("Simulated failure")

        with patch("app.create_job_launcher", return_value=mock):
            response = client.post(
                "/run_backtest",
                data=json.dumps(_make_valid_payload()),
                content_type="application/json",
            )

        assert response.status_code == 500
        data = response.get_json()
        assert "run_id" in data
        assert data["status"] == "FAILED"

    def test_400_error_run_id_is_valid_uuid4(self, client):
        """Phase 3: 400 error run_id is a valid UUID4."""
        payload = {
            "ticker": "NONEXISTENT.csv",
            "rule_type": "RSI",
            "params": {},
            "start_date": "2020-01-01",
            "end_date": "2023-12-31",
        }

        response = client.post(
            "/run_backtest",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.get_json()
        try:
            parsed = uuid.UUID(data["run_id"], version=4)
            assert str(parsed) == data["run_id"]
        except (ValueError, KeyError) as exc:
            pytest.fail(f"run_id is not a valid UUID4: {exc}")

    def test_500_error_run_id_is_valid_uuid4(self, client):
        """Phase 3: 500 error run_id is a valid UUID4."""
        mock = _mock_launcher()
        mock.launch.side_effect = RuntimeError("Simulated failure")

        with patch("app.create_job_launcher", return_value=mock):
            response = client.post(
                "/run_backtest",
                data=json.dumps(_make_valid_payload()),
                content_type="application/json",
            )

        assert response.status_code == 500
        data = response.get_json()
        try:
            parsed = uuid.UUID(data["run_id"], version=4)
            assert str(parsed) == data["run_id"]
        except (ValueError, KeyError) as exc:
            pytest.fail(f"run_id is not a valid UUID4: {exc}")


class TestSharpeRatioExecutionPath:
    """Phase 3: Sharpe Ratio computation is Worker's responsibility.

    MED-1 FIX: Removed dead-code `if data.get("status") == "completed"` branches
    that never triggered (Phase 3 always returns PENDING/FAILED, never "completed").
    MED-2 FIX: Replaced `assert status in ("PENDING", "FAILED")` with exact
    `assert status == "PENDING"` for valid input paths.
    """

    def test_valid_request_returns_pending(self, client):
        """Phase 3: Valid request returns 202 PENDING.

        MED-1 FIX: Previously had dead `if status == "completed": assert sharpe...`
        branch that never executed. Now directly asserts the Phase 3 contract.
        """
        with patch("app.create_job_launcher", return_value=_mock_launcher()):
            response = client.post(
                "/run_backtest",
                data=json.dumps(_make_valid_payload()),
                content_type="application/json",
            )

        assert response.status_code == 202
        data = response.get_json()
        assert data["status"] == "PENDING"
        assert "run_id" in data

    def test_valid_request_returns_exactly_pending(self, client):
        """Phase 3: Valid input must return exactly PENDING, not FAILED.

        MED-2 FIX: Previously accepted FAILED as valid for correct input
        (`assert status in ("PENDING", "FAILED")`). This masked regressions
        where valid requests were incorrectly rejected.
        """
        with patch("app.create_job_launcher", return_value=_mock_launcher()):
            response = client.post(
                "/run_backtest",
                data=json.dumps(_make_valid_payload()),
                content_type="application/json",
            )

        assert response.status_code == 202
        data = response.get_json()
        # Valid input must ALWAYS be PENDING, never FAILED
        assert data["status"] == "PENDING", \
            f"Valid input returned status={data['status']!r}, expected 'PENDING'"


class TestSafeIso8601UtcParseFailure:
    """Test safe_iso8601_utc returns None on parse failure."""

    def test_unparseable_string_returns_none(self):
        """Unparseable string returns None, not original value."""
        result = safe_iso8601_utc("not-a-valid-date-at-all")
        assert result is None

    def test_none_input_returns_none(self):
        """None input returns None."""
        result = safe_iso8601_utc(None)
        assert result is None

    def test_valid_date_still_works(self):
        """Valid date input still works correctly."""
        result = safe_iso8601_utc("2020-01-15")
        assert result == "2020-01-15T21:00:00+00:00"

    def test_empty_string_returns_none(self):
        """Empty string returns None (unparseable)."""
        result = safe_iso8601_utc("")
        assert result is None


class TestChartsObject:
    """Phase 3: Charts are generated by Worker, not Web.

    MED-1 FIX: Removed dead-code `if data.get("charts")` branches that
    never triggered. Web returns PENDING/FAILED without charts.
    """

    def test_success_response_is_202_pending(self, client):
        """Phase 3: Valid request returns 202 PENDING with required fields."""
        with patch("app.create_job_launcher", return_value=_mock_launcher()):
            response = client.post(
                "/run_backtest",
                data=json.dumps(_make_valid_payload()),
                content_type="application/json",
            )

        assert response.status_code == 202
        data = response.get_json()
        assert data["status"] == "PENDING"
        assert "run_id" in data

    def test_success_run_id_is_valid_uuid4(self, client):
        """Phase 3: 202 response contains a valid UUID4 run_id.

        MED-1 FIX: Replaced dead `if data.get("charts"): assert base64...`
        with meaningful UUID4 validation.
        """
        with patch("app.create_job_launcher", return_value=_mock_launcher()):
            response = client.post(
                "/run_backtest",
                data=json.dumps(_make_valid_payload()),
                content_type="application/json",
            )

        assert response.status_code == 202
        data = response.get_json()
        try:
            parsed = uuid.UUID(data["run_id"], version=4)
            assert str(parsed) == data["run_id"]
        except (ValueError, KeyError) as exc:
            pytest.fail(f"run_id is not a valid UUID4: {exc}")

    def test_400_error_has_correct_structure(self, client):
        """Phase 3: 400 error has run_id + FAILED status."""
        payload = {
            "ticker": "AAPL.csv",
            "strategy": "INVALID_STRATEGY",
            "start_date": "2020-01-01",
            "end_date": "2023-12-31",
        }

        response = client.post(
            "/run_backtest",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "run_id" in data
        assert data["status"] == "FAILED"

    def test_500_error_has_correct_structure(self, client):
        """Phase 3: 500 error (launch failure) has run_id + FAILED status."""
        mock = _mock_launcher()
        mock.launch.side_effect = RuntimeError("Simulated crash")

        with patch("app.create_job_launcher", return_value=mock):
            response = client.post(
                "/run_backtest",
                data=json.dumps(_make_valid_payload()),
                content_type="application/json",
            )

        assert response.status_code == 500
        data = response.get_json()
        assert "run_id" in data
        assert data["status"] == "FAILED"


# ═══════════════════════════════════════════════════════════════
# STATUS ENDPOINT TESTS (HIGH-2)
# ═══════════════════════════════════════════════════════════════

class TestStatusEndpoint:
    """Test GET /status/<run_id> endpoint (Phase 3 core contract).

    HIGH-2 FIX: This entire class is NEW. Previously no /status tests existed,
    leaving half the Phase 3 API contract unverified.

    Contract:
    - Existing PENDING run → 200 {run_id, status:"PENDING", started_at, completed_at, error_message}
    - Existing FAILED run  → 200 {run_id, status:"FAILED", ..., error_message:"..."}
    - Non-existent run_id  → 404 {error: "Run not found"}
    - DB error             → 500 {error: "..."}
    """

    def test_nonexistent_run_returns_404(self, client):
        """Non-existent run_id returns 404 with error message."""
        fake_run_id = str(uuid.uuid4())
        response = client.get(f"/status/{fake_run_id}")

        assert response.status_code == 404
        data = response.get_json()
        assert "error" in data
        assert data["error"] == "Run not found"

    def test_pending_run_returns_200_with_full_schema(self, client):
        """After successful dispatch, /status returns 200 with PENDING and full schema."""
        with patch("app.create_job_launcher", return_value=_mock_launcher()):
            create_resp = client.post(
                "/run_backtest",
                data=json.dumps(_make_valid_payload()),
                content_type="application/json",
            )

        assert create_resp.status_code == 202
        run_id = create_resp.get_json()["run_id"]

        # Query status
        status_resp = client.get(f"/status/{run_id}")
        assert status_resp.status_code == 200
        data = status_resp.get_json()

        # Full Phase 3 status contract
        assert data["run_id"] == run_id
        assert data["status"] == "PENDING"
        assert "started_at" in data
        assert "completed_at" in data
        assert "error_message" in data

    def test_failed_run_returns_200_with_failed_status(self, client):
        """After launch failure, /status returns 200 with FAILED and error_message."""
        mock = _mock_launcher()
        mock.launch.side_effect = RuntimeError("Simulated launch failure")

        with patch("app.create_job_launcher", return_value=mock):
            create_resp = client.post(
                "/run_backtest",
                data=json.dumps(_make_valid_payload()),
                content_type="application/json",
            )

        assert create_resp.status_code == 500
        run_id = create_resp.get_json()["run_id"]

        # Status should reflect FAILED
        status_resp = client.get(f"/status/{run_id}")
        assert status_resp.status_code == 200
        data = status_resp.get_json()
        assert data["run_id"] == run_id
        assert data["status"] == "FAILED"
        assert data["error_message"] is not None

    def test_status_db_error_returns_500(self, client):
        fake_run_id = str(uuid.uuid4())

        with patch("app.db.session.execute", side_effect=Exception("Simulated DB failure")):
            response = client.get(f"/status/{fake_run_id}")

        assert response.status_code == 500
        data = response.get_json()

        # app.py 실제 계약: system_error도 run-payload 형태로 반환
        assert data["run_id"] == fake_run_id
        assert data["status"] == "FAILED"
        assert "started_at" in data
        assert "completed_at" in data
        assert "error_message" in data
        assert data["error_message"] is not None
        assert "query status" in data["error_message"].lower()
    # def test_status_db_error_returns_500(self, client):
    #     """DB error during status fetch returns 500.

    #     Verifies the /status endpoint's error handling path without
    #     modifying app.py — uses patch to simulate DB failure.
    #     """
    #     fake_run_id = str(uuid.uuid4())

    #     with patch("app.db.session.execute", side_effect=Exception("Simulated DB failure")):
    #         response = client.get(f"/status/{fake_run_id}")

    #     assert response.status_code == 500
    #     data = response.get_json()
    #     assert "error" in data

    

    def test_status_run_id_matches_request(self, client):
        """Returned run_id in /status matches the requested run_id exactly."""
        with patch("app.create_job_launcher", return_value=_mock_launcher()):
            create_resp = client.post(
                "/run_backtest",
                data=json.dumps(_make_valid_payload()),
                content_type="application/json",
            )

        run_id = create_resp.get_json()["run_id"]

        status_resp = client.get(f"/status/{run_id}")
        data = status_resp.get_json()
        assert data["run_id"] == run_id, \
            f"run_id mismatch: requested {run_id}, got {data.get('run_id')}"


class TestRenderDrawdownChart:
    """Test render_drawdown_chart adapter function."""

    def test_empty_curve_returns_none(self):
        """Empty drawdown curve returns None."""
        result = render_drawdown_chart([])
        assert result is None

    def test_valid_curve_returns_base64(self):
        """Valid drawdown curve returns Base64 PNG."""
        curve = [
            {"date": "2020-01-01", "drawdown_pct": 0.0},
            {"date": "2020-01-02", "drawdown_pct": -1.5},
            {"date": "2020-01-03", "drawdown_pct": -3.2},
            {"date": "2020-01-04", "drawdown_pct": -2.0},
            {"date": "2020-01-05", "drawdown_pct": 0.0},
        ]

        result = render_drawdown_chart(curve)
        assert result is not None
        assert result.startswith("data:image/png;base64,")
        b64_content = result.replace("data:image/png;base64,", "")
        assert len(b64_content) > 100, "Base64 content should be substantial"


class TestRenderOrdersChart:
    """Test render_orders_chart adapter function."""

    def test_empty_df_returns_none(self):
        """Empty price DataFrame returns None."""
        result = render_orders_chart(pd.DataFrame(), [])
        assert result is None

    def test_missing_close_column_returns_none(self):
        """DataFrame without Close column returns None."""
        df = pd.DataFrame({
            "Open": [100, 101, 102],
            "High": [105, 106, 107],
        }, index=pd.date_range("2020-01-01", periods=3))

        result = render_orders_chart(df, [])
        assert result is None

    def test_valid_data_returns_base64(self):
        """Valid price data returns Base64 PNG."""
        df = pd.DataFrame({
            "Close": [100, 105, 110, 108, 115],
        }, index=pd.date_range("2020-01-01", periods=5))

        trades = [
            {
                "trade_no": 0,
                "entry_timestamp": "2020-01-02T21:00:00+00:00",
                "exit_timestamp": "2020-01-04T21:00:00+00:00",
                "pnl_pct": 3.5
            }
        ]

        result = render_orders_chart(df, trades)
        assert result is not None
        assert result.startswith("data:image/png;base64,")
        b64_content = result.replace("data:image/png;base64,", "")
        assert len(b64_content) > 100, "Base64 content should be substantial"


class TestRenderTradePnlChart:
    """Test render_trade_pnl_chart adapter function."""

    def test_empty_df_returns_none(self):
        """Empty price DataFrame returns None."""
        result = render_trade_pnl_chart(pd.DataFrame(), [])
        assert result is None

    def test_valid_data_returns_base64(self):
        """Valid price data with trades returns Base64 PNG."""
        df = pd.DataFrame({
            "Close": [100, 105, 110, 108, 115],
        }, index=pd.date_range("2020-01-01", periods=5))

        trades = [
            {
                "trade_no": 0,
                "entry_timestamp": "2020-01-02T21:00:00+00:00",
                "exit_timestamp": "2020-01-04T21:00:00+00:00",
                "pnl_pct": 3.5
            },
            {
                "trade_no": 1,
                "entry_timestamp": "2020-01-03T21:00:00+00:00",
                "exit_timestamp": "2020-01-05T21:00:00+00:00",
                "pnl_pct": -1.2
            },
        ]

        result = render_trade_pnl_chart(df, trades)
        assert result is not None
        assert result.startswith("data:image/png;base64,")
        b64_content = result.replace("data:image/png;base64,", "")
        assert len(b64_content) > 100, "Base64 content should be substantial"

    def test_no_trades_still_renders(self):
        """Price data with empty trades list still renders (empty scatter)."""
        df = pd.DataFrame({
            "Close": [100, 105, 110],
        }, index=pd.date_range("2020-01-01", periods=3))

        result = render_trade_pnl_chart(df, [])
        assert result is not None
        assert result.startswith("data:image/png;base64,")


class TestRenderCumulativeReturnChart:
    """Test render_cumulative_return_chart adapter function."""

    def test_empty_curve_returns_none(self):
        """Empty equity curve returns None."""
        result = render_cumulative_return_chart([])
        assert result is None

    def test_valid_curve_returns_base64(self):
        """Valid equity curve returns Base64 PNG cumulative return chart."""
        curve = [
            {"date": "2020-01-01", "equity": 100000},
            {"date": "2020-01-02", "equity": 101000},
            {"date": "2020-01-03", "equity": 99000},
            {"date": "2020-01-04", "equity": 102000},
            {"date": "2020-01-05", "equity": 103000},
        ]

        result = render_cumulative_return_chart(curve)
        assert result is not None
        assert result.startswith("data:image/png;base64,")
        b64_content = result.replace("data:image/png;base64,", "")
        assert len(b64_content) > 100, "Base64 content should be substantial"

    def test_zero_initial_equity_returns_none(self):
        """Zero initial equity returns None (avoids division by zero)."""
        curve = [
            {"date": "2020-01-01", "equity": 0},
            {"date": "2020-01-02", "equity": 100},
        ]

        result = render_cumulative_return_chart(curve)
        assert result is None


# ═══════════════════════════════════════════════════════════════
# DETERMINISTIC SUCCESS PATH TESTS (Phase 3)
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def deterministic_backtest_patches():
    """Phase 3: Patches for deterministic Web-layer success path tests."""
    mock = _mock_launcher()
    with patch("app.create_job_launcher", return_value=mock):
        yield mock


class TestDeterministicSuccessPath:
    """Phase 3: Web layer success path tests.

    Verifies that the Web layer:
    1. Accepts valid requests and returns 202 PENDING.
    2. Issues a valid UUID4 run_id.
    3. Calls the job launcher with the correct payload.
    """

    def test_valid_request_returns_202_pending(
        self, client, deterministic_backtest_patches
    ):
        """Phase 3: Valid request returns 202 PENDING."""
        payload = {
            "ticker": "AAPL.csv",
            "rule_type": "RSI",
            "params": {"period": 14, "oversold": 30, "overbought": 70},
            "start_date": "2020-01-01",
            "end_date": "2020-01-31",
            "initial_capital": 100000,
            "fee_rate": 0.001,
        }

        response = client.post(
            "/run_backtest",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 202, \
            f"Expected 202, got {response.status_code}: {response.get_json()}"
        data = response.get_json()
        assert data["status"] == "PENDING"
        assert data["error_message"] is None

    def test_run_id_is_valid_uuid4(
        self, client, deterministic_backtest_patches
    ):
        """Phase 3: run_id is a valid UUID4."""
        payload = {
            "ticker": "AAPL.csv",
            "rule_type": "RSI",
            "params": {},
            "start_date": "2020-01-01",
            "end_date": "2020-01-31",
        }

        response = client.post(
            "/run_backtest",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 202
        data = response.get_json()

        try:
            parsed = uuid.UUID(data["run_id"], version=4)
            assert str(parsed) == data["run_id"], \
                f"run_id {data['run_id']} does not round-trip as UUID4"
        except ValueError as exc:
            pytest.fail(f"run_id is not a valid UUID4: {exc}")

    def test_launcher_receives_correct_payload(
        self, client, deterministic_backtest_patches
    ):
        """Phase 3: Job launcher receives correct payload fields."""
        mock_launcher = deterministic_backtest_patches
        captured = []
        mock_launcher.launch.side_effect = lambda p: captured.append(dict(p))

        payload = {
            "ticker": "AAPL.csv",
            "rule_type": "RSI",
            "params": {"period": 14},
            "start_date": "2020-01-01",
            "end_date": "2020-01-31",
        }

        response = client.post(
            "/run_backtest",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 202
        assert len(captured) == 1, "Job launcher must be called exactly once"

        launched = captured[0]
        assert launched["ticker"] == "AAPL.csv"
        assert launched["rule_type"] == "RSI"
        assert launched["start_date"] == "2020-01-01"
        assert launched["end_date"] == "2020-01-31"
        assert "run_id" in launched


# ═══════════════════════════════════════════════════════════════
# FIGURE MEMORY LEAK PREVENTION TESTS
# ═══════════════════════════════════════════════════════════════

class TestFigureLeakPrevention:
    """Test that chart rendering functions properly close matplotlib figures."""

    def test_render_drawdown_chart_closes_figure(self):
        """render_drawdown_chart leaves no open figures after execution."""
        drawdown_curve = [
            {"date": "2020-01-01", "drawdown_pct": 0.0},
            {"date": "2020-01-02", "drawdown_pct": -2.5},
            {"date": "2020-01-03", "drawdown_pct": -5.0},
            {"date": "2020-01-04", "drawdown_pct": -3.0},
            {"date": "2020-01-05", "drawdown_pct": 0.0},
        ]

        before_fignums = set(plt.get_fignums())
        result = render_drawdown_chart(drawdown_curve)
        after_fignums = set(plt.get_fignums())

        assert result is not None, "render_drawdown_chart should return a result"
        assert result.startswith("data:image/png;base64,")

        new_figures = after_fignums - before_fignums
        assert new_figures == set(), \
            f"render_drawdown_chart left open figures: {new_figures}"

    def test_render_drawdown_chart_closes_figure_on_large_input(self):
        """render_drawdown_chart closes figures even with large data."""
        drawdown_curve = [
            {"date": f"2020-{(i // 30) + 1:02d}-{(i % 28) + 1:02d}",
             "drawdown_pct": -float(i % 10)}
            for i in range(100)
        ]

        before_fignums = set(plt.get_fignums())
        result = render_drawdown_chart(drawdown_curve)
        after_fignums = set(plt.get_fignums())

        assert result is not None
        assert after_fignums == before_fignums, \
            f"Figures leaked: {after_fignums - before_fignums}"

    def test_render_orders_chart_closes_figure(self):
        """render_orders_chart leaves no open figures after execution."""
        price_df = pd.DataFrame({
            "Close": [100.0, 102.0, 101.0, 104.0, 106.0],
        }, index=pd.date_range("2020-01-01", periods=5, freq="D"))

        trades = [
            {
                "trade_no": 0,
                "entry_timestamp": "2020-01-02T21:00:00+00:00",
                "exit_timestamp": "2020-01-04T21:00:00+00:00",
                "pnl_pct": 2.5,
            }
        ]

        before_fignums = set(plt.get_fignums())
        result = render_orders_chart(price_df, trades)
        after_fignums = set(plt.get_fignums())

        assert result is not None
        assert result.startswith("data:image/png;base64,")

        new_figures = after_fignums - before_fignums
        assert new_figures == set(), \
            f"render_orders_chart left open figures: {new_figures}"

    def test_render_trade_pnl_chart_closes_figure(self):
        """render_trade_pnl_chart leaves no open figures after execution."""
        price_df = pd.DataFrame({
            "Close": [100, 102, 104, 103, 105, 107, 106, 108, 110, 112],
        }, index=pd.date_range("2020-01-01", periods=10, freq="D"))

        trades = [
            {
                "trade_no": 0,
                "entry_timestamp": "2020-01-02T21:00:00+00:00",
                "exit_timestamp": "2020-01-04T21:00:00+00:00",
                "pnl_pct": 2.0,
            },
            {
                "trade_no": 1,
                "entry_timestamp": "2020-01-05T21:00:00+00:00",
                "exit_timestamp": "2020-01-07T21:00:00+00:00",
                "pnl_pct": -1.5,
            },
            {
                "trade_no": 2,
                "entry_timestamp": "2020-01-08T21:00:00+00:00",
                "exit_timestamp": "2020-01-10T21:00:00+00:00",
                "pnl_pct": 3.0,
            },
        ]

        before_fignums = set(plt.get_fignums())
        result = render_trade_pnl_chart(price_df, trades)
        after_fignums = set(plt.get_fignums())

        assert result is not None
        assert after_fignums == before_fignums, \
            f"Figures leaked: {after_fignums - before_fignums}"

    def test_render_drawdown_chart_closes_figure_on_empty_input(self):
        """render_drawdown_chart handles empty input without leaking."""
        before_fignums = set(plt.get_fignums())
        result = render_drawdown_chart([])
        after_fignums = set(plt.get_fignums())

        assert result is None
        assert after_fignums == before_fignums, \
            f"Figures leaked on empty input: {after_fignums - before_fignums}"

    def test_render_orders_chart_closes_figure_on_empty_df(self):
        """render_orders_chart handles empty DataFrame without leaking."""
        before_fignums = set(plt.get_fignums())
        result = render_orders_chart(pd.DataFrame(), [])
        after_fignums = set(plt.get_fignums())

        assert result is None
        assert after_fignums == before_fignums, \
            f"Figures leaked on empty input: {after_fignums - before_fignums}"

    def test_render_trade_pnl_chart_closes_figure_on_empty_df(self):
        """render_trade_pnl_chart handles empty DataFrame without leaking."""
        before_fignums = set(plt.get_fignums())
        result = render_trade_pnl_chart(pd.DataFrame(), [])
        after_fignums = set(plt.get_fignums())

        assert result is None
        assert after_fignums == before_fignums, \
            f"Figures leaked on empty input: {after_fignums - before_fignums}"

    def test_render_cumulative_return_chart_closes_figure(self):
        """render_cumulative_return_chart leaves no open figures after execution."""
        equity_curve = [
            {"date": "2020-01-01", "equity": 100000},
            {"date": "2020-01-02", "equity": 101000},
            {"date": "2020-01-03", "equity": 99000},
            {"date": "2020-01-04", "equity": 102000},
            {"date": "2020-01-05", "equity": 103000},
        ]

        before_fignums = set(plt.get_fignums())
        result = render_cumulative_return_chart(equity_curve)
        after_fignums = set(plt.get_fignums())

        assert result is not None
        assert result.startswith("data:image/png;base64,")

        new_figures = after_fignums - before_fignums
        assert new_figures == set(), \
            f"render_cumulative_return_chart left open figures: {new_figures}"

    def test_render_cumulative_return_chart_closes_figure_on_empty(self):
        """render_cumulative_return_chart handles empty input without leaking."""
        before_fignums = set(plt.get_fignums())
        result = render_cumulative_return_chart([])
        after_fignums = set(plt.get_fignums())

        assert result is None
        assert after_fignums == before_fignums, \
            f"Figures leaked on empty input: {after_fignums - before_fignums}"

    def test_consecutive_renders_do_not_accumulate_figures(self):
        """Multiple consecutive renders do not accumulate open figures."""
        drawdown_curve = [
            {"date": "2020-01-01", "drawdown_pct": 0.0},
            {"date": "2020-01-02", "drawdown_pct": -5.0},
            {"date": "2020-01-03", "drawdown_pct": 0.0},
        ]

        equity_curve = [
            {"date": "2020-01-01", "equity": 100000},
            {"date": "2020-01-02", "equity": 101000},
            {"date": "2020-01-03", "equity": 102000},
        ]

        price_df = pd.DataFrame({
            "Close": [100.0, 102.0, 104.0],
        }, index=pd.date_range("2020-01-01", periods=3, freq="D"))

        trades = [{"trade_no": 0, "entry_timestamp": "2020-01-01T21:00:00+00:00",
                   "exit_timestamp": "2020-01-02T21:00:00+00:00", "pnl_pct": 1.0}]

        before_fignums = set(plt.get_fignums())

        for _ in range(5):
            render_drawdown_chart(drawdown_curve)
            render_orders_chart(price_df, trades)
            render_trade_pnl_chart(price_df, trades)
            render_cumulative_return_chart(equity_curve)

        after_fignums = set(plt.get_fignums())

        assert after_fignums == before_fignums, \
            f"Figures accumulated after consecutive renders: {after_fignums - before_fignums}"