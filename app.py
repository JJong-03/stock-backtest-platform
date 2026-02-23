"""
Flask Web Dashboard for Stock Backtesting Platform
Controller layer only -- does NOT modify engine logic.

Day 3.9: Extended request/response schema with VectorBT-style dashboard support.
"""

import matplotlib
matplotlib.use("Agg")

import io
import os
import uuid
import base64
import logging
from urllib.parse import quote_plus

import pandas as pd
import matplotlib.pyplot as plt
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError

from backtest.engine import BacktestEngine
from backtest.metrics import PerformanceMetrics
from extracted.features.technical_indicators import TechnicalIndicators
from rules.technical_rules import RSIRule, MACDRule, RsiMacdRule
from rules.base_rule import RuleMetadata

from extensions import db
from models import Strategy

# Adapter layer imports (Day 3.9)
from adapters.adapter import (
    build_equity_curve,
    derive_drawdown_curve,
    derive_portfolio_curve,
    normalize_trades,
    render_drawdown_chart,
    render_orders_chart,
    render_trade_pnl_chart,
    render_cumulative_return_chart,
)

app = Flask(__name__)
logger = logging.getLogger(__name__)


def _get_database_uri():
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
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# --- Database configuration ---
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
            "rsi_period": 14, "oversold": 30, "overbought": 70,
            "fast": 12, "slow": 26, "signal": 9,
        },
    },
}


def _scan_tickers():
    """Dynamically scan data/ directory for available CSV files."""
    if not os.path.isdir(DATA_DIR):
        return []
    files = sorted(f for f in os.listdir(DATA_DIR) if f.endswith(".csv"))
    return files


def _build_strategy(strategy_key, rule, df):
    """Build a strategy_func wrapper that bridges Rule.evaluate() -> engine signal."""
    def strategy_func(row):
        signal = rule.evaluate(row)
        if signal.action in ("buy", "sell"):
            return signal.action
        return None
    return strategy_func


def _render_chart(portfolio_df, ticker, run_id):
    """Render portfolio value chart to Base64 PNG string. No disk I/O."""
    fig = None
    try:
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.plot(portfolio_df.index, portfolio_df["value"],
                color="#ff9900", linewidth=1.0)
        ax.fill_between(portfolio_df.index, portfolio_df["value"],
                        alpha=0.08, color="#ff9900")
        ax.set_title(f"{ticker}", fontsize=11, color="#ff9900",
                     fontfamily="monospace", loc="left", pad=8)
        ax.set_xlabel("")
        ax.set_ylabel("VALUE ($)", color="#666666", fontsize=8,
                      fontfamily="monospace")
        ax.tick_params(colors="#555555", labelsize=8)
        ax.set_facecolor("#000000")
        fig.patch.set_facecolor("#000000")
        ax.grid(True, alpha=0.15, color="#1e1e1e", linewidth=0.5)
        for spine in ax.spines.values():
            spine.set_color("#1e1e1e")
        fig.tight_layout(pad=1.5)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120, facecolor=fig.get_facecolor())
        buf.seek(0)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    finally:
        if fig:
            plt.close(fig)


def _build_error_response(run_id, message, status_code=400):
    """Build standardized error response with all required fields.

    ALL response keys must always exist per CLAUDE.md contract.
    Includes backward-compatibility keys for older clients.
    """
    return jsonify({
        "run_id": run_id,
        "status": "failed",
        "error_message": message,
        "metrics": {
            "total_return_pct": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "num_trades": 0
        },
        "equity_curve": [],
        "drawdown_curve": [],
        "trades": [],
        "portfolio_curve": [],
        "chart_base64": None,  # Must always exist per contract
        "chart_image": None,   # Backward compatibility for older clients
        # Day 3.9+ charts object (additive)
        "charts": {
            "drawdown_curve_base64": None,
            "portfolio_orders_base64": None,
            "trade_pnl_base64": None,
            "cumulative_return_base64": None
        }
    }), status_code


def _is_empty_or_null(value):
    """Check if a value is None, empty string, or whitespace-only."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


@app.route("/")
def index():
    tickers = _scan_tickers()
    strategies = {k: v["name"] for k, v in STRATEGY_MAP.items()}
    return render_template("index.html", tickers=tickers, strategies=strategies)


@app.route("/run_backtest", methods=["POST"])
def run_backtest():
    # Use provided run_id or generate new one
    data = request.get_json(force=True) or {}
    run_id = data.get("run_id") or str(uuid.uuid4())
    logger.info(f"[run_id={run_id}] Backtest request received")

    try:
        if not data:
            return _build_error_response(run_id, "Request body is empty", 400)

        ticker_file = data.get("ticker")
        strategy_key = data.get("strategy")
        params = data.get("params", {})

        # --- FIX #2: Explicit null/empty check for dates BEFORE parsing ---
        # This prevents TypeError from pd.Timestamp(None) leaking as HTTP 500
        start_date_raw = data.get("start_date")
        end_date_raw = data.get("end_date")

        if _is_empty_or_null(start_date_raw):
            return _build_error_response(
                run_id, "Missing required parameter: start_date", 400
            )

        if _is_empty_or_null(end_date_raw):
            return _build_error_response(
                run_id, "Missing required parameter: end_date", 400
            )

        # --- Extended parameters with defaults (Day 3.9) ---
        initial_capital = float(data.get("initial_capital", 100000))
        fee_rate = float(data.get("fee_rate", 0.001))

        # FIX #1: Slippage strictly from slippage_bps input
        # Default slippage_bps=0 means slippage_decimal=0.0 (not 0.002)
        slippage_bps = float(data.get("slippage_bps", 0))

        position_size = float(data.get("position_size", 10000))
        size_type = data.get("size_type", "value")
        direction = data.get("direction", "longonly")
        timeframe = data.get("timeframe", "1d")

        # --- Extended parameter validation ---
        if fee_rate < 0:
            return _build_error_response(
                run_id, "fee_rate must be >= 0", 400
            )

        # FIX #1: Validate slippage_bps >= 0
        if slippage_bps < 0:
            return _build_error_response(
                run_id, "slippage_bps must be >= 0", 400
            )

        if position_size <= 0:
            return _build_error_response(
                run_id, "position_size must be > 0", 400
            )

        # Timeframe validation - only "1d" supported in Day 3.9
        if timeframe in ("5m", "1h"):
            return _build_error_response(
                run_id,
                f"Timeframe '{timeframe}' is not supported in Day 3.9. Only '1d' is available.",
                400
            )

        if timeframe != "1d":
            return _build_error_response(
                run_id,
                f"Invalid timeframe: {timeframe}. Supported values: 1d",
                400
            )

        # Direction validation - only "longonly" supported in Day 3.9
        if direction == "longshort":
            return _build_error_response(
                run_id,
                "Direction 'longshort' is not supported in Day 3.9. Only 'longonly' is available.",
                400
            )

        if direction not in ("longonly", "longshort"):
            return _build_error_response(
                run_id,
                f"Invalid direction: {direction}. Supported values: longonly, longshort",
                400
            )

        # --- Input validation (400 errors) ---
        if not ticker_file:
            return _build_error_response(run_id, "Missing 'ticker' field", 400)

        # Sanitize filename to prevent path traversal
        ticker_file = secure_filename(ticker_file)

        if strategy_key not in STRATEGY_MAP:
            return _build_error_response(
                run_id, f"Unknown strategy: {strategy_key}", 400
            )

        csv_path = os.path.join(DATA_DIR, ticker_file)
        if not os.path.isfile(csv_path):
            return _build_error_response(
                run_id, f"Data file not found: {ticker_file}", 400
            )

        ticker_name = ticker_file.replace(".csv", "")
        logger.info(f"[run_id={run_id}] Running {strategy_key} on {ticker_name}")

        # --- Load CSV + Date conversion & timezone normalization ---
        try:
            df = pd.read_csv(csv_path)
            df["Date"] = pd.to_datetime(df["Date"])
            df["Date"] = df["Date"].dt.tz_localize(None)
        except Exception as e:
            logger.exception(f"[run_id={run_id}] Failed to load or parse CSV data")
            return _build_error_response(
                run_id, "Failed to load or parse CSV data", 500
            )

        # --- FIX #2: Date parsing with explicit error handling ---
        # Parse dates AFTER null check, treat parse errors as HTTP 400
        try:
            start_date = pd.Timestamp(start_date_raw)
        except (ValueError, TypeError) as e:
            return _build_error_response(
                run_id, f"Invalid start_date format: {start_date_raw}", 400
            )

        try:
            end_date = pd.Timestamp(end_date_raw)
        except (ValueError, TypeError) as e:
            return _build_error_response(
                run_id, f"Invalid end_date format: {end_date_raw}", 400
            )

        if start_date > end_date:
            return _build_error_response(
                run_id, "start_date must be before end_date", 400
            )

        df = df[(df["Date"] >= start_date) & (df["Date"] <= end_date)]

        if df.empty:
            return _build_error_response(
                run_id, "No data in selected date range", 400
            )

        df = df.set_index("Date")

        # --- Calculate indicators & build rule ---
        if strategy_key == "RSI":
            period = int(params.get("period", 14))
            oversold = float(params.get("oversold", 30))
            overbought = float(params.get("overbought", 70))
            df["rsi"] = TechnicalIndicators.rsi(df["close"], period=period)
            meta = RuleMetadata(rule_id=f"WEB_RSI_{run_id[:8]}",
                                name="RSI Strategy", description="RSI Web",
                                source="technical")
            rule = RSIRule(metadata=meta, period=period,
                          oversold=oversold, overbought=overbought)

        elif strategy_key == "MACD":
            fast = int(params.get("fast", 12))
            slow = int(params.get("slow", 26))
            sig = int(params.get("signal", 9))
            macd_line, signal_line, histogram = TechnicalIndicators.macd(
                df["close"], fast=fast, slow=slow, signal=sig)
            df["macd"] = macd_line
            df["macd_signal"] = signal_line
            df["macd_histogram"] = histogram
            meta = RuleMetadata(rule_id=f"WEB_MACD_{run_id[:8]}",
                                name="MACD Strategy", description="MACD Web",
                                source="technical")
            rule = MACDRule(metadata=meta)

        elif strategy_key == "RSI_MACD":
            rsi_period = int(params.get("rsi_period", 14))
            oversold = float(params.get("oversold", 30))
            overbought = float(params.get("overbought", 70))
            fast = int(params.get("fast", 12))
            slow = int(params.get("slow", 26))
            sig = int(params.get("signal", 9))

            df["rsi"] = TechnicalIndicators.rsi(df["close"], period=rsi_period)
            macd_line, signal_line, histogram = TechnicalIndicators.macd(
                df["close"], fast=fast, slow=slow, signal=sig)
            df["macd"] = macd_line
            df["macd_signal"] = signal_line
            df["macd_histogram"] = histogram

            meta = RuleMetadata(rule_id=f"WEB_RSI_MACD_{run_id[:8]}",
                                name="RSI+MACD Strategy", description="RSI+MACD Web",
                                source="technical")
            rule = RsiMacdRule(metadata=meta, rsi_period=rsi_period,
                               rsi_oversold=oversold, rsi_overbought=overbought,
                               macd_fast=fast, macd_slow=slow, macd_signal=sig)

        # --- Run backtest (engine untouched) ---
        # FIX #1: Convert slippage from basis points to decimal
        # slippage_bps=0 => slippage_decimal=0.0 (strict contract compliance)
        slippage_decimal = slippage_bps / 10000.0

        strategy_func = _build_strategy(strategy_key, rule, df)
        engine = BacktestEngine(
            initial_capital=initial_capital,
            commission=fee_rate,
            slippage=slippage_decimal
        )
        result = engine.run(df, strategy_func, ticker=ticker_name)

        if "error" in result:
            return _build_error_response(run_id, result["error"], 400)

        # --- Performance metrics ---
        # FIX #5: Compute Sharpe Ratio with risk_free_rate=0.0 per CLAUDE.md spec
        # DO NOT modify backtest/metrics.py - override via argument only
        portfolio_df = result["portfolio_history"]
        daily_returns = portfolio_df['value'].pct_change().dropna()

        # Compute Sharpe with risk_free_rate=0.0 (CLAUDE.md requirement)
        sharpe_ratio = PerformanceMetrics.calculate_sharpe_ratio(
            daily_returns,
            risk_free_rate=0.0  # STRICT: zero risk-free rate per spec
        )

        # Compute Sortino with risk_free_rate=0.0 for consistency
        sortino_ratio = PerformanceMetrics.calculate_sortino_ratio(
            daily_returns,
            risk_free_rate=0.0
        )

        # Get max drawdown info
        drawdown_info = PerformanceMetrics.calculate_max_drawdown(portfolio_df['value'])

        # Get win rate and profit factor
        win_info = PerformanceMetrics.calculate_win_rate(result['trades'])

        # Calculate Calmar ratio
        days = len(portfolio_df)
        years = days / 252.0 if days > 0 else 1.0
        calmar_ratio = PerformanceMetrics.calculate_calmar_ratio(
            result['total_return'],
            drawdown_info['max_drawdown'],
            years
        )

        # --- Build extended response (Day 3.9) ---
        # Build equity_curve from portfolio history
        equity_curve = build_equity_curve(portfolio_df)

        # Derive drawdown_curve from equity_curve (adapter layer)
        drawdown_curve = derive_drawdown_curve(equity_curve)

        # Derive portfolio_curve from portfolio history
        portfolio_curve = derive_portfolio_curve(equity_curve, portfolio_df)

        # Normalize trades to extended schema
        trades = normalize_trades(result["trades"], fee_rate=fee_rate)

        # --- Chart (in-memory Base64) ---
        chart_b64 = _render_chart(portfolio_df, ticker_name, run_id)

        # --- Day 3.9+ Charts (drawdown + portfolio plot) ---
        # Render drawdown curve chart
        drawdown_chart_b64 = render_drawdown_chart(drawdown_curve)

        # Prepare price data for portfolio plot (needs Close column)
        # Handle both 'Close' and 'close' column names
        price_df_for_plot = df.copy()
        if 'close' in price_df_for_plot.columns and 'Close' not in price_df_for_plot.columns:
            price_df_for_plot['Close'] = price_df_for_plot['close']

        # Render orders chart (close price + BUY/SELL markers)
        orders_chart_b64 = render_orders_chart(price_df_for_plot, trades)

        # Render trade PnL chart (scatter of per-trade P&L %)
        trade_pnl_chart_b64 = render_trade_pnl_chart(price_df_for_plot, trades)

        # Render cumulative return chart (Day 3.9+)
        cumulative_return_b64 = render_cumulative_return_chart(equity_curve)

        # --- Build response using extended schema ---
        # FIX #3: num_trades = len(trades) (paired trades count, not raw actions)
        response = {
            # Required top-level keys
            "run_id": run_id,
            "status": "completed",
            "error_message": None,

            # Metrics (Day 3.9 required)
            "metrics": {
                "total_return_pct": round(float(result["total_return_pct"]), 2),
                "sharpe_ratio": round(float(sharpe_ratio), 2),  # FIX #5: Using risk_free_rate=0.0
                "max_drawdown_pct": round(float(drawdown_info["max_drawdown_pct"]), 2),
                "num_trades": len(trades),  # FIX #3: Paired trades count
                # Additional metrics (available from engine/metrics)
                "ticker": ticker_name,
                "initial_capital": float(result["initial_capital"]),
                "final_value": round(float(result["final_value"]), 2),
                "win_rate": round(float(win_info["win_rate"]), 1),
                "sortino_ratio": round(float(sortino_ratio), 2),
                "calmar_ratio": round(float(calmar_ratio), 2),
                "profit_factor": round(float(win_info["profit_factor"]), 2),
            },

            # Time-series data (Day 3.9 required)
            "equity_curve": equity_curve,
            "drawdown_curve": drawdown_curve,
            "portfolio_curve": portfolio_curve,

            # Trade details
            "trades": trades,

            # Chart (legacy + Day 3.9)
            "chart_base64": chart_b64,
            # Backward compatibility alias
            "chart_image": chart_b64,

            # Day 3.9+ charts object (additive)
            "charts": {
                "drawdown_curve_base64": drawdown_chart_b64,
                "portfolio_orders_base64": orders_chart_b64,
                "trade_pnl_base64": trade_pnl_chart_b64,
                "cumulative_return_base64": cumulative_return_b64
            }
        }

        logger.info(f"[run_id={run_id}] Backtest completed: "
                     f"return={result['total_return_pct']:.2f}%")
        return jsonify(response), 200

    except Exception as e:
        logger.exception(f"[run_id={run_id}] Unhandled error")
        return _build_error_response(run_id, "Internal server error", 500)


@app.route("/api/strategies", methods=["GET"])
def get_strategies():
    strategies = Strategy.query.order_by(Strategy.created_at.desc()).all()
    return jsonify([s.to_dict() for s in strategies]), 200


@app.route("/api/strategies", methods=["POST"])
def create_strategy():
    data = request.get_json(force=True)
    if not data:
        return jsonify({"status": "error", "message": "Request body is empty"}), 400

    name = data.get("name")
    type_ = data.get("type")
    params = data.get("params")

    if not name or not type_ or params is None:
        return jsonify({"status": "error",
                        "message": "Missing required fields: name, type, params"}), 400

    strategy = Strategy(name=name, type=type_, params=params)
    try:
        db.session.add(strategy)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"status": "error",
                        "message": "Strategy name already exists"}), 409
    except Exception as e:
        db.session.rollback()
        logger.exception("Failed to save strategy")
        return jsonify({"status": "error",
                        "message": "Database error"}), 500

    return jsonify(strategy.to_dict()), 201


@app.route("/api/strategies/<int:strategy_id>", methods=["DELETE"])
def delete_strategy(strategy_id):
    strategy = db.session.get(Strategy, strategy_id)
    if not strategy:
        return jsonify({"status": "error", "message": "Strategy not found"}), 404

    try:
        db.session.delete(strategy)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.exception("Failed to delete strategy")
        return jsonify({"status": "error", "message": "Database error"}), 500

    return jsonify({"status": "success", "message": "Strategy deleted"}), 200


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    debug = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    app.run(host="0.0.0.0", port=5000, debug=debug)
