#!/usr/bin/env bash
# Mirror V4 — Question Bank Runner (DeepSeek-safe)
# - Works whether /ask returns only {harmony,intent} in meta (SHOW_SOURCES=0)
# - Defensive jq for missing fields: provenance, llm.used
# Usage:
#   BASE_URL=http://127.0.0.1:8080 USER_ID=qa \
#   BANK_FILE=tests/questions_v4.txt SHUFFLE=1 LIMIT=25 CONCURRENCY=4 \
#   DEPTH=deep TRAIN_JSONL=./mv4_train.jsonl TRAIN_MIN_HARMONY=0.7 \
#   ./test_mirror_v4_bank.sh

set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8080}"
USER_ID="${USER_ID:-qa}"
BANK_FILE="${BANK_FILE:-}"
SHUFFLE="${SHUFFLE:-0}"          # 1 to shuffle
LIMIT="${LIMIT:-0}"              # >0 to cap number of questions
CONCURRENCY="${CONCURRENCY:-4}"  # xargs -P
DEPTH="${DEPTH:-}"               # "", or "deep"
TRAIN_JSONL="${TRAIN_JSONL:-./mv4_train.jsonl}"
TRAIN_MIN_HARMONY="${TRAIN_MIN_HARMONY:-0.7}"
JQ="${JQ:-$(command -v jq || true)}"
CURL=${CURL:-"curl -sS --max-time 60 --retry 2 --retry-delay 1"}

# --- require jq --------------------------------------------------------------
if [ -z "$JQ" ]; then
  echo "❌ jq not found. Please: sudo apt-get install -y jq" >&2
  exit 1
fi

# --- load bank ---------------------------------------------------------------
load_bank() {
  if [ -n "${BANK_FILE}" ] && [ -f "${BANK_FILE}" ]; then
    awk 'NF' "${BANK_FILE}"
    return
  fi
  # Built-in defaults (V4-friendly)
  cat <<'EOF'
Who are the Guardians?
Summarize the Guardians Oath.
What is Lucidity?
What is Resonance?
What is the Bushido of Patience?
List the core virtues found in the TOBY scrolls.
Explain the role of the Ledger.
How does Learning self-refine after a run?
What are Scrolls and why do they matter?
What is a Rune in temporal context?
Describe the Conversation Weaver at a high level.
How does Symbol Resonance influence synthesis?
What changed between Epoch 1 and Epoch 3?
How does the Privacy Filter protect user data?
When should deep retrieval be used?
Explain “harmony score” and the threshold.
Give an example of weaving evidence across two scrolls.
What is Lucidity’s novice vs. sage output?
What is the function of Rites?
How do identities merge for the same traveler?
EOF
}

# temp working files
WORKDIR="$(mktemp -d -t mv4bank.XXXXXX)"
QFILE="$WORKDIR/questions.txt"
OUTDIR="$WORKDIR/out"
mkdir -p "$OUTDIR"

# populate questions
load_bank > "$QFILE"

# optionally shuffle / limit
if [ "${SHUFFLE}" = "1" ]; then
  if command -v shuf >/dev/null 2>&1; then
    shuf "$QFILE" -o "$QFILE"
  else
    echo "⚠️  shuf not found; running in given order"
  fi
fi
if [ "${LIMIT}" != "0" ]; then
  head -n "${LIMIT}" "$QFILE" > "$QFILE.tmp" && mv "$QFILE.tmp" "$QFILE"
fi

# preflight
echo "### Mirror V4 Bank Runner"
echo "BASE_URL=$BASE_URL  USER_ID=$USER_ID  DEPTH=${DEPTH:-normal}  CONCURRENCY=$CONCURRENCY"
echo "TRAIN_JSONL=$TRAIN_JSONL  TRAIN_MIN_HARMONY=$TRAIN_MIN_HARMONY"
echo "Questions: $(wc -l < "$QFILE")"
echo

# zero/ensure train file
: > "$TRAIN_JSONL"

# function: call one question
call_one() {
  local idx="$1"
  local q="$2"

  # Build payload via jq (safe escaping)
  local payload
  if [ "${DEPTH:-}" = "deep" ]; then
    payload=$(jq -n --arg user "$USER_ID" --arg q "$q" \
      --arg depth "deep" \
      --argjson prefer_series '["TOBY_F","TOBY_C"]' \
      --argjson keywords '["oath","virtue","history","epoch"]' \
      '{user:$user, question:$q, hint:{depth:$depth, prefer_series:$prefer_series, keywords:$keywords}}')
  else
    payload=$(jq -n --arg user "$USER_ID" --arg q "$q" '{user:$user, question:$q}')
  fi

  # Hit /ask
  local resp_file="$OUTDIR/r${idx}.json"
  if ! ${CURL} -X POST "$BASE_URL/ask" -H 'Content-Type: application/json' -d "$payload" > "$resp_file"; then
    echo "[$idx] ❌ request failed"
    return 1
  fi

  # Parse fields (defensive: meta may omit provenance/llm when SHOW_SOURCES=0)
  local answer intent harmony llm_used prov_count alen
  answer="$("$JQ" -r '.answer // ""' "$resp_file")"
  intent="$("$JQ" -r '.meta.intent // ""' "$resp_file")"
  harmony="$("$JQ" -r 'try (.meta.harmony|tonumber) catch 0' "$resp_file")"
  # llm_used: prefer explicit flag; else infer "unknown"
  llm_used="$("$JQ" -r 'if (.meta.llm.used? // empty) then .meta.llm.used else "unknown" end' "$resp_file")"
  # provenance count if present, else 0
  prov_count="$("$JQ" -r 'try ((.meta.provenance // []) | length) catch 0' "$resp_file")"
  alen="$(printf "%s" "$answer" | wc -c | tr -d ' ')"

  # Pretty line
  printf "[%02d] %s\n" "$idx" "$q"
  printf "     → intent=%s  harmony=%.3f  llm=%s  sources=%s  len=%s\n" \
    "${intent:-?}" "${harmony:-0}" "${llm_used}" "${prov_count}" "${alen}"

  # Gate for training
  awk -v h="${harmony:-0}" -v thr="${TRAIN_MIN_HARMONY}" 'BEGIN{exit !(h>=thr)}' || return 0

  # Append JSONL: simple chat pair
  jq -n --arg u "$q" --arg a "$answer" \
    '{messages:[{"role":"user","content":$u},{"role":"assistant","content":$a}]}' \
    >> "$TRAIN_JSONL"
}

export -f call_one
export USER_ID BASE_URL DEPTH TRAIN_MIN_HARMONY JQ CURL OUTDIR

# run in parallel using TAB as a safe separator
i=0
while IFS= read -r line; do
  i=$((i+1))
  printf "%s\t%s\n" "$i" "$line"
done < "$QFILE" | \
xargs -I{} -P "${CONCURRENCY}" bash -c 'idx="${1%	*}"; q="${1#*	}"; call_one "$idx" "$q"' _ {}

# summary
TOTAL=$(wc -l < "$QFILE")
KEPT=$(wc -l < "$TRAIN_JSONL")
echo
echo "### Done"
echo "Questions run: $TOTAL"
echo "Training examples kept (harmony >= $TRAIN_MIN_HARMONY): $KEPT"
echo "Train JSONL: $TRAIN_JSONL"
