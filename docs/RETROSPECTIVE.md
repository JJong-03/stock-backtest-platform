# Technical Retrospective & Architecture Overview

> **Note:** `docs/RETROSPECTIVE.md` is a **historical record** of engineering decisions made during Day 1–3.9 implementation.
> For **normative** architectural invariants, operational rules, and contracts (Day 4+), refer to **`CLAUDE.md`**, which serves as the Single Source of Truth.

> Day 1 ~ Day 3.9 구현 기반. 실제 코드베이스에서 확인 가능한 설계 결정만 기술.

---

## 1. Developer Perspective (Software Engineering)

### 1.1 Architecture & Separation of Concerns

**핵심 결정: `backtest/engine.py`를 Immutable Core로 취급**

- `BacktestEngine.run(data, strategy_func, ticker)`은 DataFrame과 callable 하나만 받아 결과 dict를 반환하는 **순수 연산 유닛**
- 엔진은 "데이터가 어디서 왔는지", "전략이 어떤 룰인지", "결과를 어디에 저장하는지" 전혀 모름
- 이 설계 덕분에 엔진 위에 Web Controller, CLI Script, K8s Worker 등 **어떤 실행 컨텍스트든 교체 가능**

**대안: 엔진 내부에 I/O와 전략 로직을 통합하는 방식**
- 엔진이 직접 CSV를 읽고, 지표를 계산하고, 차트를 저장하는 monolithic 구조
- 이 경우 엔진을 수정하지 않으면 날짜 필터링 하나 추가할 수 없음
- 엔진 변경은 **모든 백테스트 결과의 재현성(Reproducibility)을 위협**하므로 거부

**실제 구현에서의 역할 분리:**

| 계층 | 책임 | 파일 |
|------|------|------|
| **Controller** | Input validation, date filtering, indicator 계산, HTTP 응답 | `app.py` |
| **Rule Layer** | 전략 로직 (evaluate → Signal) | `rules/technical_rules.py` |
| **Strategy Adapter** | Rule.evaluate() → engine-compatible callable 변환 | `app.py:_build_strategy()` |
| **Response Adapter** | 엔진 출력 → UI-ready 데이터 변환, 차트 렌더링 | `adapters/adapter.py` |
| **Engine** | 순수 시뮬레이션 (buy/sell 실행, portfolio 추적, report 생성) | `backtest/engine.py` |

`app.py` 첫 줄 docstring이 `"Controller layer only -- does NOT modify engine logic."` 인 이유는 이 원칙을 코드 레벨에서 선언하기 위함.

---

### 1.2 Extensibility & OCP (Open-Closed Principle)

**핵심 결정: Strategy Pattern으로 전략 확장**

- `BaseRule`(abstract class) → `RSIRule` / `MACDRule` / `RsiMacdRule` 상속 구조
- 각 Rule은 `evaluate(row) → Signal`과 `get_required_features() → List[str]`을 구현
- 새 전략 추가 시 engine.py **한 줄도 수정하지 않음**

**Adapter 패턴의 역할 (`_build_strategy`):**
- 엔진은 `strategy_func(row) → 'buy'/'sell'/None` 형태의 단순 callable만 이해
- Rule 객체는 `Signal(action, confidence, reasoning)` 이라는 풍부한 객체를 반환
- `_build_strategy()`가 이 간극을 브릿지: `signal.action`만 추출하여 엔진에 전달
- 엔진 입장에서는 RSI든 MACD든 동일한 interface — **의존성 역전(DIP)** 적용

**대안: 엔진 내부에 `if strategy == "RSI": ...` 분기를 추가하는 방식**
- 전략이 추가될 때마다 engine.py를 수정해야 함 → OCP 위반
- 전략 로직과 실행 로직이 결합되어 **단위 테스트 불가능**
- 실제로 RSI → MACD → RSI+MACD 세 번의 전략 추가에서 engine.py 변경 횟수: **0회**

**`Signal` dataclass의 설계 의도:**
- `action`(buy/sell/hold)뿐만 아니라 `confidence`(0~1)와 `reasoning`(문자열)을 포함
- 현재 엔진은 action만 사용하지만, 향후 confidence 기반 position sizing이나 로깅에 확장 가능
- `__post_init__`에서 action 유효성과 confidence 범위를 즉시 검증 — **생성 시점 방어**

---

### 1.3 Defensive Programming & Data Integrity

**핵심 결정: Fail-Fast with Explicit Error Categories**

이 시스템의 에러 처리는 **"복구 시도 없이 즉시 실패"** 원칙을 따름:

**HTTP 400 (User Error) — 엔진 호출 전 차단:**
- `start_date`/`end_date` 키 누락 → 즉시 400 (엔진 미호출)
- `start_date > end_date` → 즉시 400
- 필터링 후 `df.empty` → 즉시 400
- 알 수 없는 strategy key → 즉시 400
- `secure_filename()` 통과 후 파일 미존재 → 400

**HTTP 500 (System Error) — CSV/DB 장애:**
- `pd.to_datetime(df["Date"])` 실패 → 500 + `"Failed to load or parse CSV data"`
- DB `commit()` 실패 → 500 + rollback

**날짜 처리에서 `pd.to_datetime` + `tz_localize(None)`을 명시적으로 사용하는 이유:**
- `parse_dates=True`만으로는 timezone-aware 데이터(yfinance 출력)와 timezone-naive 데이터가 혼재할 수 있음
- `tz_localize(None)`은 모든 datetime을 **UTC-naive로 정규화**하여 비교 연산 시 `TypeError: Cannot compare tz-naive and tz-aware` 방지
- 이 에러는 production에서 **특정 종목에서만 간헐적으로 발생**하기 때문에 테스트에서 잡기 어려움

**대안: `errors="coerce"`로 파싱 실패를 NaT로 변환하는 방식**
- 잘못된 데이터가 NaT로 조용히 변환되어 **백테스트가 누락된 날짜로 실행됨**
- 이는 "Silent data corruption" — 결과가 틀렸는데 에러가 나지 않는 최악의 상황
- 따라서 파싱 실패 시 즉시 500을 반환하여 **데이터 문제를 숨기지 않음**

**`run_id` (UUID4) Observability 패턴:**
- 모든 백테스트 요청에 `run_id = str(uuid.uuid4())` 부여
- 모든 로그 라인에 `[run_id=...]` 포함
- K8s 환경에서 여러 Pod의 로그가 섞여도 **단일 요청 추적 가능**

---

### 1.4 Persistence Layer Design

**핵심 결정: SQLAlchemy ORM + JSON Column (Opaque Blob Pattern)**

`Strategy` 모델의 `params` 컬럼을 `db.JSON`으로 정의한 이유:

- RSI는 `{period, oversold, overbought}`, MACD는 `{fast, slow, signal}`, RSI+MACD는 **6개 파라미터**
- 전략마다 파라미터 스키마가 다르므로, 정규화하면 **전략 추가 시 매번 ALTER TABLE 필요**
- JSON 컬럼은 이 params를 **opaque blob**으로 저장 — DB는 내부 구조를 모르고, 앱 계층에서만 해석

**Opaque Blob 패턴의 의미:**
- DB에서 `params` 내부를 `WHERE params->rsi_period = 14`로 질의하지 않음
- params는 "저장하고 그대로 반환"하는 용도 — **UI preset 복원용**
- 이렇게 하면 SQLite/MySQL/PostgreSQL 모두 동일하게 동작 (JSON 지원만 있으면 됨)

**대안 1: params를 별도 테이블로 정규화 (key-value 구조)**
- `strategy_params(strategy_id, key, value)` 형태
- 장점: SQL 질의 가능
- 단점: 전략 추가 시 스키마 변경, JOIN 필요, 타입 정보 손실 (모든 value가 string)

**대안 2: 전략별 전용 테이블 생성**
- `rsi_strategies`, `macd_strategies` 각각 생성
- 단점: 전략 추가 시 새 테이블 + 새 API + 코드 변경 → OCP 완전 위반

**SQLAlchemy를 Raw SQL 대신 선택한 이유:**
- `db.session.rollback()`이 모든 exception handler에 존재 — ORM이 transaction boundary를 명시적으로 관리
- `IntegrityError` catch로 duplicate name을 HTTP 409로 변환 — Raw SQL에서는 vendor-specific 에러 코드 파싱 필요
- `Strategy.query.order_by(...)` 같은 체이닝이 **SQLite와 MySQL 모두에서 동일하게 동작** — 마이그레이션 비용 제로

---

## 2. Infrastructure Perspective (DevOps & Cloud-Native)

### 2.1 Stateless Architecture

**핵심 결정: Web 계층은 로컬 파일시스템에 절대 쓰지 않음**

- 차트 렌더링: `fig.savefig(buf)` → `BytesIO` 메모리 버퍼 → Base64 string → JSON 응답
- 백테스트 결과: 엔진이 dict로 반환 → `app.py`가 JSON으로 직렬화 → HTTP 응답
- `/tmp/chart.png` 같은 임시 파일 **일절 없음**

**이것이 Kubernetes에서 중요한 이유:**
- K8s Deployment에서 Flask replica를 2개 이상 실행할 때, 각 Pod는 **독립된 파일시스템**을 가짐
- Pod A가 `/tmp/chart.png`를 생성하면 Pod B의 다음 요청에서는 접근 불가
- Stateless 설계 덕분에 `replicas: 2` → `replicas: 10`으로 변경해도 **코드 변경 없음**
- Pod가 crash하더라도 상태 손실 없음 — **Self-healing과 완벽 호환**

**대안: Redis나 Shared Volume을 사용하는 방식**
- 복잡도 증가, 추가 인프라 의존성
- Base64 인라인 반환은 추가 인프라 없이 stateless 보장 — Day 3 단계에서 최적

---

### 2.2 Configuration Management

**핵심 결정: 모든 설정을 `os.getenv()`로 주입**

실제 구현:
- `SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///strategies.db")`
- `FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "False")`

**12-Factor App Principle III (Config) 준수:**
- 코드와 설정의 완전한 분리
- 동일 Docker image가 `DATABASE_URL`만 바꿔서 **dev(SQLite) / staging(MySQL) / prod(MySQL+replica)** 에서 실행 가능
- K8s에서는 `ConfigMap`(비밀 아닌 값)과 `Secret`(DB 비밀번호)으로 환경변수 주입

**하드코딩 대비 이점:**
- `sqlite:///strategies.db`가 default fallback이므로 **환경변수 없이도 로컬에서 즉시 실행 가능**
- Production에서는 `DATABASE_URL=mysql+pymysql://user:pass@mysql-svc:3306/stock_backtest` 주입
- **코드 변경 없이** 데이터베이스 전환 완료

---

### 2.3 Resource Safety

**핵심 결정: Matplotlib Agg Backend + Explicit Figure Cleanup**

`matplotlib.use("Agg")`가 `import matplotlib.pyplot` **이전**에 호출되는 이유:
- Agg는 **Anti-Grain Geometry** 렌더러 — GUI 윈도우 시스템 의존성 없음
- 서버 환경(Docker, K8s Pod)에는 X11/Wayland가 없으므로, Agg 없이 pyplot을 import하면 **`_tkinter.TclError: no display` 즉시 crash**

`plt.close(fig)`가 `try...finally`에 있는 이유:
- Matplotlib는 생성된 Figure를 **전역 리스트에 보관** (garbage collection 대상이 아님)
- `close()` 없이 매 요청마다 Figure를 생성하면 **메모리가 누적**
- 100개 요청 × 12×5 inch figure ≈ **수백 MB 메모리 누수**
- K8s Pod의 memory limit에 도달하면 **OOMKilled** → 서비스 중단
- `finally` 블록이므로 렌더링 중 exception이 발생해도 **반드시 정리됨**

**대안: Figure를 global pool로 재사용하는 방식**
- Thread safety 문제, 이전 요청의 데이터가 다음 차트에 잔류할 위험
- 요청당 새 Figure 생성 + 즉시 해제가 가장 안전

---

### 2.4 Database Strategy (SQLite → MySQL)

**SQLite가 Day 3에서 허용되는 이유:**
- 단일 프로세스 로컬 개발에서는 충분
- 설치/설정 없이 `strategies.db` 파일 하나로 동작
- 빠른 프로토타이핑과 API 검증에 적합

**SQLite가 Production에서 불가능한 이유:**
- **Write lock**: 동시 쓰기 불가 — K8s에서 2개 Pod가 동시에 preset 저장 시 `database is locked`
- **파일 기반**: Pod 재시작 시 데이터 소실 (ephemeral filesystem)
- **네트워크 공유 불가**: Pod 간 SQLite 파일 공유 자체가 비지원

**`extensions.py` 패턴이 Zero-Code Migration을 가능하게 하는 방법:**
- `db = SQLAlchemy()`가 extensions.py에 독립 정의
- `app.py`에서 `db.init_app(app)` 으로 late binding
- MySQL 전환 시 변경점: 환경변수 `DATABASE_URL` **한 줄만 교체**
- ORM 쿼리(`Strategy.query...`, `db.session.add()`)는 SQLite/MySQL 동일

**`db.create_all()`을 `if __name__ == "__main__"` 안에 제한한 이유:**
- Import 시점에 schema mutation이 발생하면, Gunicorn worker 프로세스 4개가 **동시에 CREATE TABLE 실행**
- Production에서는 schema migration을 **Alembic 같은 전용 도구**로 관리해야 함
- `__main__` guard는 "로컬 개발에서만 자동 생성, production에서는 명시적 마이그레이션" 원칙

**Production Note (Day 4+):**
위의 `db.create_all()` 편의 기능은 **로컬 개발 환경에서만** 적용된다.
Production(K8s) 환경에서의 스키마 초기화는 `CLAUDE.md` Rule 9에 정의된 대로 **운영자가 명시적으로 실행하는 일회성 절차**(e.g., init Job or `kubectl exec`)로 취급되며, 자동 호출은 발생하지 않는다.

---

### 2.5 Security Considerations

**Path Traversal 방어:**
- 사용자 입력 `ticker_file`에 `secure_filename()`을 적용
- `../../etc/passwd`가 `etc_passwd`로 변환 — 디렉터리 탈출 불가
- 변환 후 `os.path.isfile(csv_path)` 추가 확인 — 실존 파일만 허용

**Transaction Safety (Broken Transaction 방어):**
- 모든 `db.session.commit()`이 `try/except` 안에 존재
- Exception 발생 시 **반드시** `db.session.rollback()` 호출
- Rollback 없이 다음 요청이 들어오면 **이전의 실패한 transaction이 session에 잔류** → 연쇄 에러
- `IntegrityError`(duplicate name)와 `Exception`(DB 장애)를 **분리 처리** — 409 vs 500 구분

**대안: Rollback 없이 session을 재생성하는 방식**
- Flask-SQLAlchemy는 기본적으로 request 종료 시 session을 정리하지만, **exception 도중 다른 DB 작업이 실행될 수 있음**
- Explicit rollback이 더 방어적이고 의도가 명확

---

### 2.6 Kubernetes & Operational Invariants (Post-Day 3.9)

> All policies referenced below are defined and governed by `CLAUDE.md`.
> 이 섹션은 해당 규칙들의 **엔지니어링 근거(Why)**만을 설명하며, 규칙 자체의 정의와 세부 사항은 `CLAUDE.md`가 Single Source of Truth이다.

**Namespace-Scoped RBAC (Role/RoleBinding, not ClusterRole):**
`CLAUDE.md` Section 3에 정의된 대로, Web Pod의 ServiceAccount는 namespace-scoped Role만 사용한다.
근거는 **최소 권한 원칙(Principle of Least Privilege)**과 **폭발 반경(blast radius) 억제**이다.
ClusterRole은 전체 클러스터의 모든 namespace에 영향을 미치므로, 단일 ServiceAccount 침해 시 다른 팀의 워크로드까지 위협한다.
Namespace-scoped Role은 권한을 `stock-backtest` namespace 내 `batch/v1` Jobs로만 한정하여, 멀티테넌트 클러스터에서의 격리를 보장한다.

**Ephemeral Worker Model (K8s Jobs):**
`CLAUDE.md` Phase 3에 정의된 대로, 각 백테스트는 독립된 K8s Job으로 실행된다.
백테스트는 CPU-bound 연산이므로 Job 단위 격리가 자연스럽다 — 하나의 장기 실행 요청이 다른 요청을 차단하지 않으며, `backoffLimit`로 재시도 의미론이 선언적으로 관리된다.
실패한 Job은 `ttlSecondsAfterFinished: 86400`으로 24시간 보존하여 로그 검사를 허용하고, 성공한 Job은 즉시 삭제하여 클러스터 리소스를 회수한다.

**Web ↔ Worker Decoupling via MySQL:**
`CLAUDE.md` Section 3 Invariants에 명시된 대로, MySQL이 결과의 유일한 source of truth이다.
근거는 **Pod 생명주기 독립성**이다 — Web Pod가 재시작되거나 Worker Job이 완료 후 삭제되어도 결과는 MySQL에 영구 보존된다.
In-memory 커플링(예: Redis pub/sub)이나 RPC 방식은 발신자와 수신자가 동시에 존재해야 하므로, K8s의 비동기적 Pod 스케줄링과 충돌한다.
DB 기반 교환은 재시도 안전성(idempotent write)과 `run_id` 기반 관찰성(observability)도 자연스럽게 제공한다.

**Reproducibility as a First-Class Property:**
`CLAUDE.md` Runtime & Data Contracts 섹션에 정의된 4가지 식별자(`data_hash`, `rule_type+params`, `engine_version`, `image_tag`)는 재현성을 수학적으로 검증 가능하게 만든다.
금융 시스템에서 "정확성(correctness)"만으로는 부족하다 — **설명 가능성(explainability)**과 **재현 가능성(replayability)**이 필수이다.
이는 곧 **감사 가능성(auditability)**의 문제이기도 하다: 백테스트 결과의 신뢰성은 사후 검증(post-hoc verification)이 가능할 때만 성립한다.
동일한 입력이 다른 결과를 생성한다면, 그것이 코드 변경 때문인지, 데이터 변경 때문인지, 환경 변경 때문인지 특정할 수 없다.
Immutable engine(Rule 1) + immutable image tags(Rule 10) + frozen params의 조합이 이 문제를 구조적으로 제거한다.

---

## 3. Day 3.9 — Adapter Layer & Advanced Visualization

### 3.1 Adapter Layer 도입 (`adapters/adapter.py`)

**핵심 결정: 엔진 출력 → UI-ready 데이터 변환을 독립 모듈로 분리**

Day 3까지는 `app.py` Controller 안에서 차트 렌더링과 데이터 변환이 섞여 있었음.
Day 3.9에서 `adapters/adapter.py`를 분리하여 **단일 책임 원칙(SRP)** 적용:

| 함수 | 책임 | 입력 → 출력 |
|------|------|-------------|
| `build_equity_curve()` | 엔진 결과 → equity time-series | engine dict → `[{date, equity}]` |
| `derive_drawdown_curve()` | equity → drawdown 계산 | equity_curve → `[{date, drawdown_pct}]` |
| `derive_portfolio_curve()` | equity + trades → 현금/포지션 분리 | equity + trades → `[{date, cash, position, total}]` |
| `normalize_trades()` | 엔진 trades → 표준 스키마 | raw trades → ISO8601 timestamps, fee 계산 |
| `render_orders_chart()` | Close 가격 + BUY/SELL 마커 | price_df + trades → Base64 PNG |
| `render_trade_pnl_chart()` | 거래별 손익 scatter | price_df + trades → Base64 PNG |
| `render_cumulative_return_chart()` | 누적 수익률 line chart | equity_curve → Base64 PNG |
| `render_drawdown_chart()` | Drawdown time-series chart | drawdown_curve → Base64 PNG |

**Rule 1 준수:** 모든 함수는 엔진 출력(equity, trades)만을 입력으로 사용.
엔진 내부 로직을 수정하거나 시그널 생성을 변경하지 않음.

---

### 3.2 Portfolio 시각화 리팩토링

**핵심 결정: 2-row subplot → 독립 차트 3개로 분리**

초기 구현은 `render_portfolio_plot()`이 Orders + Trade PnL을 하나의 2-row subplot으로 렌더링:
- 문제: 각 차트의 높이가 반으로 줄어 가독성 저하, 범례 위치 일관성 없음
- 해결: 세 개의 독립 함수로 분리 → 각각 `figsize=(12, 5)` 전체 너비 사용

| 변경 전 | 변경 후 |
|---------|---------|
| `portfolio_plot_base64` (2-row combined) | `portfolio_orders_base64` (독립) |
| ↑ 동일 키에 포함 | `trade_pnl_base64` (독립) |
| 별도 | `cumulative_return_base64` (독립) |

**API 계약 영향:**
- `portfolio_plot_base64` 키 **완전 삭제** (deprecated)
- `charts` 객체에 4개 키로 정규화: `drawdown_curve_base64`, `portfolio_orders_base64`, `trade_pnl_base64`, `cumulative_return_base64`
- 에러 응답에서도 동일 키를 `null`로 반환 → 프론트엔드 null-check 일관성

---

### 3.3 차트 렌더링 안전성 (Figure Leak Prevention)

**핵심 결정: 모든 render 함수에 `fig = None` + `try/except/finally` 패턴 적용**

```python
fig = None
try:
    fig, ax = plt.subplots(figsize=(12, 5))
    # ... render ...
    return f"data:image/png;base64,{b64}"
except Exception as e:
    logger.warning(f"render failed: {e}")
    return None
finally:
    if fig:
        plt.close(fig)
```

**테스트 검증 (83 tests, 0 warnings):**
- `plt.get_fignums()` 비교로 figure 누수 감지
- 빈 입력, 정상 입력, 연속 호출(5회 × 4함수) 모두 검증
- 빈 trades 리스트에서 `ax.legend()` 호출 시 `UserWarning` 발생 → 조건부 legend로 해결

---

### 3.4 VectorBT-Style 5-Tab Dashboard

**핵심 결정: 정보 밀도를 높이되, 인지 부하를 탭으로 분리**

| Tab | 데이터 소스 | 렌더링 방식 |
|-----|-------------|-------------|
| Stats | `metrics` (JSON) | KPI cards (client-side) |
| Equity | `chart_base64` (legacy) | Server-rendered PNG |
| Drawdown | `drawdown_curve` + `charts.drawdown_curve_base64` | Server-rendered PNG |
| Portfolio | `charts.portfolio_orders_base64` + `trade_pnl_base64` + `cumulative_return_base64` | Server-rendered PNG × 3 |
| Trades | `trades` (JSON array) | Client-side HTML table |

**Bloomberg Terminal 미학:**
- 배경: `#0a0a0a`, 텍스트: `#e0e0e0`, 강조: `#ff9900` (amber)
- 모노스페이스 숫자, 14px 최소 폰트
- 차트 스타일: dark facecolor, minimal spines, 0.15 alpha grid

---

## 4. Interview Q&A Preparation

### Q1 (Day 3): "매 요청마다 CSV를 읽는 건 비효율적이지 않나요? Caching은 왜 안 했나요?"

**Answer:**

맞습니다, I/O 비용이 있습니다. 하지만 의도적인 trade-off입니다.

**Caching을 하지 않은 이유:**
- 이 시스템은 K8s Pod로 실행될 예정이고, in-memory cache는 **Pod마다 독립** — cache coherence 문제 발생
- Redis 같은 외부 캐시를 도입하면 Day 3 단계에서 불필요한 인프라 복잡도 추가
- CSV 파일은 OHLCV 데이터로, 약 6,000행(25년 일봉) × 7컬럼 — `pd.read_csv`로 약 30ms 이내 로드

**Production에서의 개선 방향:**
- Day 5(K8s + MySQL)에서는 OHLCV 데이터 자체를 MySQL에 저장 → 캐시 불필요
- 또는 K8s Job Worker 패턴에서는 각 Job이 독립 실행이므로 캐시 자체가 무의미

**핵심:** Stateless 원칙을 지키면서, 현재 성능 병목이 아닌 부분을 조기 최적화하지 않은 것입니다.

---

### Q2 (Day 3): "RDB에 JSON 컬럼을 쓰면 정규화 원칙에 어긋나는 거 아닌가요?"

**Answer:**

전통적인 DB 정규화 관점에서는 맞습니다. 하지만 이 경우 **의도적으로 비정규화**한 것입니다.

**JSON 컬럼을 선택한 구체적 이유:**
- `params`는 전략 유형마다 스키마가 다름: RSI는 3개, MACD는 3개, RSI+MACD는 6개 파라미터
- 새 전략이 추가될 때마다 DB 스키마를 변경하면 **배포 파이프라인에 ALTER TABLE이 포함**되어야 함
- `params`에 대한 DB-level 질의(`WHERE params->'period' = 14`)는 요구사항에 없음 — 이 데이터는 "저장하고 그대로 반환"하는 용도

**정규화가 맞는 경우 vs Opaque Blob이 맞는 경우:**
- DB가 데이터를 **해석하고 질의해야 하면** → 정규화
- DB가 데이터를 **투명하게 보관하고 앱이 해석하면** → Opaque Blob
- Strategy preset의 params는 후자에 해당

**추가적으로,** SQLite와 MySQL 모두 JSON 타입을 지원하므로 **DB 마이그레이션 시에도 호환성 유지**.

---

### Q3 (Day 3): "Flask에서 Circular Import를 어떻게 방지했나요?"

**Answer:**

`extensions.py`에 `db = SQLAlchemy()`를 독립 정의하는 패턴을 사용했습니다.

**문제 상황:**
- `app.py`에서 `db = SQLAlchemy(app)` 으로 초기화하면, `models.py`가 `from app import db`를 해야 함
- 그런데 `app.py`도 `from models import Strategy`를 해야 함
- 결과: `app.py ↔ models.py` 순환 참조 → `ImportError`

**해결 패턴:**
- `extensions.py`: `db = SQLAlchemy()` — app 인스턴스 없이 생성
- `models.py`: `from extensions import db` — extensions만 의존
- `app.py`: `from extensions import db` + `db.init_app(app)` — late binding

**의존성 그래프:**
- `extensions.py` ← `models.py` (단방향)
- `extensions.py` ← `app.py` (단방향)
- `models.py` ← `app.py` (단방향)
- 순환 없음

**이 패턴이 Application Factory와 호환되는 이유:**
- 향후 `create_app()` 팩토리 함수로 전환할 때, `db.init_app(app)` 호출 위치만 변경하면 됨
- `extensions.py`와 `models.py`는 **변경 없이** 재사용 가능

---

### Q4 (Day 3.9): "Adapter 모듈을 왜 별도 디렉터리로 분리했나요? app.py에 두면 안 되나요?"

**Answer:**

가능은 합니다. 하지만 의도적으로 분리한 이유가 있습니다.

**분리 이유:**
- `app.py`는 이미 Flask 라우팅, 입력 검증, 에러 핸들링, DB 세션 관리를 담당 — 약 570줄
- Adapter 함수들(equity curve 빌드, drawdown 계산, 4개 차트 렌더링)만 **715줄**
- 합치면 1,280줄의 단일 파일 → **가독성과 테스트 격리 모두 악화**

**테스트 격리 이점:**
- `adapters/adapter.py`의 함수들은 **Flask app context 없이** 단위 테스트 가능
- `render_orders_chart(price_df, trades)` — 순수 함수, HTTP 요청과 무관
- `app.py`의 라우트 테스트는 Flask test client 필요 → 느리고 복잡
- 분리 덕분에 83개 테스트 중 adapter 테스트가 **app context 없이 빠르게 실행**

**Day 5+ 확장성:**
- K8s Worker(`worker.py`)도 동일한 adapter 함수를 재사용 가능
- Controller가 바뀌어도(Flask → FastAPI 등) adapter는 그대로

---

### Q5 (Day 3.9): "차트를 서버에서 렌더링하는 이유는? 클라이언트 측 Chart.js가 더 효율적이지 않나요?"

**Answer:**

맞습니다, 일반적으로는 클라이언트 렌더링이 서버 부하 측면에서 유리합니다.

**서버 렌더링을 선택한 이유:**
- 프로젝트 제약: **Jinja2 + Bootstrap 5 only, NO React/Vue/SPA** (CLAUDE.md Rule)
- Chart.js는 npm 번들링이나 CDN 의존 → 이 프로젝트의 기술 스택 범위 밖
- Matplotlib Agg는 이미 Python 의존성에 포함, 추가 인프라 불필요
- K8s Worker에서도 동일한 차트 생성 가능 → **실행 환경 일관성**

**Trade-off 인지:**
- 서버 CPU 부하: 차트 4개 렌더링 ≈ 200ms (허용 범위)
- Base64 전송량: 각 PNG 약 20-50KB → 총 80-200KB (API 응답 크기 증가)
- 대규모 동시 요청 시 서버 부하 → K8s horizontal scaling으로 해결 (Pod replica 증가)
