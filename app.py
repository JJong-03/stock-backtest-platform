"""Flask Web app for Stock Backtesting Platform (Phase 3 orchestration)."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import quote_plus

import pandas as pd
from flask import Flask, jsonify, render_template, request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from adapters.adapter import (
    derive_drawdown_curve,
    render_cumulative_return_chart,
    render_drawdown_chart,
    render_equity_chart,
    render_orders_chart,
    render_trade_pnl_chart,
)
from extensions import db
from job_launcher import create_job_launcher
from models import Strategy

app = Flask(__name__)
logger = logging.getLogger(__name__)


def _get_database_uri() -> str:
    """Resolve DB URI with DATABASE_URL priority, then DB_* fallback."""
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return database_url

    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT", "3306")
    db_name = os.getenv("DB_NAME")
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")

    if all([db_host, db_name, db_user, db_password]):
        return (
            f"mysql+pymysql://{quote_plus(db_user)}:{quote_plus(db_password)}"
            f"@{db_host}:{db_port}/{db_name}"
        )

    return "sqlite:///strategies.db"


log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)

app.config["SQLALCHEMY_DATABASE_URI"] = _get_database_uri()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

STRATEGY_MAP = {
    "RSI": {
        "name": "RSI (Relative Strength Index)",
        "default_params": {"period": 14, "oversold": 30, "overbought": 70},
    },
    "MACD": {
        "name": "MACD (Moving Average Convergence Divergence)",
        "default_params": {"fast": 12, "slow": 26, "signal": 9},
    },
    "RSI_MACD": {
        "name": "RSI + MACD (Combined)",
        "default_params": {
            "rsi_period": 14,
            "oversold": 30,
            "overbought": 70,
            "fast": 12,
            "slow": 26,
            "signal": 9,
        },
    },
}

_job_launcher = None


def _get_job_launcher():
    global _job_launcher
    if _job_launcher is None:
        _job_launcher = create_job_launcher()
    return _job_launcher


def _scan_tickers():
    if not os.path.isdir(DATA_DIR):
        return []
    return sorted(f for f in os.listdir(DATA_DIR) if f.endswith(".csv"))


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_iso8601_utc(value):
    if value is None:
        return None

    dt = value
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value

    if not isinstance(dt, datetime):
        return str(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


def _run_log(run_id: str, message: str, level: str = "info") -> None:
    log_func = getattr(logger, level, logger.info)
    log_func(f"[run_id={run_id}] {message}")


def _error_response(run_id: str, message: str, status_code: int, status: str = "FAILED"):
    return (
        jsonify(
            {
                "run_id": run_id,
                "status": status,
                "started_at": None,
                "completed_at": None,
                "error_message": message,
            }
        ),
        status_code,
    )


def _extract_rule_type(data: dict) -> str:
    explicit_rule_type = data.get("rule_type")
    strategy = data.get("strategy")

    if explicit_rule_type is not None and str(explicit_rule_type).strip() != "":
        return str(explicit_rule_type).strip().upper()

    if strategy is None or str(strategy).strip() == "":
        raise ValueError("Missing required field: rule_type (or strategy)")

    strategy_key = str(strategy).strip().upper()
    if strategy_key not in STRATEGY_MAP:
        raise ValueError(f"Unknown strategy: {strategy}")
    return strategy_key


def _build_run_payload(data: dict, run_id: str) -> dict:
    ticker = secure_filename(str(data.get("ticker", "")).strip())
    if not ticker:
        raise ValueError("Missing required field: ticker")
    if not ticker.endswith(".csv"):
        raise ValueError("ticker must be a CSV filename (e.g., AAPL.csv)")
    if len(ticker) > 10:
        raise ValueError("ticker filename is too long")

    csv_path = os.path.join(DATA_DIR, ticker)
    if not os.path.isfile(csv_path):
        raise ValueError(f"Data file not found: {ticker}")

    start_date = data.get("start_date")
    end_date = data.get("end_date")
    if start_date is None or str(start_date).strip() == "":
        raise ValueError("Missing required field: start_date")
    if end_date is None or str(end_date).strip() == "":
        raise ValueError("Missing required field: end_date")

    params = data.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError("params must be a JSON object")

    rule_type = _extract_rule_type(data)
    rule_id = data.get("rule_id")

    try:
        initial_capital = float(data.get("initial_capital", 100000))
    except (TypeError, ValueError) as exc:
        raise ValueError("initial_capital must be a number") from exc

    return {
        "run_id": run_id,
        "ticker": ticker,
        "rule_type": rule_type,
        "rule_id": None if rule_id in (None, "") else str(rule_id),
        "params": params,
        "params_json": json.dumps(params, ensure_ascii=False),
        "start_date": str(start_date),
        "end_date": str(end_date),
        "initial_capital": initial_capital,
        "fee_rate": data.get("fee_rate"),
        "slippage_bps": data.get("slippage_bps"),
        "position_size": data.get("position_size"),
        "size_type": data.get("size_type"),
        "direction": data.get("direction"),
        "timeframe": data.get("timeframe"),
    }


def _insert_pending_run(payload: dict) -> None:
    stmt = text(
        """
        INSERT INTO backtest_results (
            run_id,
            ticker,
            rule_type,
            rule_id,
            params_json,
            metrics_json,
            status,
            error_message,
            created_at
        ) VALUES (
            :run_id,
            :ticker,
            :rule_type,
            :rule_id,
            :params_json,
            :metrics_json,
            :status,
            NULL,
            :created_at
        )
        """
    )
    db.session.execute(
        stmt,
        {
            "run_id": payload["run_id"],
            "ticker": payload["ticker"],
            "rule_type": payload["rule_type"],
            "rule_id": payload["rule_id"],
            "params_json": payload["params_json"],
            "metrics_json": json.dumps({}, ensure_ascii=False),
            "status": "PENDING",
            "created_at": _utcnow_naive(),
        },
    )
    db.session.commit()


def _mark_pending_run_failed(run_id: str, error_message: str) -> None:
    stmt = text(
        """
        UPDATE backtest_results
           SET status = :failed,
               error_message = :error_message,
               completed_at = :completed_at
         WHERE run_id = :run_id
           AND status = :pending
        """
    )
    db.session.execute(
        stmt,
        {
            "failed": "FAILED",
            "pending": "PENDING",
            "error_message": error_message,
            "completed_at": _utcnow_naive(),
            "run_id": run_id,
        },
    )
    db.session.commit()


def _fetch_status_row(run_id: str):
    params = {"run_id": run_id}
    try:
        stmt = text(
            """
            SELECT run_id, ticker, status, started_at, completed_at, error_message,
                   metrics_json, equity_curve_json, trades_json, chart_base64
              FROM backtest_results
             WHERE run_id = :run_id
            """
        )
        return db.session.execute(stmt, params).mappings().first()
    except Exception:
        db.session.rollback()
        stmt = text(
            """
            SELECT run_id, ticker, status, started_at, completed_at, error_message,
                   metrics_json, equity_curve_json, trades_json
              FROM backtest_results
             WHERE run_id = :run_id
            """
        )
        return db.session.execute(stmt, params).mappings().first()


def _delete_succeeded_job_if_needed(run_id: str, status: str) -> None:
    if status != "SUCCEEDED":
        return

    try:
        launcher = _get_job_launcher()
    except Exception as exc:
        _run_log(run_id, f"Skipping success job cleanup (launcher init failed): {exc}", "warning")
        return

    if getattr(launcher, "mode", "").upper() != "K8S":
        return

    try:
        launcher.delete_for_run(run_id)
        _run_log(run_id, "Requested successful Job cleanup")
    except Exception as exc:
        _run_log(run_id, f"Failed to cleanup successful Job: {exc}", "warning")


@app.route("/")
def index():
    tickers = _scan_tickers()
    strategies = {k: v["name"] for k, v in STRATEGY_MAP.items()}
    return render_template("index.html", tickers=tickers, strategies=strategies)


@app.route("/run_backtest", methods=["POST"])
def run_backtest():
    run_id = str(uuid.uuid4())
    _run_log(run_id, "Backtest request received")

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error_response(run_id, "Request body must be valid JSON object", 400)

    try:
        payload = _build_run_payload(data, run_id)
    except ValueError as exc:
        _run_log(run_id, f"user_error: {exc}", "warning")
        return _error_response(run_id, str(exc), 400)

    try:
        _insert_pending_run(payload)
        _run_log(run_id, "Persisted PENDING state")
    except IntegrityError:
        db.session.rollback()
        _run_log(run_id, "system_error: database integrity error while inserting PENDING", "exception")
        return _error_response(run_id, "Database integrity error", 500)
    except Exception as exc:
        db.session.rollback()
        _run_log(run_id, f"system_error: failed to insert PENDING ({exc})", "exception")
        return _error_response(run_id, "Failed to persist run request", 500)

    try:
        launcher = _get_job_launcher()
        launcher.launch(payload)
        _run_log(run_id, f"Job launched via mode={getattr(launcher, 'mode', 'UNKNOWN')}")
    except Exception as exc:
        db.session.rollback()
        error_message = f"Job launch failed: {exc}"
        _run_log(run_id, f"system_error: {error_message}", "exception")

        try:
            _mark_pending_run_failed(run_id, error_message)
            _run_log(run_id, "Transitioned PENDING -> FAILED due to launch failure")
        except IntegrityError:
            db.session.rollback()
            _run_log(run_id, "Failed to persist launch failure (integrity error)", "exception")
        except Exception:
            db.session.rollback()
            _run_log(run_id, "Failed to persist launch failure", "exception")

        return _error_response(run_id, error_message, 500)

    return (
        jsonify(
            {
                "run_id": run_id,
                "status": "PENDING",
                "started_at": None,
                "completed_at": None,
                "error_message": None,
            }
        ),
        202,
    )


def _load_price_df(ticker: str) -> pd.DataFrame | None:
    """Load price DataFrame for chart rendering. Returns None on failure."""
    if not ticker:
        return None
    csv_path = os.path.join(DATA_DIR, ticker)
    if not os.path.isfile(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
        df.columns = [c.capitalize() for c in df.columns]
        return df.sort_index()
    except Exception as exc:
        logger.warning(f"Failed to load price data for {ticker}: {exc}")
        return None


def _derive_charts(equity_curve, trades, ticker: str | None) -> dict:
    """Derive all charts from canonical data. Returns dict with chart keys."""
    charts = {}

    drawdown_curve = derive_drawdown_curve(equity_curve) if equity_curve else []
    charts["_drawdown_curve"] = drawdown_curve
    charts["_equity_chart_base64"] = render_equity_chart(equity_curve)
    charts["drawdown_curve_base64"] = render_drawdown_chart(drawdown_curve)
    charts["cumulative_return_base64"] = render_cumulative_return_chart(equity_curve)

    price_df = _load_price_df(ticker) if ticker else None
    charts["portfolio_orders_base64"] = render_orders_chart(price_df, trades) if price_df is not None else None
    charts["trade_pnl_base64"] = render_trade_pnl_chart(price_df, trades) if price_df is not None else None

    return charts


@app.route("/status/<run_id>", methods=["GET"])
def get_status(run_id):
    _run_log(run_id, "Status request received")

    try:
        row = _fetch_status_row(run_id)
    except Exception as exc:
        db.session.rollback()
        _run_log(run_id, f"system_error: failed to query status ({exc})", "exception")
        return _error_response(run_id, "Failed to query status", 500)

    if row is None:
        return jsonify({"error": "Run not found"}), 404

    status = row["status"]
    _delete_succeeded_job_if_needed(run_id, status)

    response = {
        "run_id": row["run_id"],
        "status": status,
        "started_at": _to_iso8601_utc(row["started_at"]),
        "completed_at": _to_iso8601_utc(row["completed_at"]),
        "error_message": row["error_message"],
    }

    # Include result data when available (SUCCEEDED)
    if status == "SUCCEEDED":
        metrics_raw = row["metrics_json"]
        if metrics_raw:
            response["metrics"] = (
                json.loads(metrics_raw) if isinstance(metrics_raw, str) else metrics_raw
            )

        equity_raw = row["equity_curve_json"]
        equity_curve = None
        if equity_raw:
            equity_curve = json.loads(equity_raw) if isinstance(equity_raw, str) else equity_raw
            response["equity_curve"] = equity_curve

        trades_raw = row["trades_json"]
        trades = None
        if trades_raw:
            trades = json.loads(trades_raw) if isinstance(trades_raw, str) else trades_raw
            response["trades"] = trades

        # Derive charts from canonical data (Rule 1: adapter pattern)
        ticker = row.get("ticker")
        derived = _derive_charts(equity_curve, trades, ticker)
        response["drawdown_curve"] = derived.pop("_drawdown_curve", [])
        equity_chart = derived.pop("_equity_chart_base64", None)
        response["charts"] = {k: v for k, v in derived.items() if v is not None}

        # Equity chart: prefer DB-stored legacy field, fall back to derived
        chart_b64 = row.get("chart_base64")
        response["chart_base64"] = chart_b64 or equity_chart

    _run_log(run_id, f"Status response: {status}")
    return jsonify(response), 200


@app.route("/api/strategies", methods=["GET"])
def get_strategies():
    try:
        strategies = Strategy.query.order_by(Strategy.created_at.desc()).all()
        return jsonify([s.to_dict() for s in strategies]), 200
    except Exception as exc:
        db.session.rollback()
        logger.warning(f"strategies table may be missing; returning empty presets: {exc}")
        return jsonify([]), 200


@app.route("/api/strategies", methods=["POST"])
def create_strategy():
    data = request.get_json(force=True)
    if not data:
        return jsonify({"status": "error", "message": "Request body is empty"}), 400

    name = data.get("name")
    type_ = data.get("type")
    params = data.get("params")

    if not name or not type_ or params is None:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Missing required fields: name, type, params",
                }
            ),
            400,
        )

    strategy = Strategy(name=name, type=type_, params=params)
    try:
        db.session.add(strategy)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"status": "error", "message": "Strategy name already exists"}), 409
    except Exception:
        db.session.rollback()
        logger.exception("[run_id=n/a] Failed to save strategy")
        return jsonify({"status": "error", "message": "Database error"}), 500

    return jsonify(strategy.to_dict()), 201


@app.route("/api/strategies/<int:strategy_id>", methods=["DELETE"])
def delete_strategy(strategy_id):
    strategy = db.session.get(Strategy, strategy_id)
    if not strategy:
        return jsonify({"status": "error", "message": "Strategy not found"}), 404

    try:
        db.session.delete(strategy)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("[run_id=n/a] Failed to delete strategy")
        return jsonify({"status": "error", "message": "Database error"}), 500

    return jsonify({"status": "success", "message": "Strategy deleted"}), 200


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    # Local development only: production/K8s must initialize schema manually.
    with app.app_context():
        db.create_all()

    debug = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    app.run(host="0.0.0.0", port=5000, debug=debug)
