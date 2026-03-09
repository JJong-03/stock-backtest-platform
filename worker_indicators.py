"""Technical indicator computation and feature engineering for the worker.

Pure transformation functions that add indicator columns to a DataFrame
before engine execution.  No DB interaction, no side effects beyond
mutating the passed DataFrame (for _add_* helpers).
"""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from utils import safe_float as _safe_float, safe_int as _safe_int


# ---------------------------------------------------------------------------
# Individual indicator functions
# ---------------------------------------------------------------------------

def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gains = delta.where(delta > 0, 0.0)
    losses = -delta.where(delta < 0, 0.0)
    avg_gain = gains.rolling(window=period, min_periods=period).mean()
    avg_loss = losses.rolling(window=period, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(~avg_loss.eq(0), 100.0)
    return rsi


def _add_macd(df: pd.DataFrame, fast: int, slow: int, signal: int) -> None:
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()


def _add_sma(df: pd.DataFrame, period: int) -> None:
    df[f"sma_{period}"] = df["close"].rolling(window=period, min_periods=period).mean()


def _add_bollinger(df: pd.DataFrame, period: int, std_dev: float) -> None:
    middle = df["close"].rolling(window=period, min_periods=period).mean()
    std = df["close"].rolling(window=period, min_periods=period).std()
    df["bb_middle"] = middle
    df["bb_upper"] = middle + (std * std_dev)
    df["bb_lower"] = middle - (std * std_dev)


def _add_atr(df: pd.DataFrame, period: int) -> None:
    prev_close = df["close"].shift(1)
    tr_components = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    true_range = tr_components.max(axis=1)
    df["atr"] = true_range.rolling(window=period, min_periods=period).mean()


# ---------------------------------------------------------------------------
# Feature dispatcher
# ---------------------------------------------------------------------------

def add_rule_features(df: pd.DataFrame, canonical_rule_type: str, params: Dict[str, Any]) -> pd.DataFrame:
    """Add all technical indicator columns required by *canonical_rule_type*.

    Returns a copy of *df* with indicator columns appended.
    """
    result = df.copy()

    if canonical_rule_type == "RSI":
        period = _safe_int(params.get("period", 14), default=14)
        result["rsi"] = _rsi(result["close"], period)
    elif canonical_rule_type == "MACD":
        fast = _safe_int(params.get("fast", params.get("macd_fast", 12)), default=12)
        slow = _safe_int(params.get("slow", params.get("macd_slow", 26)), default=26)
        signal = _safe_int(params.get("signal", params.get("macd_signal", 9)), default=9)
        _add_macd(result, fast=fast, slow=slow, signal=signal)
    elif canonical_rule_type == "RSI_MACD":
        rsi_period = _safe_int(params.get("rsi_period", params.get("period", 14)), default=14)
        fast = _safe_int(params.get("macd_fast", params.get("fast", 12)), default=12)
        slow = _safe_int(params.get("macd_slow", params.get("slow", 26)), default=26)
        signal = _safe_int(params.get("macd_signal", params.get("signal", 9)), default=9)
        result["rsi"] = _rsi(result["close"], rsi_period)
        _add_macd(result, fast=fast, slow=slow, signal=signal)
    elif canonical_rule_type == "MOVING_AVERAGE_CROSS":
        fast_period = _safe_int(params.get("fast_period", 20), default=20)
        slow_period = _safe_int(params.get("slow_period", 50), default=50)
        _add_sma(result, fast_period)
        _add_sma(result, slow_period)
    elif canonical_rule_type == "BOLLINGER_BANDS":
        period = _safe_int(params.get("period", 20), default=20)
        std_dev = _safe_float(params.get("std_dev", 2.0), default=2.0)
        _add_bollinger(result, period=period, std_dev=std_dev)
    elif canonical_rule_type == "VOLUME_BREAKOUT":
        volume_ma_period = _safe_int(params.get("volume_ma_period", 20), default=20)
        result[f"volume_ma_{volume_ma_period}"] = result["volume"].rolling(
            window=volume_ma_period,
            min_periods=volume_ma_period,
        ).mean()
        result["price_change_pct"] = result["close"].pct_change()
    elif canonical_rule_type == "TREND_FOLLOWING":
        short_period = _safe_int(params.get("short_period", 20), default=20)
        medium_period = _safe_int(params.get("medium_period", 50), default=50)
        long_period = _safe_int(params.get("long_period", 200), default=200)
        _add_sma(result, short_period)
        _add_sma(result, medium_period)
        _add_sma(result, long_period)
    elif canonical_rule_type == "ATR_VOLATILITY":
        period = _safe_int(params.get("period", 14), default=14)
        _add_atr(result, period=period)

    return result
