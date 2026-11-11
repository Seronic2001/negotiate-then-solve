#!/usr/bin/env bash
# Training episodes for nts-agent-v7: the v7 families (nts.eval.scenarios.V7_FAMILIES: colleague swaps with
# consent, absences over pinned and part-day classes, two changes in two weeks, whether a colleague is free, the
# examination weeks) with coordinator-v6's tools and the Phase 1 code, on the four training departments, best of
# 3 (the runs not chosen give outcome pairs for DPO), with the policy documents loaded; then Gemini rewordings
# ("--rewrite train") on train-d1 and train-big. A finished report is skipped, so the script resumes.
#   bash scripts/collect_v7.sh      (the stores in parallel; GEMINI_RPM=12 keeps four processes under the limit)
cd "$(dirname "$0")/.." || exit 1
STORES=../negotiate-then-solve-agentic/runs/agentic
FAMILIES="swap_colleague swap_colleague_refused away_pinned away_part away_and_cancel q_colleague_free exam_week"
run() {  # store seed [extra...]
  local store=$1 seed=$2; shift 2
  local stem="runs/eval/collect-v7-${store}-s${seed}"
  [ "${1:-}" = "--rewrite" ] && stem="${stem}-train"
  [ -f "$stem.json" ] && return
  # shellcheck disable=SC2086
  GEMINI_RPM=12 uv run python -m nts eval --model gemini --agent coordinator-v6 --env ../negotiate-then-solve/.env \
    --store "$STORES/${store}.jsonl" --families $FAMILIES --per-family 5 --best-of 3 --seed "$seed" \
    --max-seconds 600 --policies data/policies --telemetry "runs/telemetry-v7/$(basename "$stem")" "$@" --out "$stem.json" > "$stem.log" 2>&1
  echo "$(date +%H:%M) $store s$seed: $(tail -n 1 "$stem.log")"
}
# the four departments at once: one process per store, each under 15 requests a minute per key (4 keys)
run train-d1 701 & run train-d2 702 & run train-d3 703 & run train-big 704 & wait
run train-d1 711 --rewrite train & run train-big 714 --rewrite train & wait
echo "$(date +%H:%M) done"
