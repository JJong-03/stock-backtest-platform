#!/usr/bin/env bash
# =============================================================================
# Phase 5 E2E Demo Script
# 고정 시나리오로 전체 파이프라인을 실행하고 Rule 8 관측성을 검증합니다.
#
# Quick Start (권장):
#   # 터미널 1: port-forward 시작
#   kubectl port-forward -n stock-backtest svc/web 8080:80 &
#   # 터미널 2: 데모 실행
#   bash scripts/demo.sh
#
# Ingress 경로 (선택):
#   # ingress-nginx-controller를 통한 접근
#   kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80 &
#   HOST_HEADER=stock-backtest.local bash scripts/demo.sh
#
# 환경변수:
#   BASE_URL       Web 엔드포인트 (기본: http://localhost:8080)
#   HOST_HEADER    Ingress Host 헤더 (기본: 비어 있음, 설정 시 curl -H "Host: ..." 추가)
#   POLL_INTERVAL  상태 폴링 간격 초 (기본: 3)
#   POLL_TIMEOUT   최대 폴링 대기 초 (기본: 120)
#   NAMESPACE      K8s namespace (기본: stock-backtest)
#   DB_USER        MySQL 사용자 (K8s secret에서 자동 읽기 시도, 실패 시 필수)
#   DB_PASSWORD    MySQL 비밀번호 (K8s secret에서 자동 읽기 시도, 실패 시 필수)
#   DB_NAME        MySQL DB 이름 (기본: stock_backtest)
# =============================================================================
set -euo pipefail

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  sed -n '2,/^set -euo/{ /^#/s/^# \{0,1\}//p }' "$0"
  exit 0
fi

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_URL="${BASE_URL:-http://localhost:8080}"
HOST_HEADER="${HOST_HEADER:-}"
POLL_INTERVAL="${POLL_INTERVAL:-3}"
POLL_TIMEOUT="${POLL_TIMEOUT:-120}"
NAMESPACE="${NAMESPACE:-stock-backtest}"
DB_NAME="${DB_NAME:-stock_backtest}"
MAX_CONSEC_FAILS="${MAX_CONSEC_FAILS:-5}"

# DB_USER / DB_PASSWORD: resolved later in resolve_db_credentials()
DB_USER="${DB_USER:-}"
DB_PASSWORD="${DB_PASSWORD:-}"

# Temp files (cleaned up on exit)
RESPONSE_FILE="$(mktemp)"
PAYLOAD_FILE="$(mktemp)"

cleanup() {
  rm -f "$RESPONSE_FILE" "$PAYLOAD_FILE"
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { printf '[INFO] %s\n' "$*"; }
pass() { printf '[PASS] %s\n' "$*"; }
fail() { printf '[FAIL] %s\n' "$*" >&2; exit 1; }

# Require jq or python3 for JSON parsing
if ! command -v jq >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
  fail "JSON 파싱을 위해 jq 또는 python3가 필요합니다."
fi

# JSON field extractor — uses jq if available, falls back to python3.
if command -v jq >/dev/null 2>&1; then
  json_field() {
    # Usage: json_field <file> <jq_expression>
    jq -r "$2" < "$1"
  }
else
  json_field() {
    # Usage: json_field <file> <jq_expression>
    # Supports simple patterns: .key, .key.subkey
    python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
keys = sys.argv[2].lstrip('.').split('.')
v = data
for k in keys:
    if v is None:
        break
    v = v.get(k) if isinstance(v, dict) else None
print('null' if v is None else str(v))
" "$1" "$2"
  }
  log "jq를 찾을 수 없어 python3 fallback을 사용합니다."
fi

# Portable base64 decode (GNU uses -d, BSD/macOS uses -D)
# Probe once at startup to avoid repeated detection
if echo "dGVzdA==" | base64 -d >/dev/null 2>&1; then
  _B64_FLAG="-d"
else
  _B64_FLAG="-D"
fi
b64decode() { base64 "$_B64_FLAG"; }

# Curl wrapper that conditionally adds Host header
do_curl() {
  # Usage: do_curl [curl_args...]
  if [[ -n "$HOST_HEADER" ]]; then
    curl -sS -H "Host: ${HOST_HEADER}" "$@"
  else
    curl -sS "$@"
  fi
}

# Normalize status to uppercase (portable: works on Bash 3.2+/macOS)
normalize_status() {
  echo "$1" | tr '[:lower:]' '[:upper:]'
}

# Validate UUID4 format
validate_run_id() {
  local id="$1"
  if ! echo "$id" | grep -qE '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'; then
    fail "run_id 형식이 올바르지 않습니다: '${id}' (UUID 형식 필요)"
  fi
}

# ---------------------------------------------------------------------------
# DB Credential Resolution
# ---------------------------------------------------------------------------
resolve_db_credentials() {
  # Already provided via env — nothing to do
  if [[ -n "$DB_USER" && -n "$DB_PASSWORD" ]]; then
    log "DB 자격증명: 환경변수에서 제공됨"
    return 0
  fi

  # Try reading from K8s web-secret
  if command -v kubectl >/dev/null 2>&1; then
    log "DB 자격증명: web-secret에서 읽기 시도..."
    local secret_json
    secret_json="$(kubectl get secret web-secret -n "$NAMESPACE" -o json 2>/dev/null || true)"

    if [[ -n "$secret_json" ]]; then
      if command -v jq >/dev/null 2>&1; then
        if [[ -z "$DB_USER" ]]; then
          DB_USER="$(echo "$secret_json" | jq -r '.data.DB_USER // empty' 2>/dev/null | b64decode 2>/dev/null || true)"
        fi
        if [[ -z "$DB_PASSWORD" ]]; then
          DB_PASSWORD="$(echo "$secret_json" | jq -r '.data.DB_PASSWORD // empty' 2>/dev/null | b64decode 2>/dev/null || true)"
        fi
      else
        if [[ -z "$DB_USER" ]]; then
          DB_USER="$(echo "$secret_json" | python3 -c "
import json, sys, base64
d = json.load(sys.stdin).get('data', {})
v = d.get('DB_USER', '')
print(base64.b64decode(v).decode() if v else '')
" 2>/dev/null || true)"
        fi
        if [[ -z "$DB_PASSWORD" ]]; then
          DB_PASSWORD="$(echo "$secret_json" | python3 -c "
import json, sys, base64
d = json.load(sys.stdin).get('data', {})
v = d.get('DB_PASSWORD', '')
print(base64.b64decode(v).decode() if v else '')
" 2>/dev/null || true)"
        fi
      fi

      if [[ -n "$DB_USER" && -n "$DB_PASSWORD" ]]; then
        log "DB 자격증명: web-secret에서 성공적으로 읽음"
        return 0
      fi
    fi
  fi

  # Neither env nor secret — fail with clear message
  fail "DB 자격증명을 확인할 수 없습니다. 다음 중 하나를 수행하세요:
  1) DB_USER, DB_PASSWORD 환경변수를 설정
  2) kubectl이 stock-backtest namespace의 web-secret에 접근 가능하도록 설정"
}

# Discover MySQL pod dynamically (StatefulSet-compatible, prefer Running pod)
resolve_mysql_pod() {
  # Try Running pod first
  MYSQL_POD="$(kubectl get pods -n "$NAMESPACE" -l app=mysql \
    --field-selector=status.phase=Running \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  # Fallback: any pod with app=mysql label
  if [[ -z "$MYSQL_POD" ]]; then
    MYSQL_POD="$(kubectl get pods -n "$NAMESPACE" -l app=mysql \
      -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  fi
  if [[ -z "$MYSQL_POD" ]]; then
    log "주의: MySQL Pod를 찾을 수 없습니다 (label: app=mysql). 메트릭 조회를 건너뜁니다."
    return 1
  fi
  log "MySQL Pod: ${MYSQL_POD}"
  return 0
}

# ---------------------------------------------------------------------------
# Step 1: Prerequisites
# ---------------------------------------------------------------------------
log "=== Phase 5 E2E Demo 시작 ==="
log "--- Step 1: Prerequisites ---"
log "BASE_URL=${BASE_URL}"
if [[ -n "$HOST_HEADER" ]]; then
  log "HOST_HEADER=${HOST_HEADER}"
fi

command -v curl >/dev/null 2>&1 || fail "curl이 필요합니다."
HAS_KUBECTL=true
command -v kubectl >/dev/null 2>&1 || { HAS_KUBECTL=false; log "주의: kubectl이 없습니다. 로그 검증/메트릭 조회 단계를 건너뜁니다."; }
pass "Prerequisites 확인 완료"

# ---------------------------------------------------------------------------
# Step 2: Health Check
# ---------------------------------------------------------------------------
log "--- Step 2: Health Check ---"
HTTP_CODE="$(do_curl -o "$RESPONSE_FILE" -w '%{http_code}' \
  "${BASE_URL}/health" || true)"

if [[ -z "$HTTP_CODE" || "$HTTP_CODE" != "200" ]]; then
  log "/health 응답 실패 (HTTP ${HTTP_CODE:-없음})"
  log ""
  log "BASE_URL(${BASE_URL})에 연결할 수 없습니다. 아래를 확인하세요:"
  log "  1) port-forward가 실행 중인지 확인:"
  log "     kubectl port-forward -n ${NAMESPACE} svc/web 8080:80 &"
  log "  2) Ingress 사용 시 HOST_HEADER 설정:"
  log "     HOST_HEADER=stock-backtest.local bash scripts/demo.sh"
  log "  3) Web Pod 상태 확인:"
  log "     kubectl get pods -n ${NAMESPACE} -l app=web"
  fail "서버에 연결할 수 없습니다."
fi
pass "/health 200 OK"

# ---------------------------------------------------------------------------
# Step 3: Submit Backtest (fixed deterministic scenario)
# ---------------------------------------------------------------------------
log "--- Step 3: 백테스트 제출 ---"

cat > "$PAYLOAD_FILE" <<'EOF'
{
  "ticker": "AAPL.csv",
  "rule_type": "RSI",
  "params": {
    "period": 14,
    "oversold": 30,
    "overbought": 70
  },
  "start_date": "2020-01-01",
  "end_date": "2020-12-31",
  "initial_capital": 100000,
  "fee_rate": 0.001,
  "position_size": 10000,
  "size_type": "value",
  "direction": "longonly",
  "timeframe": "1d"
}
EOF

HTTP_CODE="$(do_curl -o "$RESPONSE_FILE" -w '%{http_code}' \
  -H 'Content-Type: application/json' \
  -X POST "${BASE_URL}/run_backtest" \
  --data "@${PAYLOAD_FILE}" || true)"

if [[ -z "$HTTP_CODE" || "$HTTP_CODE" != "202" ]]; then
  log "HTTP ${HTTP_CODE:-없음} 응답:"
  cat "$RESPONSE_FILE" >&2
  fail "/run_backtest 제출 실패 (HTTP ${HTTP_CODE:-없음}, 기대값: 202)"
fi

RUN_ID="$(json_field "$RESPONSE_FILE" '.run_id')"
if [[ -z "$RUN_ID" || "$RUN_ID" == "null" ]]; then
  cat "$RESPONSE_FILE" >&2
  fail "응답에서 run_id를 추출할 수 없습니다."
fi
validate_run_id "$RUN_ID"

pass "백테스트 제출 성공 (run_id=${RUN_ID})"
RUN_ID_SHORT="$(echo "$RUN_ID" | cut -c1-8)"

# ---------------------------------------------------------------------------
# Step 4: Poll Status
# ---------------------------------------------------------------------------
log "--- Step 4: 상태 폴링 (간격=${POLL_INTERVAL}s, 타임아웃=${POLL_TIMEOUT}s) ---"

ELAPSED=0
LAST_STATUS=""
STATUS=""
CONSEC_FAILS=0

while [[ "$ELAPSED" -lt "$POLL_TIMEOUT" ]]; do
  HTTP_CODE="$(do_curl -o "$RESPONSE_FILE" -w '%{http_code}' \
    "${BASE_URL}/status/${RUN_ID}" || true)"

  if [[ -z "$HTTP_CODE" || "$HTTP_CODE" != "200" ]]; then
    CONSEC_FAILS=$((CONSEC_FAILS + 1))
    if [[ "$CONSEC_FAILS" -ge "$MAX_CONSEC_FAILS" ]]; then
      fail "상태 조회 연속 ${CONSEC_FAILS}회 실패. 서버 상태를 확인하세요. (마지막 HTTP: ${HTTP_CODE:-없음})"
    fi
    log "상태 조회 HTTP ${HTTP_CODE:-없음} (재시도 ${CONSEC_FAILS}/${MAX_CONSEC_FAILS}...)"
    sleep "$POLL_INTERVAL"
    ELAPSED=$((ELAPSED + POLL_INTERVAL))
    continue
  fi
  CONSEC_FAILS=0

  RAW_STATUS="$(json_field "$RESPONSE_FILE" '.status')"
  STATUS="$(normalize_status "$RAW_STATUS")"

  # Print status transition
  if [[ "$STATUS" != "$LAST_STATUS" ]]; then
    log "상태 전이: ${LAST_STATUS:-'(초기)'} → ${STATUS} (${ELAPSED}s)"
    LAST_STATUS="$STATUS"
  fi

  # Terminal states
  if [[ "$STATUS" == "SUCCEEDED" || "$STATUS" == "FAILED" ]]; then
    break
  fi

  sleep "$POLL_INTERVAL"
  ELAPSED=$((ELAPSED + POLL_INTERVAL))
done

if [[ "$STATUS" != "SUCCEEDED" && "$STATUS" != "FAILED" ]]; then
  fail "폴링 타임아웃 (${POLL_TIMEOUT}s). 마지막 상태: ${STATUS}"
fi

# ---------------------------------------------------------------------------
# Step 5: Handle Result
# ---------------------------------------------------------------------------
if [[ "$STATUS" == "FAILED" ]]; then
  ERROR_MSG="$(json_field "$RESPONSE_FILE" '.error_message')"
  log "--- 결과: FAILED ---"
  log "error_message: ${ERROR_MSG}"
  # Still print log commands before exiting
else
  pass "백테스트 완료 (SUCCEEDED)"

  # Query MySQL for metrics summary
  log "--- Step 5a: 결과 요약 (MySQL 조회) ---"

  if [[ "$HAS_KUBECTL" == "true" ]]; then
    resolve_db_credentials

    if resolve_mysql_pod; then
      METRICS_RAW="$(kubectl exec -n "$NAMESPACE" "$MYSQL_POD" -- \
        sh -c 'MYSQL_PWD="$1" mysql -u"$2" "$3" -Nse "SELECT metrics_json FROM backtest_results WHERE run_id='"'"'$4'"'"'"' \
        _ "$DB_PASSWORD" "$DB_USER" "$DB_NAME" "$RUN_ID" 2>/dev/null || true)"

      if [[ -n "$METRICS_RAW" && "$METRICS_RAW" != "NULL" ]]; then
        if command -v jq >/dev/null 2>&1; then
          printf '  %-22s %s\n' "Status:" "SUCCEEDED"
          printf '  %-22s %s\n' "num_trades:" "$(echo "$METRICS_RAW" | jq -r '.num_trades // "N/A"')"
          printf '  %-22s %s\n' "total_return_pct:" "$(echo "$METRICS_RAW" | jq -r '.total_return_pct // "N/A"')"
          printf '  %-22s %s\n' "sharpe_ratio:" "$(echo "$METRICS_RAW" | jq -r '.sharpe_ratio // "N/A"')"
          printf '  %-22s %s\n' "max_drawdown_pct:" "$(echo "$METRICS_RAW" | jq -r '.max_drawdown_pct // "N/A"')"
        else
          python3 -c "
import json, sys
try:
    m = json.loads(sys.argv[1])
    print('  %-22s %s' % ('Status:', 'SUCCEEDED'))
    for key in ['num_trades', 'total_return_pct', 'sharpe_ratio', 'max_drawdown_pct']:
        val = m.get(key, 'N/A')
        if isinstance(val, float):
            val = f'{val:.4f}'
        print('  %-22s %s' % (key + ':', val))
except Exception as e:
    print(f'  메트릭 파싱 실패: {e}', file=sys.stderr)
" "$METRICS_RAW"
        fi
        pass "메트릭 조회 완료"
      else
        log "주의: metrics_json 조회 실패 또는 비어 있음 (MySQL 접근 확인 필요)"
      fi
    fi
  else
    log "kubectl 없음 — MySQL 메트릭 조회를 건너뜁니다."
  fi
fi

# ---------------------------------------------------------------------------
# Step 6: Rule 8 Log Verification Commands
# ---------------------------------------------------------------------------
log "--- Step 6: Rule 8 로그 추적 검증 명령 ---"
cat <<EOF

  아래 명령으로 run_id 기반 전 구간 추적을 확인하세요:

  # Web 로그에서 run_id 검색
  kubectl logs -n ${NAMESPACE} -l app=web --tail=200 | grep '${RUN_ID}'

  # Worker Job 로그 확인
  kubectl logs -n ${NAMESPACE} -l run_id=${RUN_ID} --tail=200

  # Worker Pod 직접 조회 (Job 이름 기반)
  kubectl logs -n ${NAMESPACE} job/worker-${RUN_ID_SHORT} --tail=200

  # MySQL에서 전체 레코드 확인 (DB_USER/DB_PASSWORD를 실제 값으로 교체하세요)
  MYSQL_POD=\$(kubectl get pods -n ${NAMESPACE} -l app=mysql --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')
  kubectl exec -n ${NAMESPACE} \$MYSQL_POD -- \\
    sh -c 'MYSQL_PWD="\$1" mysql -u"\$2" ${DB_NAME} -e "SELECT run_id, status, started_at, completed_at FROM backtest_results WHERE run_id='"'"'${RUN_ID}'"'"'"' \\
    _ "\$DB_PASSWORD" "\$DB_USER"

EOF

# ---------------------------------------------------------------------------
# Final Status
# ---------------------------------------------------------------------------
if [[ "$STATUS" == "FAILED" ]]; then
  fail "백테스트 실패 (run_id=${RUN_ID})"
fi

log "=== Phase 5 E2E Demo 완료 (run_id=${RUN_ID}) ==="
