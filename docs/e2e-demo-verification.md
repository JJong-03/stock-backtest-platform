# E2E Demo Verification (Phase 5)

## 1. Purpose

이 문서는 백테스팅 플랫폼의 전체 파이프라인을 end-to-end로 실행한 결과를 기록하고,
Rule 8(Observability) 준수 여부를 실제 `run_id`를 통해 검증합니다.

검증 대상 흐름:

```
User Request → Web (PENDING insert) → K8s Job (Worker) → MySQL Persistence → run_id Tracing
```

---

## 2. Environment

- **Kubernetes namespace:** `stock-backtest`
- **Demo script:** `scripts/demo.sh`

### Quick Start (권장)

```bash
# 터미널 1: port-forward
kubectl port-forward -n stock-backtest svc/web 8080:80 &

# 터미널 2: 데모 실행
bash scripts/demo.sh
```

### Ingress 경로 (선택)

```bash
# ingress-nginx-controller를 통한 접근
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80 &

# HOST_HEADER로 가상 호스트 지정
HOST_HEADER=stock-backtest.local bash scripts/demo.sh
```

---

## 3. Example Successful Run

| 항목 | 값 |
|---|---|
| **run_id** | `92362869-d710-4e44-a734-9ebcee111b27` |
| **status** | `SUCCEEDED` |
| **ticker** | `AAPL.csv` |
| **rule_type** | `RSI` |
| **params** | `{"period": 14, "oversold": 30, "overbought": 70}` |

### Metrics

| Metric | Value |
|---|---|
| num_trades | 4 |
| total_return_pct | -0.5574 |
| sharpe_ratio | 0.1096 |
| max_drawdown_pct | 25.8800 |

DB 자격증명은 K8s Secret(`web-secret`)에서 자동으로 읽어와 사용되었으며, 스크립트 출력에 노출되지 않았습니다.

---

## 4. State Transition Verification

Run이 올바른 상태 머신을 따랐는지 검증합니다.

```
PENDING → RUNNING → SUCCEEDED
```

### Timestamp Evidence

| Timestamp | Value (UTC) | Meaning |
|---|---|---|
| `created_at` | `2026-03-04 05:18:23` | Web이 `PENDING` 상태로 DB에 insert |
| `started_at` | `2026-03-04 05:18:24` | Worker가 `RUNNING`으로 전이 |
| `completed_at` | `2026-03-04 05:18:24` | Worker가 실행 완료 후 `SUCCEEDED`로 전이, 결과 persist |

- `created_at` → Web이 `run_id`를 발급하고 `PENDING` row를 insert한 시점
- `started_at` → Worker Pod가 시작되어 `RUNNING`으로 상태를 전이한 시점
- `completed_at` + `status=SUCCEEDED` → Worker가 엔진 실행을 완료하고 결과를 MySQL에 persist한 시점

상태 전이는 단방향(forward-only)이며, `PENDING → RUNNING → SUCCEEDED` 순서가 timestamp로 확인됩니다.

---

## 5. Observability Verification (Rule 8)

Rule 8은 모든 로그에 `[run_id=...]`를 포함하고, stdout/stderr로만 출력할 것을 요구합니다.
아래 명령으로 동일한 `run_id`가 Web, Worker, DB 전 구간에서 추적 가능한지 확인합니다.

### Web 로그 확인

```bash
kubectl logs -n stock-backtest -l app=web --tail=200 | grep '92362869-d710-4e44-a734-9ebcee111b27'
```

### Worker Job 로그 확인

```bash
kubectl logs -n stock-backtest -l run_id=92362869-d710-4e44-a734-9ebcee111b27 --tail=200
```

### Worker Pod 직접 조회 (Job 이름 기반)

```bash
kubectl logs -n stock-backtest job/worker-92362869 --tail=200
```

### Database 레코드 확인

```bash
MYSQL_POD=$(kubectl get pods -n stock-backtest -l app=mysql \
  --field-selector=status.phase=Running \
  -o jsonpath='{.items[0].metadata.name}')

kubectl exec -n stock-backtest $MYSQL_POD -- \
  mysql -u<DB_USER> -p<DB_PASSWORD> stock_backtest \
  -e "SELECT run_id, status, started_at, completed_at FROM backtest_results WHERE run_id='92362869-d710-4e44-a734-9ebcee111b27';"
```

> `<DB_USER>`와 `<DB_PASSWORD>`는 실제 환경의 자격증명으로 대체하세요.
> `web-secret`에서 확인: `kubectl get secret web-secret -n stock-backtest -o jsonpath='{.data.DB_USER}' | base64 -d`

동일한 `run_id`(`92362869-d710-4e44-a734-9ebcee111b27`)가 Web 로그, Worker 로그, MySQL 레코드에서
모두 확인되면 **Rule 8 end-to-end 관측성이 검증**된 것입니다.

---

## 6. Result

| 검증 항목 | 결과 |
|---|---|
| K8s Job으로 백테스트 실행 | SUCCEEDED |
| MySQL에 결과 persist | metrics_json, equity_curve_json, trades_json 확인 |
| 상태 머신 준수 | PENDING → RUNNING → SUCCEEDED (timestamp 순서 정합) |
| run_id 전 구간 추적 | Web log, Worker log, DB record에서 동일 run_id 확인 |

**Rule 8 Observability 요구사항이 end-to-end로 충족됨을 확인합니다.**
