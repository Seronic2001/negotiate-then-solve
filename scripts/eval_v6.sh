#!/usr/bin/env bash
# v6 adapters (dpo, read-050, read-100) with coordinator-v6: the compositional suite (eval.jsonl, held out), then the
# twelve v6 families on eval and eval-big (s0). Waits for the server before each run; a run with connection errors
# (model_error) is set aside as *.unreachable<n> and tried again (twice at most). A finished report is skipped.
cd "$(dirname "$0")/.." || exit 1
PY="../negotiate-then-solve/.venv/Scripts/python.exe"
URL=http://10.1.25.191:8080
V6="window_move or_windows ranked_move day_cap days_cap free_gap after_lecture courses_apart even_weeks
    except_week two_windows_off move_apart"
up() { until curl -s -m 8 -o /dev/null "$URL/health"; do sleep 60; done; }
run() {  # adapter store tag [extra...]
  local a=$1 store=$2 tag=$3; shift 3
  local stem="runs/eval/v6_${a}-${tag}" try
  [ -f "$stem.json" ] && return
  for try in 1 2 3; do
    up
    PYTHONPATH=src "$PY" -m nts eval --model llama --adapter "$a" --agent coordinator-v6 --env ../negotiate-then-solve/.env \
      --store "runs/agentic/${store}.jsonl" --seed 0 --max-seconds 900 "$@" --out "$stem.json" > "$stem.log" 2>&1
    echo "$(date +%H:%M) $a $tag (try $try): $(tail -n 1 "$stem.log")"
    grep -q "model_error" "$stem.log" || return
    mv "$stem.log" "$stem.unreachable$try.log"; [ -f "$stem.json" ] && mv "$stem.json" "$stem.unreachable$try.json"
  done
}
for a in nts-agent-v6-dpo nts-agent-v6-read-100 nts-agent-v6-read-050; do
  run $a eval compositional --suite compositional
  # shellcheck disable=SC2086
  run $a eval fam-s0 --families $V6
  # shellcheck disable=SC2086
  run $a eval-big fam-big-s0 --families $V6
done
echo "$(date +%H:%M) done"
