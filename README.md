# Kubernetes 기반 주식 백테스트 플랫폼 (Stock Backtesting Platform)


<div align="center">
  <img src="https://img.shields.io/badge/Python-151515?style=for-the-badge&logo=python&logoColor=3776AB" alt="Python" />
  <img src="https://img.shields.io/badge/Flask-151515?style=for-the-badge&logo=flask&logoColor=white" alt="Flask" />
  <img src="https://img.shields.io/badge/SQLAlchemy-151515?style=for-the-badge&logo=python&logoColor=D71F00" alt="SQLAlchemy" />
  <img src="https://img.shields.io/badge/Jinja2-151515?style=for-the-badge&logo=jinja&logoColor=white" alt="Jinja2" />
  <img src="https://img.shields.io/badge/Bootstrap-151515?style=for-the-badge&logo=bootstrap&logoColor=7952B3" alt="Bootstrap" />
  
  <br/>
  
  <img src="https://img.shields.io/badge/MySQL-151515?style=for-the-badge&logo=mysql&logoColor=4479A1" alt="MySQL" />
  <img src="https://img.shields.io/badge/Docker-151515?style=for-the-badge&logo=docker&logoColor=2496ED" alt="Docker" />
  <img src="https://img.shields.io/badge/Kubernetes-151515?style=for-the-badge&logo=kubernetes&logoColor=326CE5" alt="Kubernetes" />
  <img src="https://img.shields.io/badge/GitHub_Actions-151515?style=for-the-badge&logo=github-actions&logoColor=2088FF" alt="GitHub Actions" />
  <img src="https://img.shields.io/badge/ArgoCD-151515?style=for-the-badge&logo=argo&logoColor=EF7B4D" alt="Argo CD" />
</div>

> **동기식 레거시 백테스트 엔진을 변경하지 않고, 실행을 Kubernetes Job으로 외부화해 격리·확장·재현성을 확보한 모더니제이션 프로젝트**

![Dashboard Hero](docs/images/01_dashboard_hero.png)

---

## 한 줄 요약

검증된(수정 금지) Python 백테스트 엔진을 컨테이너로 감싸고, 각 백테스트를 **독립적인 Kubernetes Job**으로 실행하도록 설계한 **배치 실행(Backtesting) 플랫폼**입니다.

---

## 프로젝트 개요

이 프로젝트의 목표는 “레거시 시스템의 클라우드 전환(Modernization)”입니다.

- **레거시 엔진은 Read-only**로 유지하고(로직 변경 금지),
- 실행 경로를 **Web(요청/조회)** 과 **Worker(Job 실행)** 로 분리해,
- **실행 격리, 수평 확장, 재현 가능한 배포**를 인프라 레벨에서 해결합니다.

핵심 키워드:
- **Execution isolation**: 백테스트 1회 = Job 1개(실패 도메인 분리)
- **GitOps**: `k8s/` 매니페스트가 인프라의 단일 진실 공급원, Argo CD가 reconcile
- **Traceability**: Web → Job → DB 전 구간 `run_id`로 요청 추적

> 설계/계약/세부 규칙은 `CLAUDE.md`(Design Spec)에서 관리합니다.

---

## Why Kubernetes Jobs?

백테스트는 전형적인 **embarrassingly parallel batch workload**입니다. 요청당 CPU/메모리 사용량이 크고 실행 시간이 길어, Web 프로세스 내부에서 동기 처리하면 다음 문제가 빠르게 드러납니다.

- **트래픽 스파이크 시 Web 안정성 저하** (요청 처리와 무거운 연산이 동일 프로세스/리소스에 공존)
- **실행 실패의 전파** (하나의 작업 실패가 Web 워커/프로세스에 영향을 줄 수 있음)
- **스케일 정책의 부자연스러움** (Web 스케일링과 백테스트 실행 스케일링이 결합됨)

대안도 고려했습니다.
- **Gunicorn 워커 확장**: 간단하지만 실행 격리/자원 통제가 약하고, Web 안정성과 결합됨
- **Celery + Broker**: 분산 실행에는 적합하지만 별도 런타임/운영면(브로커, 워커 풀, 라우팅)을 추가로 가져감
- **Kubernetes Jobs**: 배치 실행을 “클러스터 스케줄링 문제”로 전환해 **자원 격리/재시도/TTL 정리/쿼터**를 일관되게 적용 가능

결론적으로 이 프로젝트는 “클라우드 교육 + 포트폴리오” 목적에 맞춰,
- **실행 단위를 Job으로 분리**하고,
- Web은 stateless하게 유지하며,
- 클러스터 레벨에서 실행/실패/자원/정리를 다루는 방향을 선택했습니다.

> 트레이드오프(운영 복잡도 증가, Job cold-start, K8s 운영 지식 필요)는 명확히 존재하며, 이를 감수하는 대신 실행 격리/확장/운영 정책의 일관성을 얻습니다.

---

## 핵심 기능

### 1) 매매 타점 시각화 (Portfolio Analysis)
서버에서 Matplotlib(Agg)로 렌더링한 차트를 UI에 인라인으로 제공하며(로컬 파일 저장 없음),  
주가 라인 위에 매수(▲)/매도(▼) 시점을 표시하고 트레이드 손익(PnL)을 산점도로 시각화합니다.

![Portfolio Analysis](docs/images/05_ui_portfolio_analysis.png)

### 2) 핵심 지표(KPI) 요약 (Key Metrics)
백테스트 완료 즉시 총 수익률, 샤프 지수, MDD, 거래 횟수 등 핵심 KPI를 계산해 제공합니다.

![Stats KPI](docs/images/02_ui_stats_kpi.png)

추가 스크린샷(Equity/Drawdown/Cumulative Return/Trades):
- [docs/screenshots.md](docs/screenshots.md)

---

## Quick Start (Local)

> 모든 명령은 프로젝트 루트에서 실행합니다.

### Prerequisites
- Python 3.11+
- pip

### Run
```bash
pip install -r requirements.txt
python app.py
````

대시보드: [http://localhost:5000](http://localhost:5000)

### Test

```bash
python -m pytest tests/ -v
```

---

## 아키텍처 (Target: Phase 3 이후)

Web은 요청/검증/조회만 담당하고, 무거운 연산은 Job(Worker)로 분리합니다.
상태/결과는 MySQL을 단일 진실 공급원으로 사용합니다.

![Architecture Overview](docs/images/10_architecture_overview.png)

핵심 설계 포인트:

1. **Web–Worker 분리**: Web 안정성과 실행 확장을 분리
2. **Data plane은 MySQL**: 결과/상태 교환을 DB로 일원화
3. **GitOps**: CI는 이미지 생성/승격, CD는 선언형 매니페스트 기반 reconcile

상세:

* [docs/architecture.md](docs/architecture.md)

---

## 인프라 구성 (Cloud-Native)

### 로컬 패리티 (Phase 1)

* Docker multi-stage 이미지(`python:3.11-slim`)
* `docker compose up`로 web + mysql 개발 환경 구성
* 설정/시크릿은 `.env` 기반 (`.env.example`만 커밋)

### Kubernetes 런타임 (Phase 2–3)

* Namespace: `stock-backtest`
* Web: Deployment + Service + Ingress
* DB: MySQL StatefulSet + PVC
* Worker: Job(백테스트 1회 실행 후 종료)
* ConfigMap/Secret로 환경변수 주입
* Web ServiceAccount는 namespace-scoped Role/RoleBinding으로 `jobs.batch`에 대해서만 최소 권한 부여(ClusterRole 사용하지 않음)

### GitOps 배포 (Phase 4)

* CI: GitHub Actions → 테스트 → 이미지 빌드/푸시(불변 태그)
* CD: Argo CD가 `k8s/` 변경을 감지해 auto-sync

### 관측성 (Phase 5)

* 모든 실행에 `run_id(UUID4)` 부여
* Web/Worker/DB 로그에서 `run_id`로 end-to-end 추적 가능(stdout/stderr 로깅)

---

## 설계상 비협상 조건 (Non‑negotiables)

| 항목          | 결정                                              |
| ----------- | ----------------------------------------------- |
| Engine      | 레거시 엔진 로직 변경 금지(확장은 Adapter/Wrapper로만)          |
| Web         | Stateless: 로컬 파일 write 금지(차트는 메모리에서 Base64 인라인) |
| Image Tag   | 불변 태그 사용(배포 추적/재현성), `latest` 미사용               |
| RBAC        | namespace-scoped 최소 권한( Jobs 생성/조회/삭제 범위 제한 )   |
| Secrets     | 템플릿만 커밋, 실 시크릿은 외부 주입(커밋 금지)                    |
| Schema Init | Production에서 자동 create_all 금지(운영자 1회 초기화 절차)    |

---

## API Endpoints

| Method   | Path                   | 설명                                       |
| -------- | ---------------------- | ---------------------------------------- |
| `GET`    | `/`                    | 웹 대시보드                                   |
| `POST`   | `/run_backtest`        | 백테스트 실행 (현재는 동기 실행 / Phase 3에서 Job 비동기화) |
| `GET`    | `/api/strategies`      | Strategy preset 목록                       |
| `POST`   | `/api/strategies`      | Strategy preset 저장                       |
| `DELETE` | `/api/strategies/<id>` | Strategy preset 삭제                       |
| `GET`    | `/health`              | 헬스체크                                     |
| `GET`    | `/status/<run_id>`     | (Phase 3) run 상태 조회                      |

---

## Project Structure

```text
stock_backtest/
|
|-- CLAUDE.md                          # 프로젝트 규칙/계약/아키텍처 (SSOT)
|-- README.md                          # 이 문서
|-- RETROSPECTIVE.md                   # 기술 회고/면접 대비 Q&A
|-- requirements.txt                   # Python 의존성 (Poetry/Pipenv 금지)
|-- .gitignore                         # Git 제외 규칙 (strategies.db 등)
|-- test_structure.py                  # 구조 검증 테스트
|-- app.py                             # ✅ Flask 애플리케이션 진입점 (Web/Controller)
|-- worker.py                          # [Phase 3] K8s Job Worker 진입점
|-- extensions.py                      # ✅ SQLAlchemy 인스턴스 (순환 import 방지)
|-- models.py                          # ✅ Strategy ORM 모델
|-- Dockerfile                         # [Phase 1] Multi-stage Docker 빌드
|-- docker-compose.yml                 # [Phase 1] 로컬 개발: web + mysql
|-- .env.example                       # [Phase 1] 환경변수 템플릿
|-- .dockerignore                      # [Phase 1] __pycache__/, .env 등 제외 (data/는 포함)
|
|-- .github/                           # [Phase 4] CI
|   +-- workflows/
|       +-- ci.yml                     # pytest → build → push (immutable tag)
|
|-- backtest/                          # 핵심 엔진 (READ-ONLY)
|   |-- __init__.py
|   |-- engine.py                      # BacktestEngine -- 수정 금지 (Rule 1)
|   +-- metrics.py                     # PerformanceMetrics
|
|-- rules/                             # 트레이딩 룰 라이브러리
|   |-- __init__.py
|   |-- base_rule.py                   # BaseRule, Signal, RuleMetadata, CompositeRule
|   |-- technical_rules.py             # ✅ RSI, MACD, RSI+MACD 등
|   |-- paper_rules.py                 # Momentum, Value 등
|   |-- rule_validator.py              # RuleValidator, SignalAnalyzer
|   +-- optimizer.py                   # ParameterOptimizer (Grid Search)
|
|-- extracted/
|   +-- features/
|       |-- __init__.py
|       +-- technical_indicators.py    # SMA, EMA, RSI, MACD, BB, ATR 등
|
|-- scripts/
|   |-- config.py                      # 환경변수 기반 설정(Config)
|   |-- data_loader.py                 # 데이터 로더 (yfinance 다운로드 + 검증)
|   |-- logger_config.py               # stdout/stderr 로깅 설정 (Rule 8)
|   |-- qa_prices.py                   # 데이터 품질 검증
|   |-- verify_mvp.py                  # E2E 파이프라인 검증
|   +-- demo.sh                        # [Phase 5] 고정 시나리오 E2E 데모 스크립트
|
|-- adapters/                          # ✅ Adapter Layer (Rule 1 준수)
|   |-- __init__.py
|   +-- adapter.py                     # derived curves/metrics + render_*_chart
|
|-- tests/                             # ✅ Test Suite
|   |-- __init__.py
|   +-- test_day39.py                  # 83 tests
|
|-- templates/
|   +-- index.html                     # ✅ Bootstrap 5 Dark Mode 대시보드
|
|-- k8s/                               # [Phase 2-3] Kubernetes 매니페스트 (GitOps Source of Truth)
|   |-- namespace.yaml
|   |-- configmap.yaml
|   |-- secret-template.yaml           # Template only; real secrets via CI/CD or Sealed Secrets
|   |-- web-deployment.yaml
|   |-- worker-job-template.yaml
|   |-- mysql-statefulset.yaml
|   |-- rbac.yaml                      # SA + Role + RoleBinding (namespace-scoped, jobs.batch only)
|   +-- ingress.yaml
|
|-- docs/                              # [Phase 6] 프로젝트 문서
|   |-- architecture.md                # 아키텍처 다이어그램 (Mermaid)
|   |-- ops-guide.md                   # 운영 가이드 (배포/롤백/트러블슈팅)
|   |-- screenshots.md                 # ✅ UI 스크린샷 갤러리 (이 파일)
|   +-- images/                        # README/Docs용 이미지
|
|-- data/                              # OHLCV CSV 데이터 (재현성 목적)
|   +-- AAPL.csv
```


---

## Roadmap (Phase)

| Phase | 상태 | 범위 |
|---|---|---|
| Phase 0 | 완료 | 엔진 검증 + Flask 앱 + Adapter + 5탭 UI + 테스트 |
| Phase 1 | 예정 | Dockerization & Local Parity (Dockerfile, Compose, `.env.example`, healthcheck) |
| Phase 2 | 예정 | Kubernetes Runtime + Data Layer (Web Deployment, MySQL StatefulSet, ConfigMap/Secret, Ingress) |
| Phase 3 | 예정 | Web → K8s Job Orchestration (`worker.py`, JobLauncher, `/status/<run_id>`, 결과/상태 MySQL persist) |
| Phase 4 | 예정 | Automation & GitOps (GitHub Actions CI, Argo CD CD, tag promotion) |
| Phase 5 | 예정 | Observability 검증(Rule 8) + `scripts/demo.sh` 데모 |
| Phase 6 | 예정 | 문서화/회고 (architecture, ops guide, retrospective polish) |

---

## Git Workflow (요약)

* `feature/*`에서 작업 → PR → `dev` → `main`
* GitOps 대상은 `k8s/` 디렉터리
* 배포는 선언형 매니페스트 변경을 통해 이루어지도록 유지

---

## 문서

* 설계/계약: `CLAUDE.md`
* 아키텍처 상세: [docs/architecture.md](docs/architecture.md)
* 운영 가이드: [docs/ops-guide.md](docs/ops-guide.md)
* UI 갤러리: [docs/screenshots.md](docs/screenshots.md)

