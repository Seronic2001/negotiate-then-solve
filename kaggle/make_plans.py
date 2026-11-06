"""Phase 0 plans: which adapter runs which evaluation, on which account (docs/improvement-plan.md, Phase 0).

    python kaggle/make_plans.py      # writes kaggle/plans/*.json

Each account can only attach its own notebooks' outputs (a 403 across accounts), so the split follows who trained
what: shubhadeepmandal has the intents adapters (v8, v11, v12, each epoch) and the agent v6 SFT run (with a copy of
its DPO adapter); seronic2001 has the agent v1-v4 runs and the DPO runs.

    a-intents  every intents suite for v8, v11, v12 at each epoch, and v12's last epoch twice more (the noise floor)
    a-agent    agent v6 epoch 1 and epoch 2: all 42 families, 5 each, on both eval departments
    b-agent    agent v6 DPO on all 42, twice (the second run is the noise floor), and v4 (epoch 2) and v3 (DPO) on
               their 19 families: the older versions, for the regression matrix
(shubhadeepmandal keeps room for the training runs, whose data only it has.)
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "plans"
OLD19 = ["q_free", "q_classes", "away", "preference", "move", "room_closed", "not_allowed", "impossible", "ambiguous",
         "clarify", "negotiate", "negotiate_refused", "rules_question", "weekend", "clarify_negotiate", "hedged_yes",
         "no_reply", "two_changes", "away_days"]
V5 = ["three_changes", "swap", "week_range", "fallback", "cancel_one", "make_up", "hour_limit", "club_booking",
      "counter_offer", "refused_alternative", "injection"]
V6 = ["window_move", "or_windows", "ranked_move", "day_cap", "days_cap", "free_gap", "after_lecture", "courses_apart",
      "even_weeks", "except_week", "two_windows_off", "move_apart"]
ALL42 = OLD19 + V5 + V6
STORES = ["eval", "eval-big"]


def suites(adapter: str, tag: str, repeat: int = 0) -> dict:
    return {"id": f"suites/{tag}" + (f"/r{repeat}" if repeat else ""), "kind": "suites", "adapter": adapter,
            "workers": 4}


def agent(adapter: str, cfg: str, tag: str, families: list[str], stores=STORES, per_family: int = 5, seed: int = 0,
          repeat: int = 0) -> list[dict]:
    """One job per family and department: each takes one server slot, so eight run at once."""
    return [{"id": f"agent/{tag}/{store}/{fam}" + (f"/r{repeat}" if repeat else ""), "kind": "agent",
             "adapter": adapter, "agent": cfg, "store": store, "families": [fam], "per_family": per_family,
             "seed": seed} for store in stores for fam in families]


def write(name: str, account: str, jobs: list[dict], sources: list[str]) -> None:
    OUT.mkdir(exist_ok=True)
    plan = {"name": name, "account": account, "kernel_sources": sources, "budget_hours": 10.5,
            "server": {"np": 4, "ctx": 32768}, "jobs": jobs}
    (OUT / f"{name}.json").write_text(json.dumps(plan, indent=1))
    n = {k: sum(j["kind"] == k for j in jobs) for k in ("suites", "agent")}
    print(f"{name}: {n}, adapters {sorted({j['adapter'] for j in jobs})}")


def main() -> None:
    a_int = []
    for v in ("v12", "v11", "v8"):
        for e, pct in ((1, "033"), (2, "067"), (3, "100")):
            if v != "v12" and e == 1:
                continue
            a_int.append(suites(f"nts-intents-{v}-read-{pct}", f"{v}-e{e}"))
    a_int += [suites("nts-intents-v12-read-100", "v12-e3", r) for r in (1, 2)]
    write("a-intents", "shubhadeepmandal", a_int,
          ["shubhadeepmandal/nts-eval-tools", "shubhadeepmandal/nts-intents-v12", "shubhadeepmandal/nts-intents-v11",
           "shubhadeepmandal/nts-intents-v8"])

    a_ag = []
    for adapter, tag in (("nts-agent-v6-read-100", "v6-e2"), ("nts-agent-v6-read-050", "v6-e1")):
        a_ag += agent(adapter, "coordinator-v6", tag, ALL42)
    write("a-agent", "shubhadeepmandal", a_ag, ["shubhadeepmandal/nts-eval-tools", "shubhadeepmandal/nts-agent-v6"])

    # two kernels, so both of the account's GPU sessions (Kaggle allows 2 at a time) work
    write("b-agent1", "seronic2001", agent("nts-agent-v6-dpo", "coordinator-v6", "v6-dpo", ALL42),
          ["seronic2001/nts-eval-tools", "seronic2001/nts-agent-v6-dpo"])
    b2 = agent("nts-agent-v6-dpo", "coordinator-v6", "v6-dpo", ALL42, repeat=1)
    b2 += agent("nts-agent-v4-read-100", "coordinator-v4", "v4-e2", OLD19)
    b2 += agent("nts-agent-v3-dpo", "coordinator-v3", "v3-dpo", OLD19)
    write("b-agent2", "seronic2001", b2,
          ["seronic2001/nts-eval-tools", "seronic2001/nts-agent-v6-dpo", "seronic2001/nts-agent-v4-train-dp",
           "seronic2001/nts-agent-v3-dpo"])

    # the training variants (kaggle/train/make_variants.py), scored on every suite once they are trained
    variants = ["cos3", "cos1"]  # trimmed 2026-11-06: cos2 and cos2-lr1e4 dropped
    write("a-train-eval", "shubhadeepmandal", [suites(f"nts-intents-v12-{v}", f"v12-{v}") for v in variants],
          ["shubhadeepmandal/nts-eval-tools"] + [f"shubhadeepmandal/nts-intents-v12-{v}" for v in variants])


if __name__ == "__main__":
    main()
