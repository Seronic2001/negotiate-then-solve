"""Before and after a phase's changes: every message in ``<phase>/requests.jsonl`` sent to the chat
(``POST /api/chat``, as the side chat sends it) with the model on the GPU server, and what came back scored
against the row's ``want``:

- ``lookups``: the tools of the lookups answered, in order (a list of choices for a part where either will
  do; ``null``: not scored; ``[]``: no lookup answered);
- ``request``: whether a "send this as a request?" card came back;
- ``rule``: whether a rule answer came back.

    uv run python before_after/run.py before_after/phase_1 --out before   # before the changes
    uv run python before_after/run.py before_after/phase_1 --out after    # after them

The chat is emptied before each message, so no message is read as a follow-up of the one before. Nothing is
sent as a request: a card is only offered.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def tools(reply: dict) -> list[str]:
    call = reply["call"]
    return [p["tool"] for p in call["args"]["parts"]] if call["tool"] == "multi" else [call["tool"]]


def scored(want: dict, got: dict) -> dict[str, bool]:
    marks = {"request": got["request"] == want["request"], "rule": got["rule"] == want["rule"]}
    if want["lookups"] is not None:
        wanted = [w if isinstance(w, list) else [w] for w in want["lookups"]]
        marks["lookups"] = len(wanted) == len(got["lookups"]) and all(g in w for g, w in zip(got["lookups"], wanted))
    return marks


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase", type=Path, help="the phase's folder, with requests.jsonl")
    ap.add_argument("--out", required=True, choices=["before", "after"])
    ap.add_argument("--url", default="http://10.1.25.191:8080/v1", help="llama-server with the adapters")
    a = ap.parse_args()

    os.environ.update({"NTS_PARSER": "local", "NTS_LOCAL_URL": a.url, "NTS_PERSIST": "0",
                       "NTS_ADAPTERS": str(ROOT / "adapters-lora.toml")})
    from fastapi.testclient import TestClient

    from web.app import World, create_web_app

    world = World(parser_mode="local", seed_history=False, deadline=60)
    print("lookup adapter:", world.lookup_adapter, "| model reachable:", world.model_link.usable())
    c = TestClient(create_web_app(world))
    rows = [json.loads(x) for x in (a.phase / "requests.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    passed = 0
    with (a.phase / f"{a.out}.jsonl").open("w", encoding="utf-8") as out:
        for row in rows:
            me = {"X-User": row["as"]}
            c.delete("/api/chat", headers=me)
            r = c.post("/api/chat", json={"text": row["text"]}, headers=me)
            r.raise_for_status()
            replies = [m for m in r.json() if m["role"] == "assistant"]
            looked = next((m for m in replies if m["kind"] == "lookup"), None)
            card = next((m for m in replies if m["kind"] == "confirm"), None)
            rule = next((m for m in replies if m["kind"] == "rule"), None)
            got = {"lookups": tools(looked) if looked else [], "request": card is not None, "rule": rule is not None,
                   "reader": (looked or card or {}).get("reader"),
                   "answer": looked["answer"] if looked else None,
                   "card": card["text"] if card else None,
                   "rule_answer": rule["answer"] if rule else None,
                   "replies": [m["kind"] for m in replies]}
            marks = scored(row["want"], got)
            ok = all(marks.values())
            passed += ok
            print(f"{'PASS' if ok else 'FAIL'} {row['id']} {row['kind']:20} got {got['replies']} {got['lookups']}"
                  + ("" if ok else f"  (wrong: {', '.join(k for k, v in marks.items() if not v)})"))
            out.write(json.dumps({**row, "got": got, "marks": marks, "pass": ok}, ensure_ascii=False) + "\n")
    print(f"\n{passed}/{len(rows)} pass; every reply in {a.phase / (a.out + '.jsonl')}")


if __name__ == "__main__":
    main()
