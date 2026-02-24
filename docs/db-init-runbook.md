# DB Schema Initialization Runbook (Phase 2, K8s)

## 1) 목적 / 범위

이 문서는 **Phase 2 Kubernetes 운영 환경**에서 MySQL 스키마(`backtest_results`)를 **수동으로 초기화**하는 절차를 정의한다.

- 대상 namespace: `stock-backtest`
- 대상 MySQL 서비스: `mysql` (ClusterIP), label `app=mysql`
- 대상 ConfigMap: `web-config`
- 대상 Secret: `web-secret`

> **자동 스키마 생성 금지 (중요):**
> Production(K8s)에서는 `db.create_all()`이 자동 실행되지 않는다.
> 스키마 생성은 이 Runbook의 `kubectl exec` 절차로만 수행한다.

---

## 2) 사전 확인 (자동 생성 금지 검증)

### 코드 정적 확인
```bash
rg -n "db\.create_all\(" app.py
```
- 기대 결과: `db.create_all()`은 `if __name__ == "__main__":` 블록 내부에만 존재.

### 런타임 진입점 확인
```bash
rg -n "gunicorn.*app:app" Dockerfile
```
- 기대 결과: K8s/Gunicorn은 `app.py`를 import해서 실행하므로 `__main__` 블록이 자동 실행되지 않음.

### (선택) 로그 확인
```bash
kubectl logs -n stock-backtest deploy/web --tail=200 | rg -n "create_all" || echo "no create_all log"
```

---

## 3) Web DB 환경변수 규칙 (Phase 2 전환 핵심)

Web 애플리케이션 DB 연결 규칙:

1. `DATABASE_URL` 우선 사용
2. 없으면 fallback 사용:
   - `DB_HOST=mysql`
   - `DB_PORT=3306`
   - `DB_NAME`
   - `DB_USER`
   - `DB_PASSWORD`

확인 예시:
```bash
kubectl get configmap -n stock-backtest web-config -o yaml
kubectl get secret -n stock-backtest web-secret -o yaml
```

---

## 4) 수동 스키마 주입 절차 (`kubectl exec` 필수)

### Step 1. MySQL Pod 이름 확인
```bash
MYSQL_POD=$(kubectl get pods -n stock-backtest -l app=mysql -o jsonpath='{.items[0].metadata.name}')
echo "$MYSQL_POD"
```

### Step 2. DB 이름 확인 (`web-config`의 `DB_NAME`, 없으면 `stock_backtest`)
```bash
DB_NAME=$(kubectl get configmap -n stock-backtest web-config -o jsonpath='{.data.DB_NAME}')
DB_NAME=${DB_NAME:-stock_backtest}
echo "$DB_NAME"
```

### Step 3. DDL 주입 (Pod 내부 `$MYSQL_ROOT_PASSWORD` 사용 — 로컬 노출 없음)
```bash
kubectl exec -n stock-backtest -i "$MYSQL_POD" -- \
  sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" \"$DB_NAME\"" \
  < sql/backtest_results.sql
```

> **보안 원칙**: `MYSQL_ROOT_PASSWORD`는 Pod 내부 환경변수를 직접 참조합니다.
> `kubectl get secret | base64 -d` 방식(방법 B)은 터미널 히스토리에 평문이 남으므로 사용 금지입니다.

### Step 4. 생성 검증
```bash
kubectl exec -n stock-backtest "$MYSQL_POD" -- \
  sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"USE $DB_NAME; SHOW COLUMNS FROM backtest_results;\""
```

---

## 5) 생성 검증

### 테이블 존재 확인
```bash
kubectl exec -n stock-backtest $MYSQL_POD -- sh -lc 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "USE stock_backtest; SHOW TABLES LIKE '\''backtest_results'\'';"'
```

### DDL 확인
```bash
kubectl exec -n stock-backtest $MYSQL_POD -- sh -lc 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "USE stock_backtest; SHOW CREATE TABLE backtest_results\\G"'
```

> `DB_NAME`가 `stock_backtest`와 다르면 위 `USE stock_backtest;` 부분을 실제 `DB_NAME`으로 변경.

---

## 6) 운영 정책 메모

- Production(K8s)에서 `db.create_all()` 자동 실행은 금지.
- 스키마 초기화는 Runbook 기반의 명시적 수동 절차로만 수행.
- Alembic 등 마이그레이션 도구 도입은 **현재 MVP/Phase 2 범위 밖(out of scope)**.
