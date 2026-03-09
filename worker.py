"""Phase 3 worker entrypoint: env -> backtest -> MySQL persist."""

from __future__ import annotations

import hashlib
import json
import logging
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

from adapters.adapter import (
    build_equity_curve,
    build_metrics_json,
    derive_drawdown_curve,
    normalize_trades,
)
from backtest.engine import BacktestEngine
from rules.registry import UnknownRuleTypeError, canonical_rule_type, instantiate_rule
from utils import safe_float as _safe_float, safe_int as _safe_int
from worker_indicators import add_rule_features


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"


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


def _execute_engine(run_id: str, inputs: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """Load data, build rule, run engine.  Returns (engine_result, data_hash)."""
    ticker = inputs["ticker"]
    canonical_rt = canonical_rule_type(inputs["rule_type_raw"])
    rule, normalized_params = instantiate_rule(canonical_rt, inputs["params"], run_id=run_id)

    csv_path = DATA_DIR / ticker
    data_hash = _compute_sha256(csv_path)
    logger.info("Computed data hash for %s: %s", ticker, data_hash)

    data = _load_price_data(csv_path, inputs["start_date"], inputs["end_date"])
    data = add_rule_features(data, canonical_rt, normalized_params)

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

    return result, data_hash


def _run_adapter(engine_result: Dict[str, Any], fee_rate: float) -> Dict[str, Any]:
    """Derive equity curve, trades, drawdown, and metrics from engine output."""
    equity_curve = build_equity_curve(engine_result["portfolio_history"])
    trades = normalize_trades(engine_result.get("trades", []), fee_rate=fee_rate)
    drawdown_curve = derive_drawdown_curve(equity_curve)
    metrics_json = build_metrics_json(engine_result, drawdown_curve, num_normalized_trades=len(trades))

    logger.info(
        "Adapter derived payloads: equity_points=%d trades=%d drawdown_points=%d",
        len(equity_curve),
        len(trades),
        len(drawdown_curve),
    )

    return {
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
        engine_result, data_hash = _execute_engine(run_id, inputs)
        adapter_output = _run_adapter(engine_result, fee_rate=inputs["fee_rate"])

        _set_succeeded(
            session,
            run_id=run_id,
            metrics_json=adapter_output["metrics_json"],
            equity_curve=adapter_output["equity_curve"],
            trades=adapter_output["trades"],
            data_hash=data_hash,
        )
        logger.info("Transitioned to SUCCEEDED")
        return 0

    except Exception as exc:
        error_message = str(exc) or exc.__class__.__name__
        if isinstance(exc, (UnknownRuleTypeError, ValueError)):
            logger.error(error_message)
        else:
            logger.exception("Worker execution failed: %s", exc)
        try:
            _set_failed(session, run_id=run_id, error_message=error_message)
        except Exception:
            logger.exception("Failed to persist FAILED state")
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
