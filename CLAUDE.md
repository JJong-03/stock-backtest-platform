# CLAUDE.md -- Stock Backtesting Platform

## 1. Project Overview

| 항목 | 내용 |
|---|---|
| **Project Name** | Kubernetes-based Stock Backtesting Platform |
| **Timeline** | 16일 |
| **Purpose** | 강의 과제 + 클라우드 엔지니어링 면접 포트폴리오 |
| **Core Goal** | 검증 완료된 Python 백테스트 엔진을 Docker 컨테이너로 감싸고, Kubernetes Job으로 실행하는 클라우드 네이티브 플랫폼 |

**Core Values:**

| Value | Meaning |
|---|---|
| **Scalability** | 각 백테스트는 독립적인 K8s Job으로 실행. 수평 확장은 인프라 레벨에서 해결 |
| **Stateless Design** | Web 계층은 로컬 파일시스템에 의존하지 않음. 결과는 DB 또는 Base64 인라인 반환 |
| **Reproducibility** | 동일 입력(ticker, rule, params, date range)은 반드시 동일 출력 생성 |
| **GitOps** | 모든 K8s 매니페스트는 `k8s/` 디렉터리에 존재. 레포가 인프라의 단일 진실 공급원. Argo CD가 클러스터 상태를 레포에서 reconcile (Git = Source of Truth) |

---

## 2. Project Status

Active Phase: Phase 5
- Phase 1 ✅ Completed
- Phase 2 ✅ Completed
- Phase 3 ✅ Completed
- Phase 4 ✅ Completed
- Phase 5 🚧 In Progress

### Phase 2 공통 규격 (K8s)
- **namespace**: stock-backtest
- **mysql**: service name `mysql` (ClusterIP), label `app=mysql`
- **web**: deployment name `web`, label `app=web`
- **ConfigMap**: name `web-config`
- **Secret**: template name `web-secret` (실제 K8s 적용 시에도 이 이름 사용)
- **ServiceAccount**: name `web-sa`
- **Ingress host**: 로컬 환경이므로 생략 가능 (또는 `stock-backtest.local` 사용)
- **Web env (환경변수 주입 규칙)**:
  1. `DATABASE_URL` 우선 적용 (Phase 2 전환 핵심)
  2. 없을 경우 `DB_HOST=mysql`, `DB_PORT=3306`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` 로 Fallback

### Phase 3 공통 규격 (Web → K8s Job Orchestration)

- **namespace**: `stock-backtest` (Phase 2 동일)
- **DB table**: `backtest_results` (MySQL, single source of truth)
- **상태 머신**: `PENDING → RUNNING → SUCCEEDED/FAILED` (단방향)
- **UTC timestamps**: `created_at`(Web), `started_at`/`completed_at`(Worker)
- **오류 분류**
  - `user_error` → Web에서 `PENDING → FAILED` (Job 생성 안 함, HTTP 400)
  - `system_error` → Worker에서 `RUNNING → FAILED` 또는 Web에서 Job 생성 실패 시 `PENDING → FAILED` (HTTP 500)

#### K8s Job 규격
- **Job template file**: `k8s/worker-job-template.yaml`
- **Job name 규칙**: `worker-<run_id_short>` (예: worker-1a2b3c4d)
- **labels**
  - `app=worker`
  - `run_id=<uuid>`
- **backoffLimit**: `1`
- **ttlSecondsAfterFinished**: `86400` (실패 Job 24h 보존)
- **restartPolicy**: `Never`

#### Worker 실행 파라미터(환경변수)
Worker는 아래 환경변수로만 입력을 받는다 (파일 I/O 금지):
- `RUN_ID` (UUID4, 필수)
- `TICKER` (CSV 파일명 기준: 예 `AAPL.csv`, 필수)
- `RULE_TYPE` (예: RSI, MACD, RSI_MACD, 필수)
- `PARAMS_JSON` (JSON string, 필수)
- `START_DATE` (YYYY-MM-DD, 필수)
- `END_DATE` (YYYY-MM-DD, 필수)
- (선택/확장) `INITIAL_CAPITAL`, `FEE_RATE`, `SLIPPAGE_BPS`, `POSITION_SIZE`, `SIZE_TYPE`, `DIRECTION`, `TIMEFRAME`

#### Reproducibility 필드(Worker가 저장)
- `data_hash` (SHA-256 of `data/<TICKER>` CSV content, 엔진 실행 전 계산)

#### Logging 규격 (Rule 8)
- 모든 로그는 stdout/stderr
- 모든 로그 라인은 `[run_id=<RUN_ID>]` 포함

#### Web ↔ Worker 경계
- Web: 입력 검증, `run_id` 발급, `PENDING` insert, Job 생성, `/status/<run_id>` 제공, 성공 시 Job 삭제
- Worker: `RUNNING` 전이, 엔진 실행, adapter 파생, DB persist, `SUCCEEDED/FAILED` 전이, `error_message` 기록

**Reference note:** 상태 머신, 오류 분류, UTC 타임스탬프의 정식 계약은 아래 **Runtime & Data Contracts** 섹션을 기준으로 한다. 본 섹션은 Phase 3 구현 맥락 요약이다.

**Current Phase:** Phase-based planning (as of 2026-02-07).  
— Phases 1–3 cover core platform; Phases 4–6 cover automation, observability, and polish.

| Phase | Status | Scope |
|---|---|---|
| Day 1-2 | ✅ Completed | Core engine verification, rules library, technical indicators, MVP pipeline |
| Day 3 | ✅ Completed | Flask app structure (MVC), immutable engine integration, strategy persistence (SQLite + SQLAlchemy), core web routes & API contracts (`/run_backtest`, `/api/strategies`, `/health`) |
| Day 3.9 | ✅ Completed | Advanced UI: VectorBT-style 5-tab dashboard, extended JSON schemas, adapter-layer metrics, portfolio visualization refactor (separate Orders & Trade PnL charts), cumulative return chart |
| Phase 1 | ✅ Completed | Containerization & Local Parity (Docker, Compose, .env.example, healthcheck) |
| Phase 2 | ✅ Completed | Kubernetes Runtime + Data Layer (Namespace, Deployment, MySQL StatefulSet, ConfigMap/Secret, Ingress) |
| Phase 3 | ✅ Completed | Web → K8s Job Orchestration (worker entrypoint, job launcher, status polling, DB persistence) |
| Phase 4 | ✅ Completed | Automation & GitOps (CI via GitHub Actions, CD via Argo CD) |
| Phase 5 | 🚧 In Progress | Observability verification (Rule 8) & Demo Assets |
| Phase 6 | 📋 Planned | Documentation & Retrospective (architecture diagrams, ops guide, final polish) |

**Implemented APIs:**

| Method | Path | Status |
|---|---|---|
| GET | / | ✅ Implemented |
| POST | /run_backtest | ✅ Implemented |
| GET | /api/strategies | ✅ Implemented |
| POST | /api/strategies | ✅ Implemented |
| DELETE | /api/strategies/<id> | ✅ Implemented |
| GET | /health | ✅ Implemented |
| GET | /status/<run_id> | ✅ Implemented  |
---

## 3. Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Runtime | Python 3.11 Slim | `python:3.11-slim` Docker base image |
| Package Mgmt | pip + requirements.txt | Poetry/Pipenv 사용 금지 |
| Web Framework | Flask (sync) | Gunicorn 워커; 비동기 불필요 |
| **Frontend** | **Jinja2 + Bootstrap 5** | **Template rendering only. NO React/Vue/SPA frameworks** |
| ORM | Flask-SQLAlchemy | SQLite (local dev) → MySQL (production) |
| Data Processing | Pandas, NumPy | 기존 사용 중 |
| Visualization | Matplotlib (**Agg** backend) | 서버 환경 필수; GUI 의존성 없음 |
| Containerization | Docker | Multi-stage build |
| Container Registry | GHCR | `ghcr.io/<owner>/stock-backtest`; `imagePullSecrets` required if private |
| Orchestration | Kubernetes | Job(Worker), Deployment(Web), Service |
| Database | MySQL 8.0 | K8s StatefulSet + PVC |
| CI | GitHub Actions | Test → Build → Push (immutable image tags) |
| CD | Argo CD | Git-driven cluster reconciliation. GitLab CI/CD는 대안으로 허용 (아래 참고) |

**CI/CD Alternative:**
GitHub Actions + Argo CD가 기본 선택. GitLab CI/CD + GitLab Runner 조합도 대안으로 허용하되,
선택 시 `.gitlab-ci.yml`을 레포 루트에 배치하고 동일한 test → build → push → deploy 파이프라인을 유지할 것.

---

### Web vs Worker Responsibility Boundary

Phase 3에서 Web↔Worker 분리가 도입되면 아래 책임 분리를 따른다.

| Responsibility | Web (Flask Deployment) | Worker (K8s Job) |
|---|---|---|
| Request validation, input sanitization | ✅ | — |
| `run_id` issuance (UUID4) | ✅ | — |
| K8s Job 생성 (K8s Python client) | ✅ | — |
| Backtest engine 실행 | — | ✅ |
| Adapter-derived outputs (charts, metrics) | — | ✅ |
| Result persistence → MySQL | — | ✅ |
| Status/result 조회 (`/status/<run_id>`) | ✅ | — |
| Response rendering (JSON/HTML) | ✅ | — |

**Invariants:**
- **Web은 stateless** (Rule 4). 로컬 파일 I/O 없음. 수평 확장에 코드 변경 불필요.
- **Worker는 ephemeral**. 단일 백테스트 실행 후 종료. 재시도는 K8s `backoffLimit`로 관리.
- **MySQL이 결과의 source of truth**. Web과 Worker 모두 MySQL을 통해서만 결과를 교환.
- **Web Pod의 ServiceAccount:** `k8s/rbac.yaml`는 namespace-scoped Role/RoleBinding으로 정의되며, `batch` API group (`batch/v1`)의 `jobs` 리소스에 대해서만 `create`, `get`, `list`, `delete` 권한을 부여한다. ClusterRole은 사용하지 않는다.
- **JobLauncher 추상화:** Web은 `JobLauncher` 인터페이스를 통해 백테스트를 실행. Local/Dev 모드에서는 subprocess 기반 mock, K8s 모드에서는 `kubernetes.client.BatchV1Api`를 사용. 환경변수(`JOB_LAUNCHER_MODE`)로 전환.

---

### GitOps Deployment Flow (CI vs CD)

```
Developer → git push → GitHub Actions (CI)
  1. pytest                                    ← test
  2. docker build + push :${GIT_SHA_SHORT}     ← build
  3. Update image tag in k8s/web-deployment.yaml → commit & push  ← promote
                        ↓
Argo CD (CD) watches k8s/ directory on main branch
  4. Detects manifest change → auto-sync
  5. Rolling update → new Pods with :${GIT_SHA_SHORT} image
```

**CI responsibility (GitHub Actions):**
- Test, build, push image with immutable `:<git-sha-short>` tag (Rule 10)
- Update `k8s/web-deployment.yaml` image field with new tag (via `sed` or `yq` in CI step)
- Commit the manifest change to the repo (direct push to `main`, or PR for review)

**CD responsibility (Argo CD):**
- **Watches:** `k8s/` directory in `main` branch
- **Sync policy:** auto-sync with self-heal enabled
- Detects manifest drift → applies to cluster → rolling update

**Image Tag Update Strategy (Default: CI-driven commit):**
CI 파이프라인이 빌드 성공 후 `k8s/web-deployment.yaml`의 image tag를 새 SHA로 업데이트하고 commit.
전체 배포 상태가 Git에 남으므로 별도 도구 없이 추적 가능.
Direct commits to `main` are acceptable only when the branch is protected with required status checks (tests, builds) enforced before merge.
Optionally, the CI can open a PR for tag promotion and require approval before merge, providing an explicit gate before production deployment.

**Alternative:** Argo CD Image Updater가 컨테이너 레지스트리를 감시하여 자동으로 image tag를 교체할 수 있다.
CI commit 단계를 제거하지만 Argo CD 확장 의존성이 추가되므로, 규모가 커져 CI commit이 머지 충돌을 유발할 때만 도입할 것.

---

## Runtime & Data Contracts (Phase 2+)

> This section defines formal runtime contracts for the Worker execution model.
> These contracts are enforced starting Phase 3 (Web → K8s Job Orchestration).
> RFC 2119 keywords (MUST, SHOULD, MUST NOT) indicate requirement levels.

### Run Execution Contract

**State Machine:**

```
PENDING ──→ RUNNING ──→ SUCCEEDED
                    └──→ FAILED
```

| State | Set By | Trigger |
|---|---|---|
| `PENDING` | Web | `run_id` issued, Job creation requested |
| `RUNNING` | Worker | Worker process starts, begins engine execution |
| `SUCCEEDED` | Worker | Engine completes without error, results persisted to MySQL |
| `FAILED` | Worker or Web | Unrecoverable error during execution, or Job creation failure |

**Invariants:**
- State transitions are **forward-only**. A run MUST NOT revert to a previous state.
- Each transition MUST be persisted to MySQL with a UTC timestamp.
- The `error_message` field MUST be populated for `FAILED` runs.
- Web MUST record `PENDING` state in MySQL **before** creating the K8s Job.

**Timestamps:**
- All timestamps MUST be UTC, stored as ISO 8601 (`YYYY-MM-DDTHH:MM:SS+00:00`).
- `created_at`: Web issues `run_id` and inserts `PENDING` row.
- `started_at`: Worker transitions to `RUNNING`.
- `completed_at`: Worker transitions to `SUCCEEDED` or `FAILED`.

**Note:**
`start_date` and `end_date` are DATE values (YYYY-MM-DD) representing backtest boundaries.
They are not timestamps and therefore do not follow the ISO8601 DATETIME rule used for
`created_at`, `started_at`, and `completed_at`.

**Failure Classification:**

| Category | Cause | HTTP (if surfaced) | Example |
|---|---|---|---|
| `user_error` | Invalid input caught during validation | 400 | Unknown `rule_type`, invalid date range, missing ticker |
| `system_error` | Unrecoverable runtime failure | 500 | Engine crash, DB timeout, OOM |

- `user_error` runs are set to `FAILED` immediately by Web (no Job created).
- `system_error` runs are set to `FAILED` by Worker (or by Web if Job creation itself fails).

**Failure Transition Responsibility:**

| Transition | Responsible | Condition |
|---|---|---|
| `PENDING → FAILED` | Web | Input validation fails (`user_error`), or K8s Job creation fails (`system_error`) |
| `RUNNING → FAILED` | Worker | Unrecoverable runtime error during engine execution (`system_error`) |

- Web MAY transition a run directly from `PENDING → FAILED`. This does NOT violate the
  monotonic state machine; `FAILED` is a terminal state reachable from any non-terminal state.
- Failure to create a K8s Job (e.g., API error from `BatchV1Api`) is classified as `system_error`.
  Web MUST set the run to `FAILED` with a descriptive `error_message` and MUST NOT leave it in `PENDING`.
- Worker MUST transition `RUNNING → FAILED` for any unrecoverable exception during execution.
  The Worker MUST NOT silently exit without updating the run status.

---

### Reproducibility Guarantees

Given identical values for all four identifiers below, the engine MUST produce identical outputs (equity_curve, trades, metrics).

| Identifier | Source | Purpose |
|---|---|---|
| `data_hash` | SHA-256 of input OHLCV CSV content | Ensures identical market data |
| `rule_type` + `params` | Frozen at request time from API payload | Ensures identical strategy logic and parameters |
| `engine_version` | Git SHA of the commit (Rule 10 image tag) | Ensures identical engine code (immutable per Rule 1) |
| `image_tag` | Docker image tag (`:<git-sha-short>`) | Ensures identical runtime environment (dependencies, Python version) |

**Invariants:**
- All four identifiers MUST be stored in the `backtest_results` row for auditability.
- `rule_type` + `params` MUST be persisted exactly as received (no post-hoc normalization).
- The `data_hash` MUST be computed by the Worker **before** engine execution begins and stored with the result.
  Without identifying the exact input dataset, reproducibility is mathematically unverifiable.
- Since `engine.py` is immutable (Rule 1), `engine_version` is effectively the image tag.
- References to `image_tag` as an identity guarantee assume immutable tagging policy.
  This assumption is governed by Rule 10 (Immutable Image Tags) and is not newly introduced here.

**Storage mapping:** `engine_version` is not stored as a separate column. It is represented by the `image_tag` column in the persistence schema. The reproducibility requirement is satisfied because `image_tag` serves as the stored engine version identifier.

---

### Result Persistence Boundaries

MySQL is the **single source of truth** for all backtest results (Section 3 Invariant).
This subsection defines what MUST be persisted vs. what MAY be derived on demand.

**MUST persist (canonical data):**

The table below is the canonical persistence schema for backtest results. All other sections referencing stored fields must align with this definition.

**DB ↔ API naming convention:** Database columns use a `_json` suffix for JSON-typed columns (for example, `params_json`, `metrics_json`, `equity_curve_json`, `trades_json`). The API serialization layer strips this suffix when returning payload fields (for example, `params`, `metrics`, `equity_curve`, `trades`).

| Column | Type | Description |
|---|---|---|
| run_id | CHAR(36) | Primary key, UUID4 |
| ticker | VARCHAR(10) | Stock symbol |
| rule_type | VARCHAR(50) | Execution logic identifier |
| rule_id | VARCHAR(100) | Optional helper slug (nullable) |
| params_json | JSON | Strategy parameters (frozen snapshot) |
| status | ENUM | PENDING, RUNNING, SUCCEEDED, FAILED |
| error_message | TEXT | NULL for success, populated for failure |
| metrics_json | JSON | Summary KPIs |
| equity_curve_json | JSON | Canonical equity time-series |
| trades_json | JSON | Canonical trade list |
| data_hash | VARCHAR(64) | SHA-256 of input CSV (reproducibility) |
| image_tag | VARCHAR(128) | Docker image tag identifying engine version |
| start_date | DATE | Backtest start date |
| end_date | DATE | Backtest end date |
| created_at | DATETIME | UTC timestamp set by Web |
| started_at | DATETIME | UTC timestamp set by Worker |
| completed_at | DATETIME | UTC timestamp set by Worker |

**SHOULD persist (performance optimization):**
- `chart_base64`: Primary equity curve chart. Retained for backward compatibility with Phase 1 clients; new chart fields follow the derive-on-demand pattern and are not stored.

**MUST NOT persist (derived on demand):**
- `drawdown_curve`: Derivable from `equity_curve_json` via Adapter.
- `portfolio_orders_base64`, `trade_pnl_base64`, `cumulative_return_base64`: Re-renderable from `equity_curve_json` + `trades_json` + price data.
- `portfolio_curve`: Derivable from `equity_curve_json` + `trades_json`.
- `price_candles`: Phase 2 field. Re-derivable from raw OHLCV data.
- `signals`: Phase 2 field. Re-derivable from rule execution outputs.

**Rationale:** Storing only canonical data (equity_curve, trades) and summary metrics keeps the DB lean.
All derived visualizations and curves can be deterministically re-computed, consistent with the Adapter pattern (Rule 1).

**Scope:** This contract defines *what* data MUST be persisted, not *how long* or *how much*.
Storage capacity, retention periods, compression strategies, and data lifecycle policies
are operational concerns outside the scope of this document.
This contract MUST NOT be interpreted as requiring unbounded or permanent storage.

---

### Job Lifecycle & Auditability

The audit trail MUST be independent of K8s Job lifecycle.

**Invariant:** Even after a Job object is deleted (by Web on success, or by TTL on failure),
the complete run record MUST remain in MySQL.

**Timeline:**

```
1. Web receives request
   → INSERT INTO backtest_results (run_id, status='PENDING', created_at=NOW())
2. Web creates K8s Job
   → Job Pod starts → Worker UPDATEs status='RUNNING', started_at=NOW()
3a. Success path:
   → Worker UPDATEs status='SUCCEEDED', metrics, equity_curve, trades, completed_at
   → Web confirms result in MySQL → Web DELETEs Job object (immediate cleanup)
3b. Failure path:
   → Worker UPDATEs status='FAILED', error_message, completed_at
   → Job retained for 24h (ttlSecondsAfterFinished: 86400) for log inspection
   → TTL controller deletes Job object after 24h
4. In both paths: MySQL row persists indefinitely for audit and replay.
```

**Consistency with existing invariants:**
- Job deletion policy matches Phase 3 Job Lifecycle Policy (Section 8).
- RBAC `delete` permission on `jobs.batch` (Section 3 Invariants) enables Web-driven cleanup.
- All state changes are logged with `run_id` per Rule 8.

---

## 4. UI Specification (Day 3.9+) — VectorBT-Style Dashboard

This section defines the **data contracts and UI expectations** for the advanced dashboard.

### Data Flow Overview
```
User Input (Backtesting Controls)
  ↓
POST /run_backtest (JSON Request)
  ↓
Flask Controller
  ↓
Backtest Engine (immutable)
  → Outputs: equity_curve, trades, positions
  ↓
Adapter Layer (post-processing)
  → Derives: drawdown_curve, portfolio_curve
  → Computes: win_rate, profit_factor, exposure, etc.
  → Generates: Base64 PNG charts (optional)
  ↓
JSON Response (extended schema)
  ↓
Frontend UI (5 tabs)
  → Stats | Equity | Drawdown | Portfolio | Trades
```

Note: `positions` represent engine-level position state and may be used directly or aggregated downstream for portfolio-level visualizations.

---

### Backtesting Controls (Input UI)

The backtesting form exposes the following inputs:

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| Ticker | string | "AAPL.csv" | Stock symbol |
| Start Date | date | - | YYYY-MM-DD format |
| End Date | date | - | YYYY-MM-DD format |
| Rule (`rule_type`) | dropdown | "RSI" | Options: RSI, MACD, RSI+MACD. Maps to `rule_type` in API request |
| Initial Capital | number | 100000 | Starting portfolio value |
| Fee Rate | number | 0.001 | Decimal fraction (0.001 = 0.1% per trade) |
| Slippage | number | 0 | Basis points (10 bps = 0.10%). Accepted in UI/API; **ignored in Day 3.9 calculations** |
| Position Size | number | 10000 | Amount per trade |
| Size Type | dropdown | "value" | Options: "value" (dollars) or "percent" (%) |
| Direction | dropdown | "longonly" | Options: "longonly" or "longshort" |
| Timeframe | dropdown | "1d" | Daily only (Day 3.9); "5m" and "1h" are Phase 2 |


---

### Dashboard Tabs (Data Contracts)

#### Tab A: Backtesting Stats

Displays summary KPI cards.

**Required KPIs (Day 3.9):**
- Total Return (%)
- Sharpe Ratio
- Max Drawdown (%)
- Number of Trades

**Enhanced KPIs (Phase 2):**
- CAGR: `((final_equity / initial_capital) ^ (1 / years)) - 1`
- Volatility: `std(daily_returns) * sqrt(252)` (annualized)
- Win Rate: `(profitable_trades / total_trades) * 100`
- Average Trade Return: `mean(trade_pnl_pct)`
- Exposure %: `(days_in_market / total_days) * 100`
- Profit Factor: `total_profit / abs(total_loss)`

Formulas are **for documentation only** (not prescriptive implementation).

Sharpe Ratio is computed using daily returns, assuming a zero risk-free rate,
and annualized by multiplying by sqrt(252).

---

#### Tab B: List of Trades

Displays detailed trade history in a table.

**Trade Schema:**

| Field | Type | Description |
|-------|------|-------------|
| trade_no | int | 0-indexed sequence |
| side | string | "BUY" or "SELL" |
| size | int | Number of shares |
| entry_timestamp | ISO8601 | Format: `YYYY-MM-DDTHH:MM:SS+00:00` (UTC) |
| entry_price | float | Entry price (2 decimals) |
| entry_fees | float | Fee: `entry_price * size * fee_rate` |
| exit_timestamp | ISO8601 | Exit time (UTC) |
| exit_price | float | Exit price (2 decimals) |
| exit_fees | float | Fee: `exit_price * size * fee_rate` |
| pnl_abs | float | P/L: `(exit_price - entry_price) * size - entry_fees - exit_fees`|
| pnl_pct | float | Return: `pnl_abs / (entry_price * size) * 100` |
| holding_period | float | Days: `(exit_ts - entry_ts).total_seconds() / 86400` |

**Timestamp Convention:**
- Daily data (`timeframe='1d'`): Default to market close
- US market close: 16:00 ET = 21:00 UTC
- Example: `2020-01-15T21:00:00+00:00`

---

#### Tab C: Equity Curve

Time-series chart of portfolio value.

**Data Contract:**
```json
"equity_curve": [
  { "date": "2020-01-01", "equity": 100000 },
  { "date": "2020-01-02", "equity": 100523 }
]
```

Primary canonical time-series. All other series derive from this.

---

#### Tab D: Drawdown

Time-series chart of drawdown percentage.

**Data Contract:**
```json
"drawdown_curve": [
  { "date": "2020-01-01", "drawdown_pct": 0.0 },
  { "date": "2020-01-02", "drawdown_pct": -1.2 }
]
```

**Definition:**
```
drawdown_pct = ((peak_equity - current_equity) / peak_equity) * 100
where peak_equity = running maximum of equity_curve
```

**Important:** This is **derivable from equity_curve** in the Adapter layer.
Does NOT require engine modification.

---

#### Tab E: Portfolio (Orders / Trade PnL / Cumulative Return)

Three separate full-width server-rendered charts generated in the **Adapter layer**.

**Chart 1 — Orders (Buy / Sell)**
- Close price line with BUY (green ▲) and SELL (red ▼) markers
- Rendered by `render_orders_chart()` → `portfolio_orders_base64`

**Chart 2 — Trade PnL (%)**
- Scatter plot: Profit (green ●) / Loss (red ●) with zero reference line
- Conditional legend (only shown when data points exist)
- Rendered by `render_trade_pnl_chart()` → `trade_pnl_base64`

**Chart 3 — Cumulative Return (%)**
- Line chart derived from `equity_curve`
- Rendered by `render_cumulative_return_chart()` → `cumulative_return_base64`

**Data Sources (all derivable, no engine modification):**
- `equity_curve` (total value time-series)
- `trades` (executed buy/sell actions)
- Price DataFrame from data loader

All charts use the Adapter pattern (Rule 1) and follow Rule 5 (Agg backend, `plt.close(fig)`).

---

#### Tab F: Candlestick + Signals (Phase 2+ Only — NOT part of Day 3.9 dashboard)

**Status:** Phase 2+ only. Not included in the current five-tab dashboard (Stats, Equity, Drawdown, Portfolio, Trades).

- OHLC candlestick chart with BUY/SELL markers
- Library: mplfinance (Matplotlib wrapper)
- Intraday timeframes (`5m`, `1h`): Phase 2 only

**Data Contract (Phase 2):**
```json
"price_candles": [
  { "date": "2020-01-01", "open": 150.0, "high": 153.5, "low": 149.2, "close": 152.8, "volume": 1234567 }
],
"signals": [
  { "date": "2020-01-15", "action": "BUY", "price": 153.17 }
]
```

---

## 5. Strict Rules (Non-Negotiable)

### Terminology (IMPORTANT)

To avoid ambiguity in design and implementation, the following terms are used consistently:

- **Rule**:
  A trading logic implementation defined in `rules/`
  (e.g., `RsiRule`, `MacdRule`, `RsiMacdRule`).
  Rules define **how trades are generated** and are part of the immutable core logic.

- **Strategy Preset**:
  A user-defined UI configuration persisted via SQLAlchemy
  (stored in the `Strategy` ORM model).
  Presets store **parameters only** (dates, rule type, UI settings) and
  **do NOT define trading logic**.

Rule logic MUST live in `rules/`.
Strategy Presets MUST NOT introduce or modify trading behavior.

- **`rule_type` vs `rule_id` (IMPORTANT):**
  - `rule_type` (e.g., `"RSI"`, `"MACD"`, `"RSI_MACD"`) + `params` dictionary **drives execution logic**.
  - `rule_id` (e.g., `"RSI_14_30_70"`) is an **optional helper slug** for tracking and logging.
  - `rule_id` does **NOT** drive execution. If omitted, the system may derive it from `rule_type` + `params`.


**Quick Reference:**

| Rule | 핵심 내용 | 위반 시 결과 |
|---|---|---|
| **#1** | Engine 수정 금지 | 엔진 크래시, 재현성 파괴 |
| **#2** | API Contract 동결 | Worker-Web 통신 장애 |
| **#3** | 루트에서만 실행 | `ModuleNotFoundError` |
| **#4** | Stateless 아키텍처 | K8s 배포 실패 |
| **#5** | Matplotlib Agg | 서버 환경 렌더링 실패 |
| **#6** | 에러 핸들링 | 400 vs 500 구분 필수 |
| **#7** | 환경변수 설정 | 시크릿 노출 위험 |
| **#8** | run_id 로깅 | 디버깅 불가 |
| **#9** | DB Session Safety | 트랜잭션 손상 |
| **#10** | Immutable Image Tags | 배포 추적 불가 |

---

### Rule 1 -- Engine Immutability & Scope Discipline

`backtest/engine.py`와 모든 핵심 백테스트 로직은 레거시 코드이며 **절대 수정 금지**.
엔진 출력이 UI에 부족하면 **README에 제한사항 문서화**. 엔진 수정 금지.
새로운 기능은 반드시 wrapper/adapter 패턴으로 해결.
```python
# CORRECT: 래퍼 패턴
class EnhancedEngine:
    def __init__(self):
        self._engine = BacktestEngine(...)
    def run_with_risk_limit(self, ...):
        result = self._engine.run(data, strategy_func, ticker)
        # post-process result

# WRONG: engine.py 직접 수정
```

#### Post-Processing Allowance (Adapter Layer)

The Controller/Adapter layer MAY compute **derived metrics and visualizations**
from engine outputs WITHOUT modifying engine trading logic.

**Allowed in Adapter:**
- ✅ Deriving `drawdown_curve` from `equity_curve` (peak-to-trough)
- ✅ Computing `portfolio_curve` from `equity_curve` + `trades`
- ✅ Computing `win_rate`, `profit_factor`, `exposure_pct` from `trades`
- ✅ Generating PNG charts via Matplotlib
- ✅ Formatting timestamps to ISO8601

**Still Forbidden:**
- ❌ Modifying signal generation logic
- ❌ Changing trade execution rules
- ❌ Altering engine-internal formulas (Sharpe, returns)

**Important Clarification:**
Re-formatting or re-scaling engine-provided metrics is allowed;
re-computation using different formulas is not.

**Principle:**
> If data can be derived from existing engine outputs (equity, trades),
> compute it in the adapter. Features requiring internal loop access
> (e.g., tracking peak equity during execution) are **OUT OF SCOPE**
> for Phase 1–6 and must be documented as limitations in README.

### Rule 2 -- Immutable API Contracts

**This is the target Web↔Worker contract, enforced starting Phase 2.**

Web(Controller)과 Worker(Job) 간 JSON Schema는 **한번 정의되면 동결**.
기존 필드 삭제/이름 변경 금지. 새 필드 추가 시 기본값 필수.
```json
{
  "run_id": "uuid",
  "ticker": "AAPL.csv",
  "rule_type": "RSI",
  "params": {"period": 14, "oversold": 30, "overbought": 70},
  "rule_id": "RSI_14_30_70",
  "start_date": "2020-01-01",
  "end_date": "2024-01-01",
  "initial_capital": 100000,
  "fee_rate": 0.001,
  "slippage_bps": 0,
  "position_size": 10000,
  "size_type": "value",
  "direction": "longonly",
  "timeframe": "1d"
}
```

**Backtest Request notes:**
- `rule_type` is required and drives execution logic.
- `rule_id` is optional and used for tracking/logging.
- All trading parameter fields are additive-only and have defaults. Existing fields are unchanged.
- `timeframe` default is `"1d"`; `"5m"` and `"1h"` are Phase 2.

```json
{
  "run_id": "uuid",
  "status": "SUCCEEDED",
  "error_message": null,
  "rule_type": "RSI",
  "rule_id": "RSI_14_30_70",
  "params": {
    "period": 14,
    "oversold": 30,
    "overbought": 70
  },
  "metrics": {
    "total_return_pct": 12.34,
    "sharpe_ratio": 1.45,
    "max_drawdown_pct": 8.21,
    "num_trades": 42,
    "cagr": 10.5,
    "volatility": 18.2,
    "win_rate": 65.5,
    "avg_trade_return": 2.1,
    "exposure_pct": 82.3,
    "profit_factor": 1.85
  },
  "equity_curve": [
    {"date": "2020-01-01", "equity": 100000}
  ],
  "drawdown_curve": [
    {"date": "2020-01-01", "drawdown_pct": 0.0}
  ],
  "portfolio_curve": [
    {"date": "2020-01-01", "cash": 90000, "position": 10000, "total": 100000}
  ],
  "trades": [
    {
      "trade_no": 0,
      "side": "BUY",
      "size": 100,
      "entry_timestamp": "2020-01-15T21:00:00+00:00",
      "entry_price": 153.17,
      "entry_fees": 15.32,
      "exit_timestamp": "2020-05-06T21:00:00+00:00",
      "exit_price": 166.84,
      "exit_fees": 16.68,
      "pnl_abs": 1337.0,
      "pnl_pct": 8.7,
      "holding_period": 112.0
    }
  ],
  "charts": {
    "drawdown_curve_base64": "data:image/png;base64,...",
    "portfolio_orders_base64": "data:image/png;base64,...",
    "trade_pnl_base64": "data:image/png;base64,...",
    "cumulative_return_base64": "data:image/png;base64,..."
  },
  "data_hash": "sha256hex...",
  "image_tag": "abc1234",
  "start_date": "2020-01-01",
  "end_date": "2024-01-01",
  "chart_base64": "data:image/png;base64,...",
  "price_candles": [
    {"date": "2020-01-01", "open": 150.0, "high": 153.5, "low": 149.2, "close": 152.8, "volume": 1234567}
  ],
  "signals": [
    {"date": "2020-01-15", "action": "BUY", "price": 153.17}
  ]
}
```

**Backtest Result notes:**
- The canonical status values are: `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`. Legacy clients may serialize `SUCCEEDED` as `"completed"`.
- `rule_id` is an optional helper slug persisted for traceability and debugging.
- `params` represents the frozen strategy parameters used during execution. It is returned for reproducibility and auditability.
- `metrics` includes Day 3.9 required fields (`total_return_pct`, `sharpe_ratio`, `max_drawdown_pct`, `num_trades`) and Phase 2 optional fields (`cagr`, `volatility`, `win_rate`, `avg_trade_return`, `exposure_pct`, `profit_factor`).

### Rule 3 -- Execution Context (Root Only)

모든 명령(Docker build, Python 실행, 테스트)은 **프로젝트 루트에서 실행**.
하위 폴더로 `cd`하여 스크립트를 실행하면 `ModuleNotFoundError` 발생.
```bash
# Correct
python scripts/verify_mvp.py
python -m flask run
docker build -t stock-backtest .

# Wrong
cd scripts && python verify_mvp.py
```

### Rule 4 -- Stateless Web Architecture

Flask 서버는 로컬 파일시스템에 쓰기 금지.
생성된 아티팩트(차트, 이미지)는 메모리에서 처리하고 Base64로 반환.

**Backtest results storage:**
- **Phase 1 (Current):** Results returned inline as Base64-encoded JSON response
- **Phase 2+ (Future):** Results persisted to MySQL; Base64 chart stored in `backtest_results` table

Strategy definitions (user-created rules) are stored in SQLite via SQLAlchemy.
```python
# Correct
buf = io.BytesIO()
fig.savefig(buf, format="png")
chart_b64 = base64.b64encode(buf.getvalue()).decode()

# Wrong
fig.savefig("/tmp/chart.png")
```

**Note on Local SQLite Usage (IMPORTANT):**

- SQLite is used **ONLY for local development (Phase 1)** to persist UI strategy presets.
- The SQLite file (`strategies.db`) is **NOT a production dependency** and is **never committed**.
- Starting Phase 2, all persistent state (presets & results) moves to **MySQL via StatefulSet**.
- The Web tier remains stateless in production; local SQLite is a **development-only exception**.



### Rule 5 -- Server-Safe Visualization

- pyplot import 전에 반드시 `matplotlib.use("Agg")` 설정
- 렌더링 후 반드시 `plt.close(fig)`로 figure 해제 (메모리 누수 방지)
```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax = plt.subplots()
# ... render ...
buf = io.BytesIO()
fig.savefig(buf, format="png")
plt.close(fig)  # REQUIRED
```

### Rule 6 -- Error Handling Discipline

- User/Input 에러: **HTTP 400** (누락 필드, 잘못된 날짜, 알 수 없는 rule_id)
- System/Execution 에러: **HTTP 500** (DB 다운, 엔진 크래시)
- 사용자 메시지는 간결하게, 상세 스택 트레이스는 **서버 로그에만** 기록
```python
@app.errorhandler(Exception)
def handle_error(e):
    logger.exception(f"[run_id={g.run_id}] Unhandled error")
    return jsonify({"error": "Internal server error", "run_id": g.run_id}), 500
```

### Rule 7 -- Configuration & Secrets

- 모든 설정은 **환경변수**로 주입
- 로컬: `.env.example` 커밋 (실제 `.env`는 `.gitignore`)
- K8s: ConfigMap(비밀 아닌 값) + Secret(DB 비밀번호 등)
- **하드코딩된 시크릿 커밋 절대 금지**
```bash
# .env.example (committed)
FLASK_ENV=development
DB_HOST=localhost
DB_PORT=3306
DB_NAME=stock_backtest
DB_USER=backtest
DB_PASSWORD=changeme
LOG_LEVEL=INFO
```

**Secret Commit Policy (GitOps Safety):**
- `k8s/secret.yaml` with real values MUST **NEVER** be committed to the repository.
- The repo contains **`k8s/secret-template.yaml`** only (placeholder values).
- Real secrets are injected via **CI/CD pipeline variables** or **Sealed Secrets** in production.
- `.gitignore` MUST include `k8s/secret.yaml` to prevent accidental commits.

#### GitOps Secret Management (Argo CD)

In addition to the Secret Commit Policy defined above, Argo CD deployments follow the constraints below.

- Kubernetes Secrets MUST NOT be committed with real values.
- The repository stores only `secret-template.yaml` with placeholder values.
- The real `secret.yaml` is generated outside Git and ignored via `.gitignore`.
- Argo CD synchronization excludes real secret manifests to prevent self-heal overwrite conflicts.

### Rule 8 -- Observability (Primary Reference)

> **This is the single source of truth for observability requirements.**
> Phase 5 verifies compliance; it does not redefine the rules below.
> If any other section appears to conflict with the rules below, Rule 8 takes precedence.

- 모든 백테스트 실행에 `run_id` (UUID4) 부여
- 모든 로그에 `run_id` 포함 — Web, Worker, DB 전 구간 추적 가능해야 함
- K8s 로그 수집을 위해 Stdout/Stderr로만 로깅 (파일 로깅 금지)
```python
import uuid
run_id = str(uuid.uuid4())
logger.info(f"[run_id={run_id}] Backtest started: ticker={ticker}, rule={rule_id}")
logger.info(f"[run_id={run_id}] Backtest completed: return={result['total_return_pct']:.2f}%")
```

#### Phase 5 Observability Goals (Prometheus & Grafana)

The platform introduces metrics-based observability in addition to structured logging.

Core monitoring goals:

- HTTP request latency for Flask endpoints
- API request count and error rate
- Kubernetes Job backtest duration
- Kubernetes Job success and failure rate
- Worker execution failures

If implemented, the Web service should expose a `/metrics` endpoint compatible with Prometheus.

Grafana dashboards may visualize:

- request latency distribution
- job success rate
- backtest runtime distribution

These metrics extend the existing observability mechanism defined in Rule 8 (run_id structured logging).

The `/metrics` endpoint exposes only in-memory counters and histograms and does not write any filesystem state. This remains compliant with the stateless Web architecture defined in Rule 4.

### Rule 9 -- Database Session Safety

- 모든 `db.session.commit()`은 `try/except` 안에서 호출
- Exception 발생 시 반드시 `db.session.rollback()` 실행
- `IntegrityError`(중복)와 일반 `Exception`(시스템 장애) 분리 처리
- `db.create_all()`은 `if __name__ == "__main__"` 블록 안에서만 호출 (Gunicorn/K8s 호환)


**Git Safety Rule:**
- `strategies.db` (SQLite file) MUST be listed in `.gitignore` and never committed.

**Production Schema Initialization (Phase 2+):**
- Production 환경(K8s)에서 `db.create_all()`은 **자동 실행되지 않는다**.
- 스키마 초기화는 **일회성 운영 절차**로 취급하며, 운영자가 명시적으로 실행한다.
  - 방법: `kubectl exec` 또는 초기화 전용 K8s Job
- `db.create_all()`은 **로컬 개발 환경에서만** `if __name__ == "__main__"` 블록 내에서 호출된다.
- Alembic 등 마이그레이션 도구는 이 MVP 범위에서는 사용하지 않는다. 스키마 변경은 additive only.

### Rule 10 -- Immutable Image Tags

- Docker 이미지 태그는 **Git SHA 또는 semantic version** 사용. `latest` 태그를 production 배포에 사용 금지.
- CI 파이프라인이 빌드한 이미지는 `ghcr.io/<owner>/stock-backtest:<git-sha-short>` 형식으로 push.
- 동일 태그로 **이미지 덮어쓰기 금지** — 배포 이력 추적과 롤백을 보장.


---

## 6. Directory Structure
```
stock_backtest/
|
|-- CLAUDE.md                          # 이 파일 (프로젝트 규칙 및 컨텍스트)
|-- README.md                          # 프로젝트 소개 및 Quick Start
|-- requirements.txt                   # Python 의존성
|-- requirements-dev.txt               # 개발 의존성 (gunicorn)
|-- .gitignore                         # Git 제외 규칙
|-- app.py                             # ✅ Flask 애플리케이션 진입점 (Controller)
|-- worker.py                          # [Phase 3] K8s Job Worker 진입점
|-- extensions.py                      # ✅ SQLAlchemy 인스턴스 (순환 import 방지)
|-- models.py                          # ✅ Strategy ORM 모델
|-- Dockerfile                         # [Phase 1] Multi-stage Docker 빌드
|-- docker-compose.yml                 # [Phase 1] 로컬 개발: app + MySQL
|-- .env.example                       # [Phase 1] 환경변수 템플릿
|-- .dockerignore                      # [Phase 1] __pycache__/, *.pyc, .git/, .env, strategies.db 제외 (data/ is included for reproducibility)
|
|-- .github/                           # [Phase 4] CI/CD
|   +-- workflows/
|       +-- ci.yml                     # Test → Build → Push (GitHub Actions)
|
|-- launchers/                         # [Phase 3] Job 오케스트레이션 패키지
|   |-- __init__.py                    # Re-exports: create_job_launcher, build_job_name, JobLauncher
|   +-- job_launcher.py               # JobLauncher 추상화 (Local/K8s 모드 전환)
|
|-- backtest/                          # 핵심 엔진 (IMMUTABLE)
|   |-- __init__.py
|   |-- engine.py                      # BacktestEngine -- 수정 금지
|   +-- metrics.py                     # PerformanceMetrics
|
|-- rules/                             # 트레이딩 룰 라이브러리
|   |-- __init__.py
|   |-- base_rule.py                   # BaseRule, Signal, RuleMetadata, CompositeRule
|   |-- technical_rules.py             # ✅ Implemented: RSI, MACD, RSI+MACD, MA Cross, BB, Volume, Trend, ATR
|   |-- paper_rules.py                 # Momentum, Value, MeanReversion, Breakout
|   |-- rule_validator.py              # RuleValidator, SignalAnalyzer
|   +-- optimizer.py                   # ParameterOptimizer (Grid Search)
|
|-- extracted/
|   +-- features/
|       |-- __init__.py
|       +-- technical_indicators.py    # SMA, EMA, RSI, MACD, BB, ATR, Stochastic, ADX, OBV, VWAP
|
|-- scripts/
|   |-- config.py                      # 환경변수 기반 설정 (Config 클래스)
|   |-- data_loader.py                 # yfinance 다운로드 + 검증
|   |-- logger_config.py               # 로깅 설정 (stdout/stderr structured logging; K8s-friendly, Rule 8 compliant)
|   |-- qa_prices.py                   # 데이터 품질 검증
|   |-- verify_mvp.py                  # E2E 파이프라인 검증 스크립트
|   +-- demo.sh                        # [Phase 5] 고정 시나리오 E2E 데모 스크립트
|
|-- adapters/                          # ✅ Adapter Layer (post-processing, Rule 1 compliant)
|   |-- __init__.py
|   +-- adapter.py                     # build_equity_curve, derive_drawdown_curve, normalize_trades, render_*_chart
|
|-- tests/                             # ✅ Test Suite
|   |-- __init__.py
|   +-- test_day39.py                  # 83 tests: adapter, Flask endpoints, schema, figure leak prevention
|
|-- templates/
|   +-- index.html                     # ✅ Bootstrap 5 Dark Mode 대시보드
|
|-- k8s/                               # [Phase 2-3] Kubernetes 매니페스트
|   |-- namespace.yaml
|   |-- configmap.yaml
|   |-- secret-template.yaml           # Template only; real secrets via CI/CD or Sealed Secrets
|   |-- web-deployment.yaml
|   |-- web-service.yaml               # ClusterIP Service for web Deployment (port 80 → 5000)
|   |-- web-servicemonitor.yaml        # [Phase 5] Prometheus Operator ServiceMonitor for /metrics scraping
|   |-- worker-job-template.yaml
|   |-- mysql-statefulset.yaml
|   |-- rbac.yaml                      # ServiceAccount + Role + RoleBinding (namespace-scoped, jobs.batch only)
|   |-- ingress.yaml
|   +-- grafana-dashboard.json         # [Phase 5] Grafana dashboard definition (Prometheus datasource)
|
|-- docs/                              # [Phase 6] 프로젝트 문서 + 기술 회고
|   |-- RETROSPECTIVE.md              # 기술 회고 및 아키텍처 설명
|   |-- AGENTS.md                     # Codex 에이전트 실행 플레이북
|   |-- architecture.md                # 아키텍처 다이어그램 (Mermaid)
|   |-- ops-guide.md                   # 운영 가이드 (배포, 롤백, 트러블슈팅)
|   +-- sql/
|       +-- backtest_results.sql       # backtest_results 테이블 DDL 참조
|
|-- data/                              # OHLCV CSV 데이터 (AAPL.csv 데모 포함)
```

---

## 7. Short-Term Roadmap

**Note:** Roadmap is high-level only. Detailed task lists belong in `docs/RETROSPECTIVE.md` or Issues.
Phase-based plan with acceptance criteria is in **Section 8**.

### Day 3 -- Flask Web Dashboard (✅ Completed — Pre-Phase Planning)

| Task | Status |
|---|---|
| `app.py` 생성 (`GET /`, `POST /run_backtest`, `GET /health`) | ✅ Done |
| HTML 템플릿 (`index.html` — Bootstrap 5 Dark Mode, AJAX) | ✅ Done |
| Rule-Engine 어댑터 (`_build_strategy` wrapper 패턴) | ✅ Done |
| 차트 렌더링 (Matplotlib Agg → Base64 `<img>`) | ✅ Done |
| Strategy Persistence (`extensions.py`, `models.py`, REST API) | ✅ Done |
| Date range filtering (explicit `pd.to_datetime` + `tz_localize`) | ✅ Done |
| RSI + MACD Combined Strategy (`RsiMacdRule`) | ✅ Done |
| Security hardening (path traversal, memory leak, production config) | ✅ Done |

### Day 3.9 -- Advanced UI Features (✅ Completed — Pre-Phase Planning)

| Task | Status | Time |
|---|---|---|
| 5-tab interface (Stats, Equity, Drawdown, Portfolio, Trades) | ✅ Done | 1.5h |
| Extended JSON response schema (equity_curve, drawdown_curve, trades) | ✅ Done | 1h |
| Enhanced metrics calculation (adapter layer) | ✅ Done | 1h |
| Drawdown chart derivation & rendering | ✅ Done | 1h |
| Portfolio visualization refactor (separate Orders & Trade PnL charts) | ✅ Done | 1h |
| Cumulative return chart | ✅ Done | 30min |
| Trading fees + slippage UI controls | ✅ Done | 30min |
| Typography improvements (14px min, monospace numbers) | ✅ Done | 30min |
| Bloomberg Terminal aesthetic refinement | ✅ Done | 1h |

**Day 3.9 Log:** Completed UI polish, cumulative return chart, and portfolio visualization refactor (split Orders + Trade PnL into separate full-width charts with fixed-position legends, removed deprecated combined chart).

---

## 8. Phase Plan — Platform Completion (13 days remaining)

> Phases are ordered by dependency. Each phase builds on the previous.
> Estimated durations are guidelines, not hard boundaries.

---

### Phase 1: Containerization & Local Parity

**Goals:**
- Docker 이미지로 Flask 앱을 패키징하여 로컬 환경 일관성 확보
- `docker compose up` 한 줄로 Web + MySQL 개발 환경 구동
- 환경변수 기반 설정으로 Dev/Prod 전환 준비 완료

**Deliverables:**
- `Dockerfile` (multi-stage: builder + runtime, port 5000)
- `docker-compose.yml` (web + db services, shared network, MySQL volume)
- `.env.example` + `.dockerignore`

**Data Supply Strategy:**
- `data/` 디렉터리는 Docker 이미지에 포함 (COPY). 런타임에 read-only로 사용.
- MVP 기준 데이터셋 크기가 작으므로 이미지 내장이 재현성(Reproducibility)과 불변성(Rule 10)을 보장.
- `.dockerignore`에서 `data/`를 **제외하지 않음** (이미지에 포함되어야 함).

**Acceptance Criteria:**
- `docker compose up` → `/health` 200 OK, `/run_backtest` 정상 응답
- `docker compose down && docker compose up` → 데이터 무손실 (MySQL volume 유지)

**Outputs:** `Dockerfile`, `docker-compose.yml`, `.env.example`, `.dockerignore`

---

### Phase 2: Kubernetes Runtime + Data Layer

**Goals:**
- K8s 클러스터에서 Web Deployment + MySQL StatefulSet 운영
- ConfigMap/Secret으로 환경변수 주입, Ingress로 외부 접근
- SQLite → MySQL 전환 완료 (코드 변경 없이 `DATABASE_URL`만 교체)

**Deliverables:**
- `k8s/` 매니페스트 (namespace, configmap, secret-template, web-deployment, mysql-statefulset, rbac, ingress)
- `k8s/rbac.yaml`: ServiceAccount + namespace-scoped Role (`create`, `get`, `list`, `delete` on `jobs` in `batch` API group) + RoleBinding
- `backtest_results` 테이블 스키마 (canonical definition: `Result Persistence Boundaries` 참조)
- Service (ClusterIP for MySQL, NodePort/Ingress for Web)

**Acceptance Criteria:**
- `kubectl apply -f k8s/` → Web Pod Ready, MySQL Pod Ready
- Web Pod에서 MySQL 연결 성공, `/health` 200 OK

**Outputs:** `k8s/*.yaml` manifests (8 files), `backtest_results` DDL

---

### Phase 3: Web → K8s Job Orchestration

**Goals:**
- 백테스트 요청을 K8s Job으로 비동기 실행
- Worker가 결과를 MySQL에 저장하고, Web이 상태를 폴링
- Job 생명주기 관리 (TTL, backoff)

**Deliverables:**
- `worker.py` (Job 진입점: 환경변수 → 백테스트 실행 → MySQL 저장 → 종료)
- `k8s/worker-job-template.yaml` (backoffLimit: 1, ttlSecondsAfterFinished: 86400)
- Job launcher in Flask (`JobLauncher` 추상화) + `GET /status/<run_id>` 폴링 API
- `JobLauncher` 구현: Local 모드 (subprocess mock) + K8s 모드 (`BatchV1Api`), `JOB_LAUNCHER_MODE` 환경변수로 전환

**Job Lifecycle Policy:**
- **성공한 Job:** Web 애플리케이션이 결과 persist 확인 후 **즉시 명시적으로 삭제** (`BatchV1Api.delete_namespaced_job`). 삭제는 Web과 동일한 namespace 내에서만 수행된다 (RBAC namespace-scoped Role에 의해 강제).
- **실패한 Job:** 디버깅을 위해 **24시간 보존**. TTLAfterFinished controller가 `ttlSecondsAfterFinished: 86400` 이후 자동 정리.
- `ttlSecondsAfterFinished: 86400`은 실패한 Job의 fallback cleanup 역할. 성공한 Job은 TTL 만료 전에 Web이 선제 삭제.

**Acceptance Criteria:**
- Web에서 백테스트 요청 → K8s Job 생성 → MySQL에 결과 저장 → `/status/<run_id>` → `{"status": "SUCCEEDED"}`
- Job 실패 시 `/status/<run_id>` → `{"status": "FAILED", "error_message": "..."}`

**Outputs:** `worker.py`, updated `app.py` (job launcher + status endpoint), `k8s/worker-job-template.yaml`

---

### Phase 4: Automation & GitOps

**Goals:**
- Push 시 자동으로 테스트 → 빌드 → 이미지 push (CI)
- Git merge 시 Argo CD가 클러스터 상태를 자동 reconcile (CD)
- Immutable image tags (Git SHA)로 배포 추적 (Rule 10)

**Deliverables:**
- `.github/workflows/ci.yml` (pytest → docker build → push to GHCR with `:<git-sha-short>` tag)
- Argo CD Application manifest (`k8s/argocd-app.yaml` 또는 Argo CD UI 설정)
- Image tag 업데이트 → Argo CD 자동 sync 파이프라인

**Acceptance Criteria:**
- `git push` → GitHub Actions green → 새 이미지 push → Argo CD sync → Pod 롤링 업데이트
- 이전 태그로 롤백 가능 확인 (Section 11 Rollback Procedure 참고)

**Outputs:** `.github/workflows/ci.yml`, Argo CD app config, documented rollback procedure

---

### Phase 5: Observability Verification & Demo Assets

> Observability requirements are defined in **Rule 8**. This phase verifies
> end-to-end compliance and produces demo assets. It does NOT redefine the rules.

This phase focuses on verification of Rule 8 compliance (stdout/stderr logging and run_id tracing), not on introducing new observability features.

**MUST (deadline required):**
- `run_id` 기반 요청 추적이 Web → Job → MySQL 전 구간에서 동작 확인
- 모든 컴포넌트가 stdout/stderr structured logging을 사용 (Rule 8 compliance)
- `scripts/demo.sh` — 고정 시나리오 E2E 데모 (백테스트 제출 → 상태 폴링 → 결과 확인)

**NICE-TO-HAVE (optional, not required for deadline):**
- Prometheus ServiceMonitor + Grafana dashboard JSON
- `/metrics` endpoint (request count, latency histogram)

**Acceptance Criteria:**
- `scripts/demo.sh` 실행 → 전체 파이프라인 성공, 결과 MySQL 확인 가능
- `kubectl logs` 에서 `run_id`로 Web → Job 전 구간 요청 추적 가능

**Outputs:** `scripts/demo.sh`, logging verification report (in docs/RETROSPECTIVE.md)

---

### Phase 6: Documentation & Retrospective

**Goals:**
- 아키텍처 다이어그램과 운영 가이드로 포트폴리오 완성도 확보
- `docs/RETROSPECTIVE.md`에 Phase 1-5 설계 결정 추가
- README.md를 최종 상태로 업데이트

**Deliverables:**
- `docs/architecture.md` (Mermaid 다이어그램: 전체 흐름, K8s 토폴로지, CI/CD 파이프라인)
- `docs/ops-guide.md` (배포, 롤백, 트러블슈팅 가이드)
- `docs/RETROSPECTIVE.md` 업데이트 (Phase 1-5 Q&A 추가)

**Acceptance Criteria:**
- `docs/` 디렉터리에 2개 이상 문서 존재
- `docs/RETROSPECTIVE.md`에 인프라 관련 Q&A 3개 이상 추가

**Outputs:** `docs/architecture.md`, `docs/ops-guide.md`, updated `docs/RETROSPECTIVE.md` + README.md

---

## 9. Acceptance Criteria (Project-wide)

프로젝트 전체 완성도를 판단하는 최종 체크리스트:

- [ ] `docker compose up` → Web + MySQL 정상 구동, `/health` 200 OK
- [ ] `kubectl apply -f k8s/` → Web Deployment + MySQL StatefulSet Ready
- [ ] Web에서 백테스트 요청 → K8s Job 생성 → MySQL에 결과 저장
- [ ] 결과가 MySQL에 persist (`backtest_results` 테이블)
- [ ] CI/CD 파이프라인 동작: push → test → build → deploy (Argo CD sync)

---

## 10. Out of Scope (for this deadline)

아래 항목은 현재 16일 마감 내 **구현 대상이 아님**:

- **게시판/IoT/AI 연동** — Phase 7+ ideas. 플랫폼 완성 후 확장 가능성으로만 언급.
- **Candlestick chart + Intraday timeframes** — UI enhancement (Phase 2+ feature). 선택적 구현. 핵심 플랫폼 완성이 우선.
- **Benchmark overlay (Buy & Hold)** — 선택적 UI feature.
- **Sortable/filterable trade table** — 클라이언트 측 enhancement, 우선순위 낮음.
- **Additional metrics (CAGR, volatility, win_rate, profit_factor, exposure)** — Adapter layer에서 계산 가능하나, 핵심 인프라 완성이 우선.
- **Prometheus/Grafana 대시보드** — Phase 5 NICE-TO-HAVE. 마감 필수 요건 아님.

**원칙:** 플랫폼 완성도(Docker → K8s → Job → CI/CD → Observability) > 새로운 UI 기능.

---

## 11. Operations: SLO, Rollback, Incident Triage

### SLOs (Service Level Objectives)

- **Availability:** `/health` endpoint returns 200 OK ≥ 99% of the time (measured per hour)
- **Backtest Completion:** ≥ 95% of submitted K8s Jobs reach `SUCCEEDED` status within 5 minutes

### Rollback Procedure (3 steps)

1. **Revert image tag:** Argo CD sync to previous known-good tag
   (`argocd app sync stock-backtest --revision <prev-commit>`)
   — 또는 `k8s/web-deployment.yaml`의 image tag를 이전 SHA로 되돌리고 commit → Argo CD auto-sync
2. **Verify health:** `curl http://<ingress>/health` → 200 OK on all Web Pods
3. **Validate functionality:** submit test backtest → `/status/<run_id>` returns `SUCCEEDED` with valid metrics

### Incident Triage Checklist

| Step | Command / Action | What to check |
|---|---|---|
| 1. Ingress/Service | `kubectl get ingress,svc -n stock-backtest` | Endpoints populated? External IP assigned? |
| 2. Web Pods | `kubectl get pods -l app=web -n stock-backtest` | Running? Restart count normal? OOMKilled? |
| 3. Job Status | `kubectl get jobs -n stock-backtest` | Failed jobs? `backoffLimit` exceeded? |
| 4. DB Connectivity | `kubectl exec <web-pod> -- python -c "from extensions import db; ..."` (환경변수 기반 테스트 커맨드 예시; 실제 값은 환경별로 상이) | MySQL connection OK? Timeout? |
| 5. Logs by run_id | `kubectl logs -l app=web \| grep <run_id>` + `kubectl logs job/<run_id>` | Trace full request path: Web → Job → DB |

---

## 12. Observability Stack

> This section formalizes the Kubernetes-native observability architecture.
> It extends Rule 8 (structured logging + run_id tracing) with metrics-based monitoring.
> No application behavior, API contracts, persistence schema, or worker execution model is changed.

### Stack Components

**Primary (Phase 5):**

| Component | Role | Deployment |
|---|---|---|
| **Prometheus** | Metrics collection & alerting | K8s Deployment or Helm chart (`kube-prometheus-stack`) |
| **Grafana** | Visualization & dashboards | K8s Deployment, datasource: Prometheus |
| **kube-state-metrics** | Exposes K8s object state as Prometheus metrics | Single-replica Deployment (bundled with `kube-prometheus-stack`) |

**Optional Future Extensions:**

| Component | Role | When to Adopt |
|---|---|---|
| Loki | Log aggregation (centralized log querying) | When `kubectl logs` becomes insufficient for multi-pod debugging |
| OpenTelemetry | Distributed tracing (spans across Web → Worker → DB) | When request-level latency profiling is needed beyond run_id grep |

### Prometheus Scrape Configuration

Prometheus discovers the web Service's `/metrics` endpoint via a **ServiceMonitor** resource (`k8s/web-servicemonitor.yaml`).
Annotation-based scraping (`prometheus.io/*`) is not used — the ServiceMonitor is the single scrape mechanism.

- **Scrape target:** web Service only (long-running Deployment). Worker Job pods are NOT scraped.
- **Port:** ServiceMonitor references the named port `http` on the web Service (port 80 → targetPort 5000).
- **Path:** `/metrics`
- **Interval:** 15s
- **Scope:** Metrics scraping is cluster-internal only. `/metrics` is NOT exposed via Ingress.

The ServiceMonitor requires the `release` label to match the Prometheus Operator's `serviceMonitorSelector`.
The default value assumes a kube-prometheus-stack Helm release named `kube-prometheus-stack`.

### Web Service Metrics (`/metrics` Endpoint)

The Flask Web service exposes a `/metrics` endpoint using the **Prometheus Python client** (`prometheus_client`).
This endpoint serves in-memory counters and histograms only — no filesystem writes (Rule 4 compliant).

#### Web Layer Metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `http_requests_total` | Counter | `method`, `endpoint`, `status` | Total HTTP requests by method, endpoint, and status code |
| `http_request_duration_seconds` | Histogram | `method`, `endpoint` | Request latency distribution |
| `backtest_requests_total` | Counter | `rule_type`, `outcome` |
Backtest submissions by rule type and outcome.
`outcome` values: `accepted` (PENDING persisted, proceeding to launch),
`rejected` (validation/user error, HTTP 400),
`error` (system error before launch, e.g., DB insert failure, HTTP 500). |

**Note:** 5xx error rates SHOULD be derived from `http_requests_total` using PromQL rather than tracked as a separate metric:
```promql
http_requests_total{status=~"5.."}
```

#### Job Orchestration Metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `job_launch_success_total` | Counter | `rule_type` | Successful K8s Job creations |
| `job_launch_failure_total` | Counter | `rule_type` | Failed K8s Job creation attempts |

**Note:** Job duration SHOULD be derived from kube-state-metrics using:
```promql
kube_job_status_completion_time - kube_job_status_start_time
```
This avoids duplicating timing data already available from the Kubernetes control plane.

### Kubernetes-Level Monitoring

Collected by **kube-state-metrics** + Prometheus scraping (no application code changes):

| Signal | Source | Description |
|---|---|---|
| Job success / failure count | `kube_job_status_succeeded`, `kube_job_status_failed` | K8s Job completion metrics |
| Pod restart count | `kube_pod_container_status_restarts_total` | Detects crash loops (Web or Worker) |
| Worker execution duration | `kube_job_status_completion_time - kube_job_status_start_time` | Job-level runtime derived from K8s metadata |
| Pod resource usage | `container_cpu_usage_seconds_total`, `container_memory_working_set_bytes` | Resource consumption (via cAdvisor / metrics-server) |

### Grafana Dashboards

Recommended dashboard panels:

1. **Request Overview** — HTTP request rate, latency percentiles (p50/p95/p99), error rate
2. **Backtest Pipeline** — Job launch rate, success/failure ratio, run duration distribution
3. **Kubernetes Health** — Pod status, restart count, resource utilization
4. **MySQL** — Connection pool usage, query latency (if MySQL exporter is deployed)

### Label Cardinality Constraint

> **CRITICAL:** `run_id` MUST NOT be used as a Prometheus metric label.

`run_id` is a UUID4 with unbounded cardinality. Adding it as a label would cause
Prometheus TSDB storage explosion and query performance degradation.

**Correct separation of concerns:**

| Data | Channel | Lookup Method |
|---|---|---|
| Per-request identity (`run_id`) | **Structured logs** (stdout/stderr) | `kubectl logs` + `grep run_id=<uuid>` |
| Aggregate operational signals | **Prometheus metrics** | Grafana dashboards, PromQL queries |

Allowed labels are low-cardinality dimensions only: `method`, `endpoint`, `status`, `rule_type`, `outcome`.

**Endpoint Label Normalization:**

The `endpoint` label MUST use Flask route templates, not resolved paths.
Dynamic path parameters MUST be normalized to prevent cardinality explosion.

| | Example |
|---|---|
| **Correct** | `endpoint="/status/<run_id>"` |
| **Incorrect** | `endpoint="/status/a1b2c3d4-e5f6..."` |

### Compliance Notes

- **Rule 1 (Engine Immutability):** No engine changes. Metrics are collected in the Flask layer and Kubernetes infrastructure.
- **Rule 2 (API Contracts):** `/metrics` is an operational endpoint, not part of the backtest API contract. No existing endpoints are modified.
- **Rule 4 (Stateless Web):** `/metrics` serves in-memory counters only. No filesystem state.
- **Rule 8 (Observability):** Prometheus metrics complement (not replace) structured logging with `run_id`.
