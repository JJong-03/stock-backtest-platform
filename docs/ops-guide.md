# 🛠️ Ops Guide (배포/운영/롤백/트러블슈팅)

이 문서는 **Stock Backtesting Platform**의 운영 관점 가이드입니다.  

- **README:** 프로젝트 요약/대표 이미지/빠른 시작
- **docs/architecture.md:** 아키텍처 상세(구성요소/흐름/계약)
- **docs/ops-guide.md:** 운영 절차(배포/롤백/장애대응)

---

## 0) 운영 원칙 (필독 요약)

- **Engine 수정 금지**: `backtest/engine.py` 및 핵심 로직은 변경하지 않습니다. (Rule 1)
- **Web은 Stateless**: Web Pod는 로컬 파일 write 금지(차트는 Base64 인라인). (Rule 4)
- **MySQL은 단일 진실 공급원**: 결과/상태는 MySQL이 SoT입니다.
- **RBAC 최소 권한**: namespace-scoped Role/RoleBinding, `jobs.batch`에 대해서만 권한 부여(ClusterRole 금지).
- **시크릿 커밋 금지**: `k8s/secret.yaml` 실값 커밋 금지. 템플릿만 커밋. (Rule 7)
- **불변 이미지 태그**: `:<git-sha-short>` 같은 immutable tag 사용, `latest` 금지. (Rule 10)
- **관측성**: 전 구간 `run_id(UUID4)` 로깅, stdout/stderr 로깅. (Rule 8)

---

## 1) Prerequisites

### 로컬 (Phase 0)
- Python 3.11+
- pip

### 컨테이너/로컬 패리티 (Phase 1)
- Docker / Docker Compose v2

### Kubernetes (Phase 2+)
- kubectl
- 로컬 클러스터(선택): kind 또는 minikube
- (Phase 4) Argo CD 접근 수단: `argocd` CLI 또는 UI

---

## 2) 환경변수/설정 (Configuration)

> **Rule 7:** 모든 설정은 환경변수로 주입합니다. 하드코딩 금지.

### 로컬 개발 (Phase 0~1)
- `.env.example`만 커밋
- 실제 `.env`는 `.gitignore` 대상

**예시 (`.env`):**
```bash
FLASK_ENV=development
DB_HOST=localhost
DB_PORT=3306
DB_NAME=stock_backtest
DB_USER=backtest
DB_PASSWORD=changeme
LOG_LEVEL=INFO
JOB_LAUNCHER_MODE=LOCAL   # Phase 3부터 의미 있음 (LOCAL|K8S)

```

### Kubernetes (Phase 2+)

* **비밀이 아닌 값:** ConfigMap
* **비밀(패스워드 등):** Secret
* 레포에는 `k8s/secret-template.yaml`만 존재해야 함

---

## 3) 로컬 실행 (Phase 0)

> **Rule 3:** 모든 명령은 반드시 프로젝트 루트에서 실행합니다.

```bash
pip install -r requirements.txt
python app.py
```

**헬스체크:**

```bash
curl -sS http://localhost:5000/health
```

**테스트:**

```bash
python -m pytest tests/ -v
```

---

## 4) Docker Compose 실행 (Phase 1)

Phase 1 완료 후 적용되는 runbook입니다.

### 4.1 빌드/기동

```bash
docker compose up --build
```

### 4.2 헬스체크

```bash
curl -sS http://localhost:5000/health
```

### 4.3 종료 (볼륨 유지)

```bash
docker compose down
```

> **Acceptance 체크:** down 후 up 해도 MySQL 볼륨이 유지되어 데이터가 보존되는지 확인합니다.

---

## 5) Kubernetes 배포 (Phase 2)

아래는 `k8s/` 매니페스트 기반 배포 절차입니다.

실제 시크릿은 템플릿을 복사해 로컬에서 생성하거나, CI/CD 또는 Sealed Secrets로 주입합니다.

### 5.1 네임스페이스 생성

```bash
kubectl apply -f k8s/namespace.yaml
kubectl get ns | grep stock-backtest
export NS=stock-backtest  # 편의상 변수 설정
```

### 5.2 ConfigMap 적용

```bash
kubectl apply -n $NS -f k8s/configmap.yaml
kubectl get configmap -n $NS
```

### 5.3 Secret 생성 (실값 커밋 금지)

**방법 A) 템플릿 복사 후 로컬에서 적용**

```bash
# (로컬) k8s/secret-template.yaml → k8s/secret.yaml 로 복사 후 실값 입력
# ⚠️ k8s/secret.yaml은 .gitignore 대상이어야 함
kubectl apply -n $NS -f k8s/secret.yaml

```

**방법 B) kubectl로 직접 생성 (권장: 데모/학습용)**

```bash
kubectl create secret generic stock-backtest-secret -n $NS \
  --from-literal=DB_USER=backtest \
  --from-literal=DB_PASSWORD='<your-password>'
```

### 5.4 MySQL StatefulSet/PVC 배포

```bash
kubectl apply -n $NS -f k8s/mysql-statefulset.yaml
kubectl get pods -n $NS -w
kubectl get pvc -n $NS
```

**MySQL 준비 확인:**

```bash
kubectl logs -n $NS -l app=mysql --tail=200
```

### 5.5 DB 스키마 초기화 (운영자 1회 실행)

> **Rule 9:** Production에서 `db.create_all()` 자동 실행 금지.
> 스키마는 운영자가 명시적으로 1회 수행합니다.

**방법 A) kubectl exec로 mysql 접속 후 DDL 실행**

```bash
# MySQL Pod 이름 확인
kubectl get pod -n $NS -l app=mysql

# mysql client로 접속 (예시)
kubectl exec -it -n $NS <mysql-pod-name> -- mysql -u root -p
# -> DB 생성/권한/테이블 생성 DDL 실행
```

### 5.6 RBAC 적용 (Web이 Job을 만들 수 있도록)

```bash
kubectl apply -n $NS -f k8s/rbac.yaml
kubectl get sa,role,rolebinding -n $NS
```

### 5.7 Web Deployment/Service 배포

```bash
kubectl apply -n $NS -f k8s/web-deployment.yaml
kubectl get pods -n $NS -l app=web -w
kubectl get svc -n $NS
```

### 5.8 Ingress 배포

```bash
kubectl apply -n $NS -f k8s/ingress.yaml
kubectl get ingress -n $NS
```

### 5.9 배포 검증

```bash
# Web Pod Ready 확인
kubectl get pods -n $NS -l app=web
# /health 확인
curl -sS http://<ingress-host-or-ip>/health
```

---

## 6) Web → K8s Job 오케스트레이션 검증 (Phase 3)

Phase 3 완료 후 적용되는 runbook입니다.

### 6.1 정상 흐름 (성공)

1. 백테스트 제출 (`POST /run_backtest`) → Web이 `run_id` 발급 + DB에 `PENDING` 기록
2. Web이 **K8s Job 생성**
3. Worker Pod 시작 → DB에 `RUNNING` 기록
4. 엔진 실행 완료 → 결과 persist → `SUCCEEDED` 기록
5. Web `/status/<run_id>`로 조회 가능
6. Web이 성공 Job을 **즉시 삭제** (정리 정책)

### 6.2 실패 흐름 (실패)

1. Worker가 `FAILED` + `error_message` 기록
2. Job은 **24시간 보관**(디버깅) 후 TTL로 정리

### 6.3 확인 커맨드

```bash
# Job 목록
kubectl get jobs -n $NS

# Worker 로그 (예시)
kubectl logs -n $NS job/<job-name> --tail=200

# Job 삭제 (성공 정리 확인용)
kubectl delete job -n $NS <job-name>
```

---

## 7) 관측성 (Observability) 운영 방법 (Rule 8)

### 7.1 run_id 기반 트레이싱

* 모든 요청/실행은 `run_id` (UUID4)를 가진다
* Web / Worker / DB 로그 모두 `run_id` 포함
* 로그는 `stdout`/`stderr`로만 출력 (파일 로깅 금지)

### 7.2 run_id로 로그 찾기

```bash
# Web 로그
kubectl logs -n $NS -l app=web --tail=500 | grep "<run_id>"

# Worker 로그 (잡/파드 이름 기준)
kubectl logs -n $NS job/<job-name> --tail=500 | grep "<run_id>"
```

---

## 8) GitOps 운영 (Phase 4)

`k8s/` 디렉터리는 GitOps의 SSOT이며, Argo CD가 이를 reconcile 합니다.

### 8.1 배포 흐름 (권장)

1. **개발:** `feature/*` → PR → `dev` → `main`
2. **CI (GitHub Actions):**
* `pytest`
* 이미지 빌드/푸시: `ghcr.io/<owner>/stock-backtest:<git-sha-short>`
* `k8s/web-deployment.yaml`의 image tag 갱신 (commit 또는 PR)


3. **CD (Argo CD):**
* `main` 브랜치의 `k8s/` 변경 감지 → auto-sync → 롤링 업데이트



### 8.2 Argo CD 상태 확인 (예시)

```bash
argocd app list
argocd app get stock-backtest
```

---

## 9) 롤백 절차 (Rollback)

### 9.1 이전 이미지 태그로 되돌리기

**방법 A:** `k8s/web-deployment.yaml`의 image tag를 이전 SHA로 revert → commit/push → Argo CD auto-sync

**방법 B (Argo CD CLI):** 이전 revision으로 sync

```bash
argocd app sync stock-backtest --revision <prev-commit>
```

### 9.2 기능 확인

1. 헬스 확인: `curl -sS http://<ingress>/health`
2. 백테스트 1건 제출 → `/status/<run_id>`가 `SUCCEEDED` 반환 확인

---

## 10) 장애 대응 (Incident Triage) 체크리스트

장애 상황에서는 **“외부 → Web → Job → DB”** 순으로 좁혀갑니다.

### 10.1 Ingress/Service

```bash
kubectl get ingress,svc -n $NS
kubectl describe ingress -n $NS <ingress-name>
```

### 10.2 Web Pods

```bash
kubectl get pods -n $NS -l app=web
kubectl describe pod -n $NS <web-pod>
kubectl logs -n $NS -l app=web --tail=200
```

* Restart count 급증 / OOMKilled 여부 확인
* readiness/liveness probe 실패 여부 확인

### 10.3 Job 상태

```bash
kubectl get jobs -n $NS
kubectl describe job -n $NS <job-name>
```

* `backoffLimit` 초과, 이미지 풀 실패, 권한 오류(RBAC) 확인

### 10.4 DB 연결성 (MySQL)

```bash
# MySQL Pod 상태
kubectl get pods -n $NS -l app=mysql
kubectl logs -n $NS -l app=mysql --tail=200

# Web Pod에서 DB 연결성 점검 (예시)
kubectl exec -n $NS -it <web-pod> -- python -c "import os; print(os.getenv('DB_HOST'))"
```

### 10.5 run_id 기반 end-to-end 추적

```bash
kubectl logs -n $NS -l app=web --tail=500 | grep "<run_id>"
kubectl logs -n $NS job/<job-name> --tail=500 | grep "<run_id>"
```

---

## 11) SLO (Service Level Objectives)

* **Availability:** `/health`가 시간당 **99%** 이상 200 OK
* **Backtest Completion:** 제출된 Job 중 **95%** 이상이 5분 내 `SUCCEEDED` 도달

---

## 12) 운영 팁 / 자주 쓰는 커맨드 모음

```bash
# 리소스 전체 보기
kubectl get all -n $NS

# 특정 라벨만 보기
kubectl get pods -n $NS -l app=web
kubectl get pods -n $NS -l app=mysql

# 롤링 업데이트 상태
kubectl rollout status deployment/web -n $NS
kubectl rollout history deployment/web -n $NS

# Ingress 없이 임시 포트포워드로 확인
kubectl port-forward -n $NS svc/web 5000:5000
curl -sS http://localhost:5000/health
```

---

## 13) 보안/컴플라이언스 체크 (최소)

* [ ] `k8s/secret.yaml` 실값 커밋이 없는가? (`secret-template.yaml`만 존재하는가?)
* [ ] 이미지 태그에 `latest`를 사용하지 않는가?
* [ ] Web이 ClusterRole을 쓰지 않는가? (namespace-scoped Role/RoleBinding인가?)
* [ ] 로그에 민감정보(DB 패스워드 등)가 출력되지 않는가?
* [ ] 모든 로그에 `run_id`가 포함되는가?

---

## 14) Related Docs

* **설계/규칙/계약 (필독):** `../CLAUDE.md`
* **아키텍처 상세:** `architecture.md`
* **UI 스크린샷 갤러리:** `screenshots.md`
* **프로젝트 소개:** `../README.md`

