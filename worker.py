"""Phase 3 worker entrypoint: env -> backtest -> MySQL persist."""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib.parse import quote_plus

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from adapters.adapter import build_equity_curve, derive_drawdown_curve, normalize_trades
from backtest.engine import BacktestEngine
from backtest.metrics import PerformanceMetrics
from rules.base_rule import RuleMetadata
from rules.technical_rules import (
    ATRVolatilityRule,
    BollingerBandsRule,
    MACDRule,
    MovingAverageCrossRule,
    RSIRule,
    RsiMacdRule,
    TrendFollowingRule,
    VolumeBreakoutRule,
)


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"


class UnknownRuleTypeError(ValueError):
    """Raised when RULE_TYPE cannot be mapped to an existing rule class."""


RULE_CLASS_REGISTRY = {
    "RSI": RSIRule,
    "MACD": MACDRule,
    "RSI_MACD": RsiMacdRule,
    "MOVING_AVERAGE_CROSS": MovingAverageCrossRule,
    "BOLLINGER_BANDS": BollingerBandsRule,
    "VOLUME_BREAKOUT": VolumeBreakoutRule,
    "TREND_FOLLOWING": TrendFollowingRule,
    "ATR_VOLATILITY": ATRVolatilityRule,
}

RULE_TYPE_ALIASES = {
    "RSIMACD": "RSI_MACD",
    "RSI+MACD": "RSI_MACD",
    "MA_CROSS": "MOVING_AVERAGE_CROSS",
    "MOVINGAVERAGECROSS": "MOVING_AVERAGE_CROSS",
}


logger = logging.getLogger(__name__)


def _configure_logging(run_id: str) -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format=f"%(asctime)s [%(levelname)s] [run_id={run_id}] %(message)s",
        force=True,
    )


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _commit_with_rollback(session: Session, context: str) -> None:
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        logger.exception("IntegrityError during %s", context)
        raise
    except Exception:
        session.rollback()
        logger.exception("Database error during %s", context)
        raise


def _get_database_uri() -> str:
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

    raise RuntimeError("DATABASE_URL or DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD is required")


def _create_session_factory(database_uri: str) -> sessionmaker:
    if database_uri.startswith("sqlite"):
        engine = create_engine(
            database_uri,
            future=True,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )
    else:
        engine = create_engine(database_uri, future=True, pool_pre_ping=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(result) or math.isinf(result):
        return default
    return result


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or str(value).strip() == "":
        raise ValueError(f"Missing required env var: {name}")
    return str(value).strip()


def _sanitize_ticker(ticker: str) -> str:
    filename = os.path.basename(ticker)
    if filename != ticker:
        raise ValueError("TICKER must be a plain CSV filename")
    if not filename.endswith(".csv"):
        raise ValueError("TICKER must end with .csv")
    if len(filename) > 10:
        raise ValueError("TICKER filename is too long")
    return filename


def _read_inputs() -> Dict[str, Any]:
    ticker = _sanitize_ticker(_require_env("TICKER"))
    rule_type = _require_env("RULE_TYPE")
    params_json_raw = _require_env("PARAMS_JSON")
    start_date = _require_env("START_DATE")
    end_date = _require_env("END_DATE")

    try:
        params = json.loads(params_json_raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"PARAMS_JSON must be valid JSON object: {exc}") from exc
    if not isinstance(params, dict):
        raise ValueError("PARAMS_JSON must decode to JSON object")

    initial_capital = _safe_float(os.getenv("INITIAL_CAPITAL", "100000"), default=100000.0)
    fee_rate = _safe_float(os.getenv("FEE_RATE", "0.001"), default=0.001)

    slippage_bps_raw = os.getenv("SLIPPAGE_BPS")
    if slippage_bps_raw is None or str(slippage_bps_raw).strip() == "":
        slippage = 0.002  # BacktestEngine default
    else:
        slippage = _safe_float(slippage_bps_raw, default=0.0) / 10000.0

    return {
        "ticker": ticker,
        "rule_type_raw": rule_type,
        "params": params,
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": initial_capital,
        "fee_rate": fee_rate,
        "slippage": slippage,
    }


def _compute_sha256(path: Path) -> str:
    sha256 = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _load_price_data(csv_path: Path, start_date: str, end_date: str) -> pd.DataFrame:
    if not csv_path.is_file():
        raise FileNotFoundError(f"Data file not found: {csv_path.name}")

    data = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    data.columns = [str(c).lower() for c in data.columns]
    data = data.sort_index()

    required = {"open", "high", "low", "close", "volume"}
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError(f"Missing required OHLCV columns: {missing}")

    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    if start_ts > end_ts:
        raise ValueError("start_date must be <= end_date")

    filtered = data.loc[(data.index >= start_ts) & (data.index <= end_ts)].copy()
    if filtered.empty:
        raise ValueError("No data available in the requested date range")

    return filtered


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


def _canonical_rule_type(rule_type_raw: str) -> str:
    normalized = rule_type_raw.strip().upper()
    canonical = RULE_TYPE_ALIASES.get(normalized, normalized)
    if canonical not in RULE_CLASS_REGISTRY:
        raise UnknownRuleTypeError(f"Unknown RULE_TYPE: {rule_type_raw}")
    return canonical


def _normalize_rule_params(canonical_rule_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(params)

    if canonical_rule_type == "RSI_MACD":
        if "oversold" in normalized and "rsi_oversold" not in normalized:
            normalized["rsi_oversold"] = normalized["oversold"]
        if "overbought" in normalized and "rsi_overbought" not in normalized:
            normalized["rsi_overbought"] = normalized["overbought"]
        if "period" in normalized and "rsi_period" not in normalized:
            normalized["rsi_period"] = normalized["period"]
        if "fast" in normalized and "macd_fast" not in normalized:
            normalized["macd_fast"] = normalized["fast"]
        if "slow" in normalized and "macd_slow" not in normalized:
            normalized["macd_slow"] = normalized["slow"]
        if "signal" in normalized and "macd_signal" not in normalized:
            normalized["macd_signal"] = normalized["signal"]

    return normalized


def _instantiate_rule(
    canonical_rule_type: str,
    params: Dict[str, Any],
    run_id: str,
) -> Tuple[Any, Dict[str, Any]]:
    rule_class = RULE_CLASS_REGISTRY[canonical_rule_type]
    normalized_params = _normalize_rule_params(canonical_rule_type, params)

    signature = inspect.signature(rule_class.__init__)
    constructor_kwargs: Dict[str, Any] = {}
    for name in signature.parameters:
        if name in ("self", "metadata"):
            continue
        if name in normalized_params and normalized_params[name] is not None:
            constructor_kwargs[name] = normalized_params[name]

    metadata = RuleMetadata(
        rule_id=f"{canonical_rule_type}_{run_id[:8]}",
        name=canonical_rule_type,
        description=f"{canonical_rule_type} worker execution",
        source="technical",
    )
    rule = rule_class(metadata=metadata, **constructor_kwargs)
    return rule, normalized_params


def _add_rule_features(df: pd.DataFrame, canonical_rule_type: str, params: Dict[str, Any]) -> pd.DataFrame:
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


def _build_metrics_json(backtest_result: Dict[str, Any], drawdown_curve: Any) -> Dict[str, Any]:
    metrics_report = PerformanceMetrics.generate_full_report(backtest_result)
    risk = metrics_report.get("risk_metrics", {})
    trading = metrics_report.get("trading_metrics", {})

    max_drawdown_pct = 0.0
    if drawdown_curve:
        max_drawdown_pct = abs(min(_safe_float(item.get("drawdown_pct", 0.0), 0.0) for item in drawdown_curve))

    return {
        "total_return_pct": round(_safe_float(backtest_result.get("total_return_pct")), 4),
        "sharpe_ratio": round(_safe_float(risk.get("sharpe_ratio")), 6),
        "max_drawdown_pct": round(max_drawdown_pct if drawdown_curve else _safe_float(risk.get("max_drawdown_pct")), 4),
        "num_trades": _safe_int(backtest_result.get("num_trades"), 0),
        "win_rate": round(_safe_float(trading.get("win_rate", backtest_result.get("win_rate"))), 4),
        "profit_factor": round(_safe_float(trading.get("profit_factor")), 6),
        "final_value": round(_safe_float(backtest_result.get("final_value")), 4),
    }


def _check_run_row_exists(session: Session, run_id: str) -> bool:
    row = session.execute(
        text("SELECT run_id FROM backtest_results WHERE run_id = :run_id"),
        {"run_id": run_id},
    ).mappings().first()
    return row is not None


def _set_running(session: Session, run_id: str) -> None:
    session.execute(
        text(
            """
            UPDATE backtest_results
               SET status = :status,
                   started_at = :started_at
             WHERE run_id = :run_id
            """
        ),
        {
            "status": "RUNNING",
            "started_at": _utcnow_naive(),
            "run_id": run_id,
        },
    )
    _commit_with_rollback(session, "set RUNNING")


def _set_succeeded(
    session: Session,
    run_id: str,
    metrics_json: Dict[str, Any],
    equity_curve: Any,
    trades: Any,
    data_hash: str,
) -> None:
    session.execute(
        text(
            """
            UPDATE backtest_results
               SET status = :status,
                   error_message = NULL,
                   metrics_json = :metrics_json,
                   equity_curve_json = :equity_curve_json,
                   trades_json = :trades_json,
                   data_hash = :data_hash,
                   completed_at = :completed_at
             WHERE run_id = :run_id
            """
        ),
        {
            "status": "SUCCEEDED",
            "metrics_json": json.dumps(metrics_json, ensure_ascii=False),
            "equity_curve_json": json.dumps(equity_curve, ensure_ascii=False),
            "trades_json": json.dumps(trades, ensure_ascii=False),
            "data_hash": data_hash,
            "completed_at": _utcnow_naive(),
            "run_id": run_id,
        },
    )
    _commit_with_rollback(session, "set SUCCEEDED")


def _set_failed(session: Session, run_id: str, error_message: str, data_hash: str | None = None) -> None:
    session.rollback()
    session.execute(
        text(
            """
            UPDATE backtest_results
               SET status = :status,
                   error_message = :error_message,
                   data_hash = COALESCE(:data_hash, data_hash),
                   completed_at = :completed_at
             WHERE run_id = :run_id
            """
        ),
        {
            "status": "FAILED",
            "error_message": error_message,
            "data_hash": data_hash,
            "completed_at": _utcnow_naive(),
            "run_id": run_id,
        },
    )
    _commit_with_rollback(session, "set FAILED")


def _run_backtest(run_id: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
    ticker = inputs["ticker"]
    canonical_rule_type = _canonical_rule_type(inputs["rule_type_raw"])
    rule, normalized_params = _instantiate_rule(canonical_rule_type, inputs["params"], run_id=run_id)

    csv_path = DATA_DIR / ticker
    data_hash = _compute_sha256(csv_path)
    logger.info("Computed data hash for %s: %s", ticker, data_hash)

    data = _load_price_data(csv_path, inputs["start_date"], inputs["end_date"])
    data = _add_rule_features(data, canonical_rule_type, normalized_params)

    if not rule.validate(data):
        errors = "; ".join(rule.get_validation_errors())
        raise ValueError(f"Rule validation failed: {errors}")

    def strategy_func(row: pd.Series) -> str | None:
        signal = rule.evaluate(row)
        if signal.action in ("buy", "sell"):
            return signal.action
        return None

    engine = BacktestEngine(
        initial_capital=inputs["initial_capital"],
        commission=inputs["fee_rate"],
        slippage=inputs["slippage"],
    )
    result = engine.run(data, strategy_func, ticker=ticker.replace(".csv", ""))
    if "error" in result:
        raise RuntimeError(result["error"])

    equity_curve = build_equity_curve(result["portfolio_history"])
    trades = normalize_trades(result.get("trades", []), fee_rate=inputs["fee_rate"])
    drawdown_curve = derive_drawdown_curve(equity_curve)
    metrics_json = _build_metrics_json(result, drawdown_curve)

    logger.info(
        "Adapter derived payloads: equity_points=%d trades=%d drawdown_points=%d",
        len(equity_curve),
        len(trades),
        len(drawdown_curve),
    )

    return {
        "data_hash": data_hash,
        "metrics_json": metrics_json,
        "equity_curve": equity_curve,
        "trades": trades,
    }


def main() -> int:
    run_id = os.getenv("RUN_ID", "").strip() or "n/a"
    _configure_logging(run_id)

    if run_id == "n/a":
        logger.error("Missing required env var: RUN_ID")
        return 1

    try:
        database_uri = _get_database_uri()
        SessionFactory = _create_session_factory(database_uri)
    except Exception as exc:
        logger.exception("Failed to initialize database connection: %s", exc)
        return 1

    session = SessionFactory()
    try:
        if not _check_run_row_exists(session, run_id):
            logger.error("orphan job detected")
            return 1

        _set_running(session, run_id)
        logger.info("Transitioned to RUNNING")

        inputs = _read_inputs()
        execution = _run_backtest(run_id, inputs)
        _set_succeeded(
            session,
            run_id=run_id,
            metrics_json=execution["metrics_json"],
            equity_curve=execution["equity_curve"],
            trades=execution["trades"],
            data_hash=execution["data_hash"],
        )
        logger.info("Transitioned to SUCCEEDED")
        return 0

    except UnknownRuleTypeError as exc:
        try:
            _set_failed(session, run_id=run_id, error_message=str(exc))
        except Exception:
            logger.exception("Failed to persist FAILED state for unknown RULE_TYPE")
        logger.error(str(exc))
        return 1
    except ValueError as exc:
        try:
            _set_failed(session, run_id=run_id, error_message=str(exc))
        except Exception:
            logger.exception("Failed to persist FAILED state for value error")
        logger.error(str(exc))
        return 1
    except Exception as exc:
        error_message = str(exc) or exc.__class__.__name__
        try:
            _set_failed(session, run_id=run_id, error_message=error_message)
        except Exception:
            logger.exception("Failed to persist FAILED state for system error")
        logger.exception("Worker execution failed: %s", exc)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
