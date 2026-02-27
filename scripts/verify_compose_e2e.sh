#!/usr/bin/env bash
set -euo pipefail

RESET_ON_START=1
E2E_MARKER_ID=""
if [[ "${1:-}" == "--no-reset" ]]; then
  RESET_ON_START=0
fi

log() {
  printf '[INFO] %s\n' "$*"
}

pass() {
  printf '[PASS] %s\n' "$*"
}

fail() {
  printf '[FAIL] %s\n' "$*" >&2
  exit 1
}

require_repo_root() {
  [[ -f "docker-compose.yml" ]] || fail "repo root에서 실행해야 합니다. (docker-compose.yml 없음)"
  [[ -f "app.py" ]] || fail "repo root에서 실행해야 합니다. (app.py 없음)"
}

load_env_file() {
  if [[ ! -f ".env" ]]; then
    [[ -f ".env.example" ]] || fail ".env 와 .env.example 이 모두 없습니다."
    cp .env.example .env
    log ".env가 없어 .env.example 기반으로 생성했습니다. (로컬 전용)"
  fi

  # shellcheck disable=SC1091
  set -a && source .env && set +a

  for key in DB_NAME DB_USER DB_PASSWORD MYSQL_ROOT_PASSWORD; do
    [[ -n "${!key:-}" ]] || fail ".env에 ${key} 값이 필요합니다."
  done
}

wait_for_health() {
  local url="http://localhost:5000/health"
  local retries=60
  local sleep_sec=2
  local body_file status_code
  body_file="$(mktemp)"

  for _ in $(seq 1 "$retries"); do
    status_code="$(curl -sS -o "$body_file" -w '%{http_code}' "$url" || true)"
    if [[ "$status_code" == "200" ]]; then
      python - "$body_file" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
assert data.get("status") == "ok", data
PY
      pass "/health 200 OK 확인"
      rm -f "$body_file"
      return 0
    fi
    sleep "$sleep_sec"
  done

  rm -f "$body_file"
  fail "/health 준비 실패 (최대 $((retries * sleep_sec))초 대기)"
}

post_run_backtest() {
  local run_id payload_file response_file status_code
  run_id="$(python - <<'PY'
import uuid
print(uuid.uuid4())
PY
)"

  payload_file="$(mktemp)"
  response_file="$(mktemp)"

  cat >"$payload_file" <<EOF
{
  "run_id": "${run_id}",
  "ticker": "AAPL.csv",
  "strategy": "RSI",
  "params": {
    "period": 14,
    "oversold": 30,
    "overbought": 70
  },
  "start_date": "2020-01-01",
  "end_date": "2020-12-31"
}
EOF

  status_code="$(curl -sS -o "$response_file" -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    -X POST http://localhost:5000/run_backtest \
    --data "@${payload_file}")"

  [[ "$status_code" == "200" ]] || {
    cat "$response_file" >&2
    fail "/run_backtest HTTP ${status_code}"
  }

  python - "$response_file" "$run_id" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
assert data.get("status") == "completed", data
assert data.get("run_id") == sys.argv[2], data
assert isinstance(data.get("metrics"), dict), data
assert "total_return_pct" in data["metrics"], data
print(f"run_id={data['run_id']} total_return_pct={data['metrics']['total_return_pct']}")
PY
  pass "/run_backtest 정상 응답 확인"
  rm -f "$payload_file" "$response_file"

  if docker compose logs --no-color --tail=200 web | grep -q "\[run_id=${run_id}\]"; then
    pass "web 로그에서 run_id 추적 확인 (${run_id})"
  else
    log "주의: web 로그에서 run_id(${run_id})를 찾지 못했습니다. (환경에 따라 로그 tail 범위 이슈 가능)"
  fi
}

mysql_write_and_check() {
  local count
  E2E_MARKER_ID="phase1_e2e_$(date +%s)"

  docker compose exec -T mysql \
    mysql -u"${DB_USER}" "-p${DB_PASSWORD}" "${DB_NAME}" \
    -e "SELECT 1;" >/dev/null
  pass "MySQL 연결 확인 (SELECT 1)"

  docker compose exec -T mysql \
    mysql -u"${DB_USER}" "-p${DB_PASSWORD}" "${DB_NAME}" \
    -e "CREATE TABLE IF NOT EXISTS phase1_e2e_markers (marker_id VARCHAR(64) PRIMARY KEY, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        INSERT INTO phase1_e2e_markers (marker_id) VALUES ('${E2E_MARKER_ID}');" >/dev/null

  count="$(docker compose exec -T mysql \
    mysql -Nse "SELECT COUNT(*) FROM phase1_e2e_markers WHERE marker_id='${E2E_MARKER_ID}';" \
    -u"${DB_USER}" "-p${DB_PASSWORD}" "${DB_NAME}")"

  [[ "${count}" -ge 1 ]] || fail "MySQL marker insert 확인 실패"
  pass "MySQL 쓰기 확인 (marker_id=${E2E_MARKER_ID})"
}

verify_persistence_after_restart() {
  local marker_id="$1"
  local count

  log "docker compose down 실행"
  docker compose down

  log "docker compose up -d 재기동"
  docker compose up -d

  wait_for_health

  count="$(docker compose exec -T mysql \
    mysql -Nse "SELECT COUNT(*) FROM phase1_e2e_markers WHERE marker_id='${marker_id}';" \
    -u"${DB_USER}" "-p${DB_PASSWORD}" "${DB_NAME}")"

  [[ "${count}" -ge 1 ]] || fail "재기동 후 marker 유실 (mysql-data 볼륨 확인 필요)"
  pass "down/up 이후 mysql-data 볼륨 유지 확인 (marker_id=${marker_id})"
}

main() {
  require_repo_root
  load_env_file

  if [[ "${RESET_ON_START}" -eq 1 ]]; then
    log "재현성 확보를 위해 초기 상태 정리: docker compose down -v --remove-orphans"
    docker compose down -v --remove-orphans >/dev/null 2>&1 || true
  fi

  log "docker compose up -d --build 실행"
  docker compose up -d --build

  wait_for_health
  post_run_backtest
  mysql_write_and_check
  verify_persistence_after_restart "${E2E_MARKER_ID}"

  cat <<'EOF'
[DONE] Compose E2E 검증 완료.
- /health: 200 OK
- /run_backtest: completed 응답
- MySQL 연결/쓰기 확인
- docker compose down/up 후 mysql-data 유지 확인

원하면 종료 시 아래 명령 실행:
  docker compose down
EOF
}

main "$@"
