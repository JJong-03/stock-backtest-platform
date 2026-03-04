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

> **검증된 동기식 백테스트 엔진을 수정 없이 Kubernetes Job으로 외부화해, 격리·확장·재현성을 인프라 레벨에서 확보한 프로젝트**


![Dashboard Hero](https://raw.githubusercontent.com/wiki/msp-architect-2026/kim-jongwon/images/01_dashboard_hero.png)

---

## Core Design

- **Immutable Engine** — 레거시 엔진 로직 변경 금지, 확장은 Adapter/Wrapper로만
- **1 Backtest = 1 K8s Job** — 실행 격리/자원 통제/TTL 정리를 클러스터 레벨에서 처리
- **Stateless Web + Ephemeral Worker** — Web은 요청/조회만, Worker는 단일 실행 후 종료
- **Reproducibility** — 동일 입력(`ticker`, `rule_type+params`, `start/end`, `data_hash`, `image_tag`)이면 동일 출력
- **GitOps** — `k8s/` 매니페스트가 인프라의 단일 진실 공급원, Argo CD reconcile
- **run_id Tracing** — Web → Job → DB 전 구간 UUID4 기반 추적

---

## Architecture Overview

![Architecture Overview](https://raw.githubusercontent.com/wiki/msp-architect-2026/kim-jongwon/images/10_architecture_overview.png)

Web(Stateless)은 요청/조회만 담당하고, 백테스트 실행은 K8s Job(Worker)로 분리해 **1 run = 1 execution** 격리 모델을 구성합니다.  
CPU/메모리 집약적인 batch workload를 클러스터 스케줄링 문제로 전환함으로써 자원 통제·실패 도메인 분리·TTL 정리를 일관되게 적용하고, 
그 대신 운영 복잡도 증가라는 트레이드오프를 수용합니다.

> 대안(Celery, Gunicorn) 비교 및 상세 설계 결정은 [Wiki ADR](https://github.com/msp-architect-2026/kim-jongwon/wiki/ADR-Design-Decisions)을 참고하세요.

---

## 핵심 기능

### 매매 타점 시각화 (Portfolio Analysis)

서버에서 Matplotlib(Agg)로 렌더링한 차트를 UI에 인라인으로 제공하며(로컬 파일 저장 없음), 주가 라인 위에 매수(▲)/매도(▼) 시점을 표시하고 트레이드 손익(PnL)을 산점도로 시각화합니다.

![Portfolio Analysis](https://raw.githubusercontent.com/wiki/msp-architect-2026/kim-jongwon/images/05_ui_portfolio_analysis.png)

### 핵심 지표(KPI) 요약 (Key Metrics)

백테스트 완료 즉시 총 수익률, 샤프 지수, MDD, 거래 횟수 등 핵심 KPI를 계산해 제공합니다.

![Stats KPI](https://raw.githubusercontent.com/wiki/msp-architect-2026/kim-jongwon/images/02_ui_stats_kpi.png)

> 추가 스크린샷(Equity/Drawdown/Cumulative Return/Trades)은 [Wiki UI 화면구성](https://github.com/msp-architect-2026/kim-jongwon/wiki/UI-%ED%99%94%EB%A9%B4%EA%B5%AC%EC%84%B1)에서 확인할 수 있습니다.

---

## Quick Start (Local)

아래는 **로컬 동기 실행 모드**(Flask 단독, DB/K8s 불필요)입니다. Kubernetes 클러스터 배포 및 Job 기반 비동기 실행은 [Wiki Runbook](https://github.com/msp-architect-2026/kim-jongwon/wiki/Runbook-Troubleshooting)을 참고하세요.

```bash
pip install -r requirements.txt
python app.py
```

Dashboard: [http://localhost:5000](http://localhost:5000)

```bash
python -m pytest tests/ -v
```

---

## Documentation

상세 설계/운영 문서는 **[GitHub Wiki](https://github.com/msp-architect-2026/kim-jongwon/wiki)** 에서 관리합니다.

| 카테고리 | 문서 |
|---|---|
| **Start Here** | [Design Principles](https://github.com/msp-architect-2026/kim-jongwon/wiki/Design-Principles) · [Execution Lifecycle](https://github.com/msp-architect-2026/kim-jongwon/wiki/Execution-Lifecycle) · [Reproducibility](https://github.com/msp-architect-2026/kim-jongwon/wiki/Reproducibility) · [Scope & Non-Goals](https://github.com/msp-architect-2026/kim-jongwon/wiki/Scope-%26-Non-Goals) |
| **Architecture & Ops** | [Infra Architecture](https://github.com/msp-architect-2026/kim-jongwon/wiki/Infra-Architecture) · [ADR (Design Decisions)](https://github.com/msp-architect-2026/kim-jongwon/wiki/ADR-Design-Decisions) · [Runbook](https://github.com/msp-architect-2026/kim-jongwon/wiki/Runbook-Troubleshooting) · [E2E Demo Verification](docs/e2e-demo-verification.md) |
| **Reference** | [API & Schemas](https://github.com/msp-architect-2026/kim-jongwon/wiki/API-Endpoints-%26-Schemas) · [ERD](https://github.com/msp-architect-2026/kim-jongwon/wiki/ERD-Data-Model) · [Security Model](https://github.com/msp-architect-2026/kim-jongwon/wiki/Security-Model) · [Testing Strategy](https://github.com/msp-architect-2026/kim-jongwon/wiki/Testing-Strategy) · [UI 화면구성](https://github.com/msp-architect-2026/kim-jongwon/wiki/UI-%ED%99%94%EB%A9%B4%EA%B5%AC%EC%84%B1) · [Glossary](https://github.com/msp-architect-2026/kim-jongwon/wiki/Glossary) |