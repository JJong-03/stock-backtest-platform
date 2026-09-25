# 로컬 kind 클러스터 부하 측정 (2026-09-25)

요청 한 건만 확인했던 E2E 검증(`docs/e2e-demo-verification.md`) 뒤에, 동시 요청을 넣었을 때
처리량과 지연이 어떻게 변하는지 로컬 재현 환경에서 처음으로 측정한 기록이다.
운영 환경 수치가 아니며, 아래 조건에서만 유효하다.

## 환경

| 항목 | 값 |
|---|---|
| 클러스터 | kind v0.27.0, 노드 1개(control-plane 겸용), Kubernetes v1.32.2 |
| 호스트 | WSL2, Docker 29.1.3, CPU 12개, 메모리 약 7.7GiB |
| 이미지 | 이 저장소 `3bcac46`을 로컬 빌드(`stock-backtest:measure-3bcac46`) |
| 매니페스트 | `k8s/`의 namespace, configmap, rbac, mysql-statefulset, web-deployment, web-service (이미지만 로컬 태그로 교체, Secret은 측정용 임시값) |
| 스키마 | 규칙 9대로 `docs/sql/backtest_results.sql`을 한 번 적용 |
| 요청 | `AAPL.csv`, RSI(기본 파라미터), 2020-01-01 ~ 2024-12-31 |
| 클라이언트 | 클러스터 안 Pod에서 `scripts/measure_local_load.py` 실행(`http://web`), 결과 조회 주기 2초(`templates/index.html`의 `pollForResult`와 같음) |

지표:
- **접수 시간**: `POST /run_backtest`가 202를 돌려줄 때까지(PENDING 저장과 Job 생성 포함)
- **시작 지연**: 요청부터 Worker가 RUNNING으로 바꾼 시각(`started_at`)까지
- **완료 시간(E2E)**: 요청부터 클라이언트가 SUCCEEDED를 받을 때까지(2초 조회 주기 포함)
- **처리량**: 동시 요청 묶음의 성공 건수 ÷ 첫 요청부터 마지막 완료까지 걸린 시간

## 결과

### A. 저장소 기본 설정 (gunicorn 워커 1개, CPU 한도 500m, 메모리 한도 512Mi)

| 동시 요청 | 성공 | 시작 지연 중간값 | 완료 시간 중간값 / 최대 | 처리량 | 웹 재시작 |
|---|---|---|---|---|---|
| 1건씩 5번 | 5/5 | 2.2초 | 5.6초 / 6.7초 | - | 0 |
| 10 | 10/10 | 4.6초 | 15.4초 / 21.5초 | 분당 27.9건 | 0 |
| 20 | 20/20 | 10.1초 | 28.3초 / 43.3초 | 분당 27.7건 | 0 |

- Worker 계산 자체는 1초 안팎이다(`started_at`과 `completed_at`이 초 단위로 0~1초 차이).
- 동시 요청을 10건에서 20건으로 늘려도 처리량이 분당 약 28건에서 늘지 않았다.
- 웹 로그를 보면 SUCCEEDED 결과를 돌려주는 `/status` 한 건이 1.6~1.9초 걸린다. 결과를 조회할 때마다
  차트 5개를 다시 그리기 때문이고(Result Persistence Boundaries의 derive-on-demand 계약), 워커 1개가
  이 요청들을 차례로 처리하면서 뒤쪽 요청의 완료 시간이 길어졌다.

### 관찰: 조회를 자주 하면 웹이 재시작됨

측정 스크립트 첫 버전은 0.25초마다 결과를 조회했다. 이때 차트를 그리는 `/status`가 워커 1개를 붙잡아
`/health` 헬스 체크(제한 3초)가 응답하지 못했고, 쿠버네티스가 liveness probe 실패로 웹 컨테이너를 재시작했다.
진행 중이던 연결은 끊겼지만 Job과 MySQL 결과는 모두 남아 있었다. 화면과 같은 2초 주기로 바꾼 A 측정에서는 재시작이 없었다.

### B. 워커만 3개로 늘림 (CPU 500m, 메모리 512Mi 그대로)

| 동시 요청 | 성공 | 시작 지연 중간값 | 완료 시간 중간값 / 최대 | 처리량 | 웹 재시작 |
|---|---|---|---|---|---|
| 1건씩 5번 | 5/5 | 2.2초 | 5.7초 / 7.7초 | - | 0 |
| 10 | 10/10 | 4.3초 | 69.5초 / 79.4초 | 분당 7.6건 | 누적 6 |
| 20 | 20/20 | 7.9초 | 259.4초 / 489.8초 | 분당 2.5건 | (위와 합산) |

- 웹 컨테이너가 **OOMKilled(exit 137)**로 6번 재시작했다. pandas와 matplotlib를 올린 워커 3개가 메모리 한도 512Mi를 넘었다.
- 재시작 동안 결과 조회가 실패했다(조회 실패 10건 묶음 66번, 20건 묶음 468번). Job은 모두 성공했고 결과도 MySQL에 남았다.
- 워커 수만 늘리는 것은 이 자원 한도에서는 답이 아니었다.

### C. 워커 2개 + CPU 한도 1000m, 메모리 한도 1Gi

| 동시 요청 | 성공 | 시작 지연 중간값 | 완료 시간 중간값 / 최대 | 처리량 | 웹 재시작 |
|---|---|---|---|---|---|
| 1건씩 5번 | 5/5 | 2.5초 | 4.8초 / 6.0초 | - | 0 |
| 10 | 10/10 | 4.9초 | 11.5초 / 14.8초 | 분당 40.5건 | 0 |
| 20 | 20/20 | 9.1초 | 19.8초 / 27.4초 | 분당 43.7건 | 0 |

- 웹 컨테이너 최대 메모리(cgroup `memory.peak`): 약 397MiB.

### D. 워커 2개, CPU 500m, 메모리 512Mi (C에서 자원 한도만 원래대로)

| 동시 요청 | 성공 | 시작 지연 중간값 | 완료 시간 중간값 / 최대 | 처리량 | 웹 재시작 |
|---|---|---|---|---|---|
| 1건씩 5번 | 5/5 | 2.3초 | 5.5초 / 6.5초 | - | 0 |
| 10 | 10/10 | 4.3초 | 16.5초 / 23.1초 | 분당 26.0건 | 0 |
| 20 | 20/20 | 8.2초 | 26.7초 / 39.2초 | 분당 30.6건 | 0 |

- 웹 컨테이너 최대 메모리: 약 385MiB. 워커 2개는 512Mi 안에 들어간다.

## 정리

동시 요청 20건 기준 비교:

| 구성 | 처리량 | 20건 모두 끝날 때까지 | 웹 재시작 |
|---|---|---|---|
| A 워커 1, CPU 500m, 512Mi (저장소 기본) | 분당 27.7건 | 43.3초 | 0 |
| B 워커 3, CPU 500m, 512Mi | 분당 2.5건 | 489.8초 | 6 (OOMKilled) |
| D 워커 2, CPU 500m, 512Mi | 분당 30.6건 | 39.2초 | 0 |
| C 워커 2, CPU 1000m, 1Gi | 분당 43.7건 | 27.4초 | 0 |

1. 병목은 계산 Job이 아니라 웹의 결과 조회였다. SUCCEEDED 결과를 조회할 때마다 차트를 다시 그려 한 건에 1.6~1.9초가 걸린다.
2. 워커를 늘리는 것만으로는 효과가 작거나(D, +11%) 오히려 나빠졌다(B, 메모리 한도 초과로 재시작).
3. 효과가 컸던 것은 CPU 한도였다. 워커 2개에 CPU 한도 1코어를 주자 처리량이 분당 27.7건에서 43.7건(+58%)으로, 20건 완료 시간이 43.3초에서 27.4초로 줄었다.
4. 측정한 구성 C(`--workers 2`, CPU 한도 1000m, 메모리 한도 1Gi)를 `k8s/web-deployment.yaml`에 반영했다. 근본적으로는 조회할 때마다 차트를 다시 그리지 않도록 하는 방법(예: 웹 Pod 메모리 안 캐시)을 따로 검토해야 한다. 차트를 DB에 저장하는 것은 Result Persistence Boundaries 계약(derive-on-demand)과 맞지 않는다.
5. 한계: 로컬 kind 1노드에서 한 번씩 잰 값이며 반복 측정은 하지 않았다. 운영 클러스터의 네트워크, 노드 수, 이미지 풀 시간은 반영되지 않는다. Worker 계산 시간은 DB 타임스탬프가 초 단위라 1초 안팎으로만 알 수 있다.

## 다시 재는 방법

```bash
kind create cluster --name sbt-measure
docker build -t stock-backtest:measure-$(git rev-parse --short HEAD) .
kind load docker-image stock-backtest:measure-<sha> --name sbt-measure
kubectl apply -f k8s/namespace.yaml -f k8s/configmap.yaml -f k8s/rbac.yaml
kubectl -n stock-backtest create secret generic web-secret ...   # secret-template.yaml의 키, 임시값
kubectl apply -f k8s/mysql-statefulset.yaml -f k8s/web-service.yaml
sed 's#ghcr.io/jjong-03/stock-backtest:.*#stock-backtest:measure-<sha>#' k8s/web-deployment.yaml | kubectl apply -f -
kubectl -n stock-backtest exec -i mysql-0 -- mysql -u<user> -p<pw> stock_backtest < docs/sql/backtest_results.sql
kubectl -n stock-backtest create configmap measure-script --from-file=scripts/measure_local_load.py
# 클러스터 안 Pod에서 실행
python scripts/measure_local_load.py --base-url http://web --sequential 5 --concurrent 10 --concurrent 20
```

원시 결과(JSON)는 `docs/measurements/2026-09-25-local-kind-load.json`에 있다.
