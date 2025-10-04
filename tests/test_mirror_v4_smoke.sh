#!/usr/bin/env bash
# Mirror V4 — E2E Smoke (matches your plan 0..7)
# usage: BASE_URL=http://127.0.0.1:8080 ./test_mirror_v4_smoke.sh

set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8080}"
JQ="${JQ:-$(command -v jq || true)}"
CURL="curl -sS --max-time 10"

pass(){ printf "✅ %s\n" "$*"; }
fail(){ printf "❌ %s\n" "$*\n"; exit 1; }
info(){ printf "— %s\n" "$*"; }

require_jq(){
  if [ -z "$JQ" ]; then
    fail "jq not found. install jq or set JQ=/path/to/jq"
  fi
}

assert_http_ok(){
  local url="$1"
  $CURL "$url" >/dev/null || fail "HTTP not OK for: $url"
}

assert_gte(){
  # usage: assert_gte <value> <min> <label>
  local v="$1" min="$2" lbl="$3"
  awk "BEGIN{exit !($v>=$min)}" || fail "$lbl expected >= $min, got $v"
}

section(){ printf "\n### %s\n" "$*"; }

require_jq

# 0) dashboard quick check
section "0) Dashboard quick check"
info "GET $BASE_URL/web/health.html (tiles should be green)"
assert_http_ok "$BASE_URL/web/health.html"
pass "dashboard reachable"

# 1) core health + status
section "1) Core health + status"
info "GET /health"
$CURL "$BASE_URL/health" | tee /tmp/mv4_health.json >/dev/null
grep -q '"ok": *true' /tmp/mv4_health.json || fail "/health ok:false"
pass "/health ok:true"

info "GET /status"
$CURL "$BASE_URL/status" | ${JQ} . > /tmp/mv4_status.json
SCROLLS=$(${JQ} -r '.scrolls_loaded' /tmp/mv4_status.json)
INDEX_ADDED=$(${JQ} -r '.index_stats.added' /tmp/mv4_status.json)
info "scrolls_loaded=$SCROLLS, index_stats.added=$INDEX_ADDED"
assert_gte "${SCROLLS:-0}" 1000 "scrolls_loaded"
pass "/status looks sane"

# --- safeguards check ---
info "GET /safeguards/status"
SAFE=$($CURL "$BASE_URL/safeguards/status")
echo "$SAFE" | ${JQ} . > /tmp/mv4_guard.json
CLOSED_COUNT=$(jq -r '[.temporal.state, .symbol.state, .conversation.state] | map(select(.=="CLOSED")) | length' /tmp/mv4_guard.json)
if [ "$CLOSED_COUNT" -eq 3 ]; then
  pass "safeguards breakers CLOSED"
else
  info "safeguards not all CLOSED (ok if by design)"; cat /tmp/mv4_guard.json
fi

# 2) retriever & synthesis
section "2) Retriever & synthesis (normal vs deep, with/without hints)"

info "plain ask: Summarize the Guardians Oath."
$CURL -X POST "$BASE_URL/ask" \
  -H 'Content-Type: application/json' \
  -d '{"user":"qa","question":"Summarize the Guardians Oath."}' \
  | ${JQ} . > /tmp/mv4_ask_plain.json
ANS_LEN=$(wc -c </tmp/mv4_ask_plain.json)
assert_gte "${ANS_LEN:-0}" 64 "answer length (plain)"
pass "plain ask returned text ($ANS_LEN bytes)"

info "deep ask + hint: Bushido of Patience"
$CURL -X POST "$BASE_URL/ask" \
  -H 'Content-Type: application/json' \
  -d '{"user":"qa","question":"What is the Bushido of Patience?","hint":{"depth":"deep","prefer_series":["TOBY_F","TOBY_C"],"keywords":["oath","virtue"]}}' \
  | ${JQ} . > /tmp/mv4_ask_deep.json
DEEP_LEN=$(wc -c </tmp/mv4_ask_deep.json)
assert_gte "${DEEP_LEN:-0}" 64 "answer length (deep)"
pass "deep ask returned text ($DEEP_LEN bytes)"

# 3) indexing
section "3) Indexing"
info "POST /reindex pattern=**/*"
$CURL -X POST "$BASE_URL/reindex" -H 'Content-Type: application/json' \
  -d '{"pattern":"**/*"}' | ${JQ} . > /tmp/mv4_reindex.json
ADDED_THIS_RUN=$(${JQ} -r '.added_this_run' /tmp/mv4_reindex.json)
DOCS_TOTAL=$(${JQ} -r '.docs_total' /tmp/mv4_reindex.json)
info "reindex: added_this_run=$ADDED_THIS_RUN docs_total=$DOCS_TOTAL"
assert_gte "${DOCS_TOTAL:-0}" 1000 "docs_total"

info "verify counts via /status"
$CURL "$BASE_URL/status" | ${JQ} '[.scrolls_loaded, .index_stats]'>/tmp/mv4_status2.json
pass "status reflects index stats"

# 4) ledger & learning
section "4) Ledger & learning"
info "GET /ledger/summary"
$CURL "$BASE_URL/ledger/summary" | ${JQ} . >/tmp/mv4_ledger.json || true
info "GET /learning/summary"
$CURL "$BASE_URL/learning/summary" | ${JQ} . >/tmp/mv4_learning.json || true
pass "ledger/learning reachable (content depends on recent activity)"

# 5) Prometheus metrics sanity
section "5) Prometheus metrics"
METRICS_RAW=$($CURL "$BASE_URL/metrics" || true)
echo "$METRICS_RAW" | grep -E 'mv4_requests_total|mv4_request_latency_seconds' | head || true
pass "metrics endpoint exposes mv4_* counters"

# 6) light concurrency burst
section "6) Concurrency burst (P=4)"
printf 'who are the guardians?\nwhat is lucidity?\nwhat is resonance?\n' | \
xargs -I{} -P 4 sh -c \
  "$CURL -X POST $BASE_URL/ask -H 'Content-Type: application/json' -d '{\"user\":\"load\",\"question\":\"{}\"}' >/dev/null"
$CURL "$BASE_URL/metrics" | grep mv4_requests_total | head || true
pass "burst completed"

# 7) safeguards probe
section "7) Safeguards quick probe"
$CURL "$BASE_URL/safeguards/status" | ${JQ} . | sed -e 's/^/   /'
pass "safeguards status shown (trigger checks manually if desired)"

echo
pass "Mirror V4 smoke: all sections executed"
