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

> **검증된 레거시 동기식 백테스트 엔진을 수정하지 않고,**
> **실행 모델만 Kubernetes Job 기반 비동기로 전환**해  
> **격리(1 run = 1 job) · 확장 · 재현성(data_hash/image_tag) · GitOps 배포**를 인프라 레벨에서 확보한 플랫폼

**Project Status:** Phase 3 ✅ Completed · Phase 4 🚧 In Progress (CI/CD + GitOps automation)

---

## Core Design

- **Immutable Engine** — 레거시 엔진 로직 변경 금지(확장은 Adapter/Wrapper로만)
- **1 Backtest = 1 K8s Job** — 실행 격리/자원 통제/TTL 정리를 클러스터 레벨에서
- **Stateless Web + Ephemeral Worker** — Web은 요청/조회만, Worker는 단일 실행 후 종료
- **Reproducibility** — 동일 입력(`ticker`, `rule_type+params`, `start/end`, `data_hash`, `image_tag`)이면 동일 출력
- **GitOps** — `k8s/` 매니페스트가 인프라의 단일 진실 공급원, Argo CD reconcile
- **run_id Tracing** — Web → Job → DB 전 구간 UUID4 기반 추적

---

## Architecture

![Architecture Overview](https://raw.githubusercontent.com/wiki/msp-architect-2026/kim-jongwon/images/10_architecture_overview.png)

> Web(Stateless) → K8s Job(Worker) → MySQL(Source of Truth)로 실행을 분리해,  
> “웹 안정성”과 “백테스트 확장성”을 독립적으로 가져갑니다.

---

## Quick Start (Local)

> **Phase 0 (Local sync mode)** 기준 실행 방법입니다.  
> (Docker Compose / Kubernetes / DB 초기화 등 운영 절차는 Wiki Runbook을 참고하세요)

```bash
# Run from repo root
pip install -r requirements.txt
python app.py
````

Dashboard: [http://localhost:5000](http://localhost:5000)

Tests:

```bash
python -m pytest tests/ -v
```

---

## Documentation (GitHub Wiki)

상세 설계/운영 문서는 GitHub Wiki에서 관리합니다.

* **Wiki Home**: [GitHub Wiki](https://github.com/msp-architect-2026/kim-jongwon/wiki)

### Start Here

* [Design Principles](https://github.com/msp-architect-2026/kim-jongwon/wiki/Design-Principles)
* [Execution Lifecycle](https://github.com/msp-architect-2026/kim-jongwon/wiki/Execution-Lifecycle)
* [Reproducibility (+ Verification Playbook)](https://github.com/msp-architect-2026/kim-jongwon/wiki/Reproducibility)
* [Scope & Non-Goals](https://github.com/msp-architect-2026/kim-jongwon/wiki/Scope-%26-Non-Goals)

### Architecture & Ops

* [Infra Architecture](https://github.com/msp-architect-2026/kim-jongwon/wiki/Infra-Architecture)
* [Runbook / Troubleshooting](https://github.com/msp-architect-2026/kim-jongwon/wiki/Runbook-Troubleshooting)
* [ADR (Design Decisions)](https://github.com/msp-architect-2026/kim-jongwon/wiki/ADR-Design-Decisions)

### Reference

* [API-Endpoints & Schemas](https://github.com/msp-architect-2026/kim-jongwon/wiki/API-Endpoints-%26-Schemas)
* [ERD-Data Model](https://github.com/msp-architect-2026/kim-jongwon/wiki/ERD-Data-Model)
* [Security Model](https://github.com/msp-architect-2026/kim-jongwon/wiki/Security-Model)
* [Testing Strategy](https://github.com/msp-architect-2026/kim-jongwon/wiki/Testing-Strategy)
* [Glossary](https://github.com/msp-architect-2026/kim-jongwon/wiki/Glossary)
* [UI-화면구성](https://github.com/msp-architect-2026/kim-jongwon/wiki/UI-%ED%99%94%EB%A9%B4%EA%B5%AC%EC%84%B1)
