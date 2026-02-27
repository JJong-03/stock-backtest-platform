# Kubernetes 기반 주식 백테스트 플랫폼

<div align="center">
  <img src="https://img.shields.io/badge/Python-151515?style=for-the-badge&logo=python&logoColor=3776AB" alt="Python" />
  <img src="https://img.shields.io/badge/Flask-151515?style=for-the-badge&logo=flask&logoColor=white" alt="Flask" />
  <img src="https://img.shields.io/badge/MySQL-151515?style=for-the-badge&logo=mysql&logoColor=4479A1" alt="MySQL" />
  <img src="https://img.shields.io/badge/Docker-151515?style=for-the-badge&logo=docker&logoColor=2496ED" alt="Docker" />
  <img src="https://img.shields.io/badge/Kubernetes-151515?style=for-the-badge&logo=kubernetes&logoColor=326CE5" alt="Kubernetes" />
  <img src="https://img.shields.io/badge/GitHub_Actions-151515?style=for-the-badge&logo=github-actions&logoColor=2088FF" alt="GitHub Actions" />
  <img src="https://img.shields.io/badge/ArgoCD-151515?style=for-the-badge&logo=argo&logoColor=EF7B4D" alt="Argo CD" />
</div>

> 검증된(수정 금지) Python 백테스트 엔진을 컨테이너로 감싸고, 각 백테스트를 독립적인 Kubernetes Job으로 실행하는 클라우드 네이티브 플랫폼

---

## Core Design

- **Immutable Engine** — 레거시 엔진 로직 변경 금지. 확장은 Adapter/Wrapper 패턴으로만 해결
- **1 Backtest = 1 K8s Job** — 실행 격리, 자원 통제, 재시도/TTL 정리를 클러스터 레벨에서 관리
- **Stateless Web + Ephemeral Worker** — Web은 요청/조회만, Worker는 단일 실행 후 종료
- **Reproducibility** — 동일 입력(ticker, rule, params, date range, image tag)은 반드시 동일 출력
- **GitOps** — `k8s/` 매니페스트가 인프라의 단일 진실 공급원, Argo CD가 reconcile
- **run_id Tracing** — Web → Job → DB 전 구간 UUID4 기반 요청 추적

---

## Architecture

![Architecture Overview](https://raw.githubusercontent.com/wiki/msp-architect-2026/kim-jongwon/images/10_architecture_overview.png)

---

## Quick Start (Local)

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

모든 상세 문서는 GitHub Wiki에서 관리합니다.

| 주제 | Wiki 페이지 |
|---|---|
| Home | [Wiki Home](https://github.com/msp-architect-2026/kim-jongwon/wiki) |
| 설계 원칙 | [Design Principles](https://github.com/msp-architect-2026/kim-jongwon/wiki/Design-Principles) |
| Scope & Non-Goals | [Scope & Non-Goals](https://github.com/msp-architect-2026/kim-jongwon/wiki/Scope-&-Non-Goals) |
| 인프라 아키텍처 | [Infra Architecture](https://github.com/msp-architect-2026/kim-jongwon/wiki/Infra-Architecture) |
| 앱 아키텍처 | [App Architecture](https://github.com/msp-architect-2026/kim-jongwon/wiki/App-Architecture) |
| 실행 라이프사이클 | [Execution Lifecycle](https://github.com/msp-architect-2026/kim-jongwon/wiki/Execution-Lifecycle) |
| API & Schemas | [API-Endpoints & Schemas](https://github.com/msp-architect-2026/kim-jongwon/wiki/API-Endpoints-%26-Schemas) |
| 데이터 모델 / ERD | [ERD-Data Model](https://github.com/msp-architect-2026/kim-jongwon/wiki/ERD-Data-Model) |
| 재현성 | [Reproducibility](https://github.com/msp-architect-2026/kim-jongwon/wiki/Reproducibility) |
| CI/CD & GitOps | [CI_CD_GitOps](https://github.com/msp-architect-2026/kim-jongwon/wiki/CI_CD_GitOps) |
| 보안 모델 | [Security Model](https://github.com/msp-architect-2026/kim-jongwon/wiki/Security-Model) |
| 운영/트러블슈팅 | [Runbook-Troubleshooting](https://github.com/msp-architect-2026/kim-jongwon/wiki/Runbook-Troubleshooting) |
| 테스트 전략 | [Testing Strategy](https://github.com/msp-architect-2026/kim-jongwon/wiki/Testing-Strategy) |
| UI 화면구성 | [UI-화면구성](https://github.com/msp-architect-2026/kim-jongwon/wiki/UI-%ED%99%94%EB%A9%B4%EA%B5%AC%EC%84%B1) |
| ADR / 설계 결정 | [ADR-Design Decisions](https://github.com/msp-architect-2026/kim-jongwon/wiki/ADR-Design-Decisions) |
| 용어집 | [Glossary](https://github.com/msp-architect-2026/kim-jongwon/wiki/Glossary) |
