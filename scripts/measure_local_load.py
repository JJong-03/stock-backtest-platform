#!/usr/bin/env python3
"""Measure backtest request latency and concurrent Job throughput against a running web service.

Sends POST /run_backtest and polls GET /status/<run_id> until SUCCEEDED or FAILED.
Records, per run:
  accept_s  : time until POST /run_backtest returned (PENDING stored + Job created)
  start_s   : time from request to the worker marking RUNNING (server started_at)
  e2e_s     : time from request until the client saw SUCCEEDED/FAILED (includes poll interval)

Usage (port-forwarded web service):
    python3 scripts/measure_local_load.py --base-url http://localhost:18080 \
        --sequential 5 --concurrent 10 --concurrent 20 --out measurement.json

Only the standard library is used so it runs outside the app image.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

BODY = {
    "ticker": "AAPL.csv",
    "rule_type": "RSI",
    "params": {},
    "start_date": "2020-01-01",
    "end_date": "2024-12-31",
}
POLL_INTERVAL_S = 2.0  # templates/index.html pollForResult와 같은 주기


def _request(url: str, data: dict | None = None, timeout: float = 120.0) -> dict:
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method="POST" if data is not None else "GET")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _parse_server_time(value: str | None) -> float | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def run_one(base_url: str, deadline_s: float = 900.0) -> dict:
    t0 = time.time()
    try:
        accepted = _request(f"{base_url}/run_backtest", BODY)
    except Exception as exc:  # 접수 단계에서 연결이 끊기거나 시간 초과
        return {"run_id": None, "status": "CLIENT_ERROR", "accept_s": None, "start_s": None,
                "worker_s": None, "e2e_s": round(time.time() - t0, 3), "error": f"submit: {exc}"}
    t_accept = time.time()
    run_id = accepted["run_id"]
    status = accepted.get("status")
    last = accepted
    poll_errors = 0
    while status not in ("SUCCEEDED", "FAILED"):
        if time.time() - t0 > deadline_s:
            status = "TIMEOUT"
            break
        time.sleep(POLL_INTERVAL_S)
        try:
            last = _request(f"{base_url}/status/{run_id}")
            status = last.get("status")
        except Exception:  # 조회 실패는 세고 계속 조회한다
            poll_errors += 1
    t_done = time.time()
    started = _parse_server_time(last.get("started_at"))
    completed = _parse_server_time(last.get("completed_at"))
    return {
        "run_id": run_id,
        "status": status,
        "accept_s": round(t_accept - t0, 3),
        "start_s": round(started - t0, 3) if started else None,
        "worker_s": round(completed - started, 3) if started and completed else None,
        "e2e_s": round(t_done - t0, 3),
        "error": last.get("error_message"),
        "poll_errors": poll_errors,
    }


def summarize(runs: list[dict], wall_s: float | None = None) -> dict:
    ok = [r for r in runs if r["status"] == "SUCCEEDED"]

    def stats(key: str) -> dict:
        values = sorted(r[key] for r in ok if r.get(key) is not None)
        if not values:
            return {}
        p95_index = max(0, int(round(0.95 * len(values))) - 1)
        return {
            "min": values[0],
            "median": round(statistics.median(values), 3),
            "p95": values[p95_index],
            "max": values[-1],
        }

    summary = {
        "requests": len(runs),
        "succeeded": len(ok),
        "failed": len(runs) - len(ok),
        "poll_errors": sum(r.get("poll_errors", 0) for r in runs),
        "accept_s": stats("accept_s"),
        "start_s": stats("start_s"),
        "worker_s": stats("worker_s"),
        "e2e_s": stats("e2e_s"),
    }
    if wall_s is not None:
        summary["wall_s"] = round(wall_s, 3)
        summary["runs_per_min"] = round(len(ok) / wall_s * 60, 2) if wall_s else None
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://localhost:18080")
    parser.add_argument("--sequential", type=int, default=5)
    parser.add_argument("--concurrent", type=int, action="append", default=[])
    parser.add_argument("--out", default="measurement.json")
    args = parser.parse_args()

    result = {"measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "body": BODY, "rounds": []}

    if args.sequential:
        runs = [run_one(args.base_url) for _ in range(args.sequential)]
        result["rounds"].append({"mode": "sequential", "n": args.sequential, "runs": runs, "summary": summarize(runs)})
        print("sequential", json.dumps(summarize(runs), ensure_ascii=False))

    for n in args.concurrent:
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=n) as pool:
            runs = list(pool.map(lambda _: run_one(args.base_url), range(n)))
        wall = time.time() - t0
        result["rounds"].append({"mode": "concurrent", "n": n, "runs": runs, "summary": summarize(runs, wall)})
        print(f"concurrent {n}", json.dumps(summarize(runs, wall), ensure_ascii=False))

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
