"""
Adapter Layer for Day 3.9 Extended Response Schema.

This module provides helper functions to transform engine outputs
into the extended JSON schema defined in CLAUDE.md Section 4.

IMPORTANT: This module does NOT modify engine logic.
It only performs post-processing on engine outputs.
"""

import matplotlib
matplotlib.use("Agg")  # Must be before pyplot import

import io
import base64
import logging
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Union

from backtest.metrics import PerformanceMetrics
from utils import safe_float as _safe_float

# Module-level logger (does NOT depend on Flask)
logger = logging.getLogger(__name__)


# Default US market close time (16:00 ET = 21:00 UTC)
DEFAULT_DAILY_CLOSE_UTC = "21:00:00+00:00"


def safe_iso8601_utc(
    date_input: Union[str, datetime, pd.Timestamp, None],
    daily_close_utc: str = DEFAULT_DAILY_CLOSE_UTC
) -> Optional[str]:
    """
    Convert date/timestamp to ISO8601 UTC string.

    For daily data (timeframe='1d'):
    - If timestamp is timezone-aware -> convert to UTC
    - If timestamp is naive/date-only -> assign US market close (21:00 UTC)

    Args:
        date_input: Input date (string, datetime, or pd.Timestamp)
        daily_close_utc: Time to assign for date-only inputs (default: 21:00:00+00:00)

    Returns:
        ISO8601 formatted string: YYYY-MM-DDTHH:MM:SS+00:00
        Returns None if input cannot be parsed (schema safety).

    Note:
        On parse failure, emits a WARNING log and returns None.
        This ensures downstream consumers receive a valid ISO8601 string or null,
        never an unparseable raw value that violates the schema contract.
    """
    # Handle None/null input explicitly
    if date_input is None:
        logger.warning("safe_iso8601_utc received None input, returning None")
        return None

    if isinstance(date_input, str):
        # Parse string to timestamp
        try:
            ts = pd.Timestamp(date_input)
            # Check for NaT (Not a Timestamp) - happens with empty string
            if pd.isna(ts):
                logger.warning(
                    f"safe_iso8601_utc parsed NaT from string '{date_input}', returning None"
                )
                return None
        except Exception as e:
            logger.warning(
                f"safe_iso8601_utc failed to parse string '{date_input}': {e}"
            )
            return None  # Return None on parse failure (schema safety)
    elif isinstance(date_input, (datetime, pd.Timestamp)):
        ts = pd.Timestamp(date_input)
        # Check for NaT
        if pd.isna(ts):
            logger.warning("safe_iso8601_utc received NaT timestamp, returning None")
            return None
    else:
        # Handle other types (e.g., date objects)
        try:
            ts = pd.Timestamp(str(date_input))
            if pd.isna(ts):
                logger.warning(
                    f"safe_iso8601_utc parsed NaT from type {type(date_input).__name__}, returning None"
                )
                return None
        except Exception as e:
            logger.warning(
                f"safe_iso8601_utc failed to parse type {type(date_input).__name__}: {e}"
            )
            return None

    # Check if timestamp is timezone-aware
    if ts.tzinfo is not None:
        # Convert to UTC
        ts_utc = ts.tz_convert("UTC")
        return ts_utc.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    else:
        # Naive timestamp - assign daily close time (21:00 UTC)
        # Parse the time component
        time_parts = daily_close_utc.split("+")[0].split(":")
        hour = int(time_parts[0])
        minute = int(time_parts[1]) if len(time_parts) > 1 else 0
        second = int(time_parts[2]) if len(time_parts) > 2 else 0

        # Create UTC datetime
        dt = datetime(
            ts.year, ts.month, ts.day,
            hour, minute, second,
            tzinfo=timezone.utc
        )
        return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def build_equity_curve(portfolio_df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Build equity_curve from engine's portfolio_history DataFrame.

    Args:
        portfolio_df: DataFrame with 'value' column and DatetimeIndex

    Returns:
        List of {"date": "YYYY-MM-DD", "equity": float}
    """
    if portfolio_df is None or portfolio_df.empty:
        return []

    equity_curve = []
    for idx, row in portfolio_df.iterrows():
        equity_curve.append({
            "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10],
            "equity": round(float(row["value"]), 2)
        })

    return equity_curve


def derive_drawdown_curve(equity_curve: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Derive drawdown_curve from equity_curve.

    SPECIFICATION (AUTHORITATIVE):
    Returns NON-POSITIVE values (<= 0.0).
    A value of 0.0 indicates a new equity peak (no drawdown).
    Negative values indicate drawdown below the running peak.

    Examples:
    - drawdown_pct = 0.0   -> at peak (valid and expected)
    - drawdown_pct = -10.0 -> 10% below peak

    This aligns with standard financial definitions:
    1. Matches CLAUDE.md example: {"date": "2020-01-02", "drawdown_pct": -1.2}
    2. Follows industry convention (drawdown represents loss from peak)
    3. Enables intuitive UI coloring (negative = red, zero = green/neutral)

    Formula:
        drawdown_pct = ((current_equity - peak_equity) / peak_equity) * 100
    where peak_equity = running maximum of equity_curve

    Args:
        equity_curve: List of {"date": str, "equity": float}

    Returns:
        List of {"date": str, "drawdown_pct": float}
        - Values are NON-POSITIVE (<= 0.0)
        - Zero at new peaks, negative below peaks

    Note:
        - Handles edge cases (empty list, single point, monotonic increase)
        - Zero peak equity returns 0.0 drawdown (avoids division by zero)
        - NO epsilon hacks: 0.0 is mathematically correct at peaks
    """
    if not equity_curve:
        return []

    drawdown_curve = []
    peak_equity = 0.0

    for point in equity_curve:
        equity = point["equity"]

        # Update running peak
        if equity > peak_equity:
            peak_equity = equity

        # Calculate drawdown percentage (NEGATIVE values for loss from peak)
        if peak_equity > 0:
            drawdown_pct = ((equity - peak_equity) / peak_equity) * 100
        else:
            drawdown_pct = 0.0

        # Rounding rationale:
        # - Round to 2 decimals for UI readability and JSON stability
        # - Rounding can turn very small negatives (e.g., -0.001%) into 0.0
        # - This is acceptable: drawdown is defined as NON-POSITIVE (<= 0.0),
        #   so 0.0 is a valid value at or near peaks
        drawdown_curve.append({
            "date": point["date"],
            "drawdown_pct": round(drawdown_pct, 2)
        })

    return drawdown_curve


def derive_portfolio_curve(
    equity_curve: List[Dict[str, Any]],
    portfolio_df: pd.DataFrame
) -> List[Dict[str, Any]]:
    """
    Derive portfolio_curve showing cash vs position breakdown.

    Args:
        equity_curve: List of {"date": str, "equity": float}
        portfolio_df: DataFrame with 'cash' and 'holdings_value' columns

    Returns:
        List of {"date": str, "cash": float, "position": float, "total": float}

    Note:
        Returns empty list if portfolio_df lacks required columns.
    """
    if portfolio_df is None or portfolio_df.empty:
        return []

    if "cash" not in portfolio_df.columns or "holdings_value" not in portfolio_df.columns:
        return []

    portfolio_curve = []
    for idx, row in portfolio_df.iterrows():
        portfolio_curve.append({
            "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10],
            "cash": round(float(row["cash"]), 2),
            "position": round(float(row["holdings_value"]), 2),
            "total": round(float(row["value"]), 2)
        })

    return portfolio_curve


def normalize_trades(
    raw_trades: List[Dict[str, Any]],
    fee_rate: float = 0.001
) -> List[Dict[str, Any]]:
    """
    Normalize engine trades to the extended schema defined in CLAUDE.md.

    The engine outputs trades as a flat list of buy/sell actions.
    This function pairs them and computes P&L, holding period, etc.

    Args:
        raw_trades: Engine's trades list (from BacktestEngine.trades)
        fee_rate: Fee rate for fee calculation verification

    Returns:
        List of normalized trades matching CLAUDE.md schema:
        {
            "trade_no": int,
            "side": "BUY" | "SELL",
            "size": int,
            "entry_timestamp": ISO8601,
            "entry_price": float,
            "entry_fees": float,
            "exit_timestamp": ISO8601,
            "exit_price": float,
            "exit_fees": float,
            "pnl_abs": float,
            "pnl_pct": float,
            "holding_period": float (days)
        }

    Note:
        - Only completed round-trip trades (buy+sell pairs) are returned
        - Open positions at end of backtest are excluded
        - num_trades in API response should equal len(normalize_trades())
    """
    if not raw_trades:
        return []

    # Separate buy and sell trades
    buy_trades = [t for t in raw_trades if t.get("action") == "buy"]
    sell_trades = [t for t in raw_trades if t.get("action") == "sell"]

    normalized = []

    # Pair buy/sell trades
    for i, (buy, sell) in enumerate(zip(buy_trades, sell_trades)):
        # Extract timestamps
        entry_ts = buy.get("date")
        exit_ts = sell.get("date")

        # Convert to ISO8601
        entry_timestamp = safe_iso8601_utc(entry_ts)
        exit_timestamp = safe_iso8601_utc(exit_ts)

        # Get prices and size
        entry_price = float(buy.get("price", 0))
        exit_price = float(sell.get("price", 0))
        size = int(sell.get("quantity", buy.get("quantity", 0)))

        # Get fees from engine (or compute from fee_rate)
        entry_fees = float(buy.get("commission", entry_price * size * fee_rate))
        exit_fees = float(sell.get("commission", exit_price * size * fee_rate))

        # Calculate P&L
        # Note: Engine uses effective_price (with slippage), but we report market price
        # P&L formula from CLAUDE.md:
        # pnl_abs = (exit_price - entry_price) * size - entry_fees - exit_fees
        pnl_abs = (exit_price - entry_price) * size - entry_fees - exit_fees

        # P&L percentage
        # pnl_pct = pnl_abs / (entry_price * size) * 100
        entry_cost = entry_price * size
        pnl_pct = (pnl_abs / entry_cost * 100) if entry_cost > 0 else 0.0

        # Calculate holding period in days
        try:
            entry_dt = pd.Timestamp(entry_ts)
            exit_dt = pd.Timestamp(exit_ts)
            holding_seconds = (exit_dt - entry_dt).total_seconds()
            holding_period = holding_seconds / 86400  # Convert to days
        except Exception:
            holding_period = 0.0

        normalized.append({
            "trade_no": i,
            "side": "BUY",  # The trade type (entry side)
            "size": size,
            "entry_timestamp": entry_timestamp,
            "entry_price": round(entry_price, 2),
            "entry_fees": round(entry_fees, 2),
            "exit_timestamp": exit_timestamp,
            "exit_price": round(exit_price, 2),
            "exit_fees": round(exit_fees, 2),
            "pnl_abs": round(pnl_abs, 2),
            "pnl_pct": round(pnl_pct, 2),
            "holding_period": round(holding_period, 1)
        })

    return normalized


# ---------------------------------------------------------------------------
# Metrics builder (moved from worker.py — pure transformation, no DB)
# ---------------------------------------------------------------------------

def build_metrics_json(
    backtest_result: Dict[str, Any],
    drawdown_curve: Any,
    num_normalized_trades: int = 0,
) -> Dict[str, Any]:
    """Aggregate engine output + adapter-derived curves into canonical metrics.

    This is a **pure transformation** — no DB interaction.  The returned dict
    is the value that gets persisted as ``metrics_json`` by the worker.
    """
    metrics_report = PerformanceMetrics.generate_full_report(backtest_result)
    risk = metrics_report.get("risk_metrics", {})
    trading = metrics_report.get("trading_metrics", {})

    max_drawdown_pct = 0.0
    if drawdown_curve:
        max_drawdown_pct = abs(
            min(_safe_float(item.get("drawdown_pct", 0.0), 0.0) for item in drawdown_curve)
        )

    return {
        "total_return_pct": round(_safe_float(backtest_result.get("total_return_pct")), 4),
        "sharpe_ratio": round(_safe_float(risk.get("sharpe_ratio")), 6),
        "sortino_ratio": round(_safe_float(risk.get("sortino_ratio")), 6),
        "max_drawdown_pct": round(
            max_drawdown_pct if drawdown_curve else _safe_float(risk.get("max_drawdown_pct")),
            4,
        ),
        "num_trades": num_normalized_trades,
        "win_rate": round(_safe_float(trading.get("win_rate", backtest_result.get("win_rate"))), 4),
        "profit_factor": round(_safe_float(trading.get("profit_factor")), 6),
        "final_value": round(_safe_float(backtest_result.get("final_value")), 4),
    }


def render_equity_chart(equity_curve: List[Dict[str, Any]]) -> Optional[str]:
    """
    Render equity curve as a line chart.

    Args:
        equity_curve: List of {"date": str, "equity": float}

    Returns:
        Base64 encoded PNG string with data URI prefix, or None on failure.
    """
    if not equity_curve:
        logger.warning("render_equity_chart received empty equity_curve")
        return None

    fig = None
    try:
        dates = [point["date"] for point in equity_curve]
        equities = [point["equity"] for point in equity_curve]

        fig, ax = plt.subplots(figsize=(12, 4))
        ax.plot(range(len(dates)), equities, color='#4dabf7', linewidth=1.5)

        ax.set_facecolor('#0a0a0a')
        fig.patch.set_facecolor('#0a0a0a')
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_color('#333333')
        ax.spines['left'].set_color('#333333')
        ax.tick_params(colors='#888888', labelsize=9)
        ax.set_ylabel('Portfolio Value ($)', color='#888888', fontsize=10)
        ax.set_title('Equity Curve', color='#ff9900', fontsize=12,
                     fontfamily='monospace', loc='left', pad=10)
        ax.grid(True, alpha=0.15, color='#1e1e1e', linewidth=0.5)

        n_labels = min(10, len(dates))
        step = max(1, len(dates) // n_labels)
        ax.set_xticks(range(0, len(dates), step))
        ax.set_xticklabels(
            [dates[i] for i in range(0, len(dates), step)],
            rotation=45, ha='right', fontsize=8
        )

        plt.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=100, facecolor=fig.get_facecolor())
        buf.seek(0)

        b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        return f"data:image/png;base64,{b64}"

    except Exception as e:
        logger.warning(f"render_equity_chart failed: {e}")
        return None
    finally:
        if fig:
            plt.close(fig)


def render_drawdown_chart(drawdown_curve: List[Dict[str, Any]]) -> Optional[str]:
    """
    Render drawdown curve as a LINE chart (not filled area).

    Args:
        drawdown_curve: List of {"date": str, "drawdown_pct": float}
                        Values are NON-POSITIVE (<= 0.0).

    Returns:
        Base64 encoded PNG string with data URI prefix, or None on failure.

    Note:
        Uses Matplotlib Agg backend. Figure is closed after rendering.
    """
    if not drawdown_curve:
        logger.warning("render_drawdown_chart received empty drawdown_curve")
        return None

    fig = None
    try:
        dates = [point["date"] for point in drawdown_curve]
        drawdowns = [point["drawdown_pct"] for point in drawdown_curve]

        fig, ax = plt.subplots(figsize=(12, 4))

        # LINE chart (not filled area per spec)
        ax.plot(range(len(dates)), drawdowns, color='#ff6b6b', linewidth=1.5)

        # Zero reference line
        ax.axhline(y=0, color='#444444', linestyle='-', linewidth=0.8)

        # Styling (Bloomberg dark theme)
        ax.set_facecolor('#0a0a0a')
        fig.patch.set_facecolor('#0a0a0a')
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_color('#333333')
        ax.spines['left'].set_color('#333333')
        ax.tick_params(colors='#888888', labelsize=9)
        ax.set_ylabel('Drawdown (%)', color='#888888', fontsize=10)
        ax.set_title('Drawdown Curve', color='#ff9900', fontsize=12,
                     fontfamily='monospace', loc='left', pad=10)

        # X-axis labels (sample to avoid crowding)
        n_labels = min(10, len(dates))
        step = max(1, len(dates) // n_labels)
        ax.set_xticks(range(0, len(dates), step))
        ax.set_xticklabels(
            [dates[i] for i in range(0, len(dates), step)],
            rotation=45, ha='right', fontsize=8
        )

        # Grid
        ax.grid(True, alpha=0.15, color='#1e1e1e', linewidth=0.5)

        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=100, facecolor=fig.get_facecolor())
        buf.seek(0)

        b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        return f"data:image/png;base64,{b64}"

    except Exception as e:
        logger.warning(f"render_drawdown_chart failed: {e}")
        return None
    finally:
        if fig:
            plt.close(fig)


def render_orders_chart(
    price_df: pd.DataFrame,
    trades: List[Dict[str, Any]]
) -> Optional[str]:
    """
    Render orders chart: close price line with BUY/SELL markers.

    Args:
        price_df: DataFrame with DatetimeIndex and 'Close' column (daily OHLC data)
        trades: List of normalized trades with entry/exit timestamps

    Returns:
        Base64 encoded PNG string with data URI prefix, or None on failure.

    Note:
        - BUY markers: green triangle up (^) at entry dates
        - SELL markers: red triangle down (v) at exit dates
        - Legend: fixed at upper-left (loc="upper left")
        - Separate figure (no subplots)
    """
    if price_df is None or price_df.empty:
        logger.warning("render_orders_chart received empty price_df")
        return None

    if "Close" not in price_df.columns:
        logger.warning("render_orders_chart: price_df missing 'Close' column")
        return None

    fig = None
    try:
        date_labels = []
        for d in price_df.index:
            if hasattr(d, 'strftime'):
                date_labels.append(d.strftime('%Y-%m-%d'))
            else:
                date_labels.append(str(d)[:10])

        closes = price_df['Close'].values
        x_indices = list(range(len(price_df)))

        fig, ax = plt.subplots(figsize=(12, 5))

        ax.plot(x_indices, closes, color='#4dabf7', linewidth=1.2, label='Close')

        # Overlay BUY/SELL markers
        buy_x, buy_y = [], []
        sell_x, sell_y = [], []

        for trade in (trades or []):
            entry_ts = trade.get('entry_timestamp', '')
            entry_date = entry_ts[:10] if entry_ts else ''
            if entry_date in date_labels:
                idx = date_labels.index(entry_date)
                buy_x.append(idx)
                buy_y.append(closes[idx])

            exit_ts = trade.get('exit_timestamp', '')
            exit_date = exit_ts[:10] if exit_ts else ''
            if exit_date in date_labels:
                idx = date_labels.index(exit_date)
                sell_x.append(idx)
                sell_y.append(closes[idx])

        if buy_x:
            ax.scatter(buy_x, buy_y, marker='^', s=80, color='#51cf66',
                       zorder=5, label='BUY', edgecolors='white', linewidths=0.5)
        if sell_x:
            ax.scatter(sell_x, sell_y, marker='v', s=80, color='#ff6b6b',
                       zorder=5, label='SELL', edgecolors='white', linewidths=0.5)

        # Styling
        ax.set_facecolor('#0a0a0a')
        fig.patch.set_facecolor('#0a0a0a')
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_color('#333333')
        ax.spines['left'].set_color('#333333')
        ax.tick_params(colors='#888888', labelsize=9)
        ax.set_ylabel('Price ($)', color='#888888', fontsize=10)
        ax.set_title('Orders (Buy / Sell)',
                     color='#ff9900', fontsize=12, fontfamily='monospace',
                     loc='left', pad=10)
        ax.legend(loc='upper left', framealpha=0.7, fontsize=9)
        ax.grid(True, alpha=0.15, color='#1e1e1e', linewidth=0.5)

        # X-axis labels
        n_labels = min(10, len(date_labels))
        step = max(1, len(date_labels) // n_labels)
        ax.set_xticks(range(0, len(date_labels), step))
        ax.set_xticklabels(
            [date_labels[i] for i in range(0, len(date_labels), step)],
            rotation=45, ha='right', fontsize=8
        )

        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=100, facecolor=fig.get_facecolor())
        buf.seek(0)

        b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        return f"data:image/png;base64,{b64}"

    except Exception as e:
        logger.warning(f"render_orders_chart failed: {e}")
        return None
    finally:
        if fig:
            plt.close(fig)


def render_trade_pnl_chart(
    price_df: pd.DataFrame,
    trades: List[Dict[str, Any]]
) -> Optional[str]:
    """
    Render trade PnL scatter chart: per-trade P&L (%) at exit dates.

    Args:
        price_df: DataFrame with DatetimeIndex (for date alignment)
        trades: List of normalized trades with exit timestamps and pnl_pct

    Returns:
        Base64 encoded PNG string with data URI prefix, or None on failure.

    Note:
        - Green circles: profit trades (pnl_pct >= 0)
        - Red circles: loss trades (pnl_pct < 0)
        - Zero reference line
        - Legend: fixed at upper-left (loc="upper left")
        - Separate figure (no subplots)
    """
    if price_df is None or price_df.empty:
        logger.warning("render_trade_pnl_chart received empty price_df")
        return None

    fig = None
    try:
        date_labels = []
        for d in price_df.index:
            if hasattr(d, 'strftime'):
                date_labels.append(d.strftime('%Y-%m-%d'))
            else:
                date_labels.append(str(d)[:10])

        fig, ax = plt.subplots(figsize=(12, 5))

        # Separate profit/loss for legend
        profit_x, profit_y = [], []
        loss_x, loss_y = [], []

        for trade in (trades or []):
            exit_ts = trade.get('exit_timestamp', '')
            exit_date = exit_ts[:10] if exit_ts else ''
            pnl = trade.get('pnl_pct', 0)

            if exit_date in date_labels:
                idx = date_labels.index(exit_date)
                if pnl >= 0:
                    profit_x.append(idx)
                    profit_y.append(pnl)
                else:
                    loss_x.append(idx)
                    loss_y.append(pnl)

        if profit_x:
            ax.scatter(profit_x, profit_y, color='#51cf66', s=60, zorder=5,
                       edgecolors='white', linewidths=0.5, label='Profit')
        if loss_x:
            ax.scatter(loss_x, loss_y, color='#ff6b6b', s=60, zorder=5,
                       edgecolors='white', linewidths=0.5, label='Loss')

        # Zero reference line
        ax.axhline(y=0, color='#666666', linestyle='-', linewidth=1)

        # Styling
        ax.set_facecolor('#0a0a0a')
        fig.patch.set_facecolor('#0a0a0a')
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_color('#333333')
        ax.spines['left'].set_color('#333333')
        ax.tick_params(colors='#888888', labelsize=9)
        ax.set_ylabel('Trade PnL (%)', color='#888888', fontsize=10)
        ax.set_xlabel('Date', color='#888888', fontsize=10)
        ax.set_title('Trade PnL (%)',
                     color='#ff9900', fontsize=12, fontfamily='monospace',
                     loc='left', pad=10)
        if profit_x or loss_x:
            ax.legend(loc='upper left', framealpha=0.7, fontsize=9)
        ax.grid(True, alpha=0.15, color='#1e1e1e', linewidth=0.5)

        # X-axis labels
        n_labels = min(10, len(date_labels))
        step = max(1, len(date_labels) // n_labels)
        ax.set_xticks(range(0, len(date_labels), step))
        ax.set_xticklabels(
            [date_labels[i] for i in range(0, len(date_labels), step)],
            rotation=45, ha='right', fontsize=8
        )

        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=100, facecolor=fig.get_facecolor())
        buf.seek(0)

        b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        return f"data:image/png;base64,{b64}"

    except Exception as e:
        logger.warning(f"render_trade_pnl_chart failed: {e}")
        return None
    finally:
        if fig:
            plt.close(fig)


def render_cumulative_return_chart(
    equity_curve: List[Dict[str, Any]]
) -> Optional[str]:
    """
    Render cumulative return (%) over time as a line chart.

    Definition:
        E0 = first equity value
        cum_return_pct(t) = (E(t) / E0 - 1) * 100

    Args:
        equity_curve: List of {"date": str, "equity": float}

    Returns:
        Base64 encoded PNG string with data URI prefix, or None on failure.

    Note:
        Uses Matplotlib Agg backend. Figure is closed after rendering.
    """
    if not equity_curve:
        logger.warning("render_cumulative_return_chart received empty equity_curve")
        return None

    fig = None
    try:
        dates = [point["date"] for point in equity_curve]
        equities = [point["equity"] for point in equity_curve]

        e0 = equities[0]
        if e0 == 0:
            logger.warning("render_cumulative_return_chart: initial equity is 0")
            return None

        cum_returns = [((e / e0) - 1) * 100 for e in equities]

        fig, ax = plt.subplots(figsize=(12, 4))

        # Line chart
        ax.plot(range(len(dates)), cum_returns, color='#51cf66', linewidth=1.5)

        # Zero reference line
        ax.axhline(y=0, color='#666666', linestyle='--', linewidth=0.8)

        # Styling (Bloomberg dark theme)
        ax.set_facecolor('#0a0a0a')
        fig.patch.set_facecolor('#0a0a0a')
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_color('#333333')
        ax.spines['left'].set_color('#333333')
        ax.tick_params(colors='#888888', labelsize=9)
        ax.set_ylabel('Cumulative Return (%)', color='#888888', fontsize=10)
        ax.set_title('Cumulative Return Over Time', color='#ff9900', fontsize=12,
                     fontfamily='monospace', loc='left', pad=10)

        # X-axis labels (sample to avoid crowding)
        n_labels = min(10, len(dates))
        step = max(1, len(dates) // n_labels)
        ax.set_xticks(range(0, len(dates), step))
        ax.set_xticklabels(
            [dates[i] for i in range(0, len(dates), step)],
            rotation=45, ha='right', fontsize=8
        )

        # Grid
        ax.grid(True, alpha=0.15, color='#1e1e1e', linewidth=0.5)

        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=100, facecolor=fig.get_facecolor())
        buf.seek(0)

        b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        return f"data:image/png;base64,{b64}"

    except Exception as e:
        logger.warning(f"render_cumulative_return_chart failed: {e}")
        return None
    finally:
        if fig:
            plt.close(fig)
