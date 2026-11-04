"""Which Meta Model API calls a run made, as a table a person can read (CALLS.md).

Runs since commit 096bee3 record every call in api_calls.jsonl (see meta_api.CallLog), and the
table is made from that. Older runs only have events.jsonl, which logs what each step did and
what the models returned, not each request. For those the calls are derived from the code path
each logged event comes from (agent.py):

| event                  | calls behind it                                                   |
|------------------------|-------------------------------------------------------------------|
| decide                 | Muse Spark (the decision) + SAM 3.1 "character" (people), at once |
| scan, no target        | SAM 3.1 "character"                                               |
| scan / check of object | SAM 3.1 on the phrase and its last word, + Muse Spark picking     |
|                        | among the numbered matches if there were any                      |
| approach, follow, aim  | SAM 3.1 on the target phrase (shorter phrases tried first fail    |
|                        | silently, so this is a lower bound)                               |
| holding                | Muse Spark (is the hand holding it?) + SAM 3.1 on the held object |
| decide with voice      | Muse Voice Transcribe finished those utterances before this step  |

A derived call has no request id, duration or token count, and calls that failed or found
nothing are missing, so derived counts are lower bounds. The event's time is when the step's
calls had all returned.
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

SPARK, SAM, ASR = "Muse Spark 1.3", "SAM 3.1", "Muse Voice Transcribe"
NAMES = {"chat/completions": SPARK, "responses": SAM, "asr/realtime": ASR}


def _events(run: Path) -> list[dict]:
    path = run / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _short(text, n: int = 90) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _phrases(target: str) -> list[str]:
    words = str(target or "").split()
    return list(dict.fromkeys([str(target), words[-1]])) if words else []


def derive(events: list[dict]) -> list[dict]:
    """The calls each logged event implies, in log order (see the module docstring)."""
    out: list[dict] = []

    def call(e: dict, model: str, purpose: str, returned: str, **extra) -> None:
        out.append({"t": e["t"], "step": e.get("step"), "frame": e.get("frame"), "model": model,
                    "purpose": purpose, "returned": returned, "derived": True, **extra})

    for e in events:
        phase = e.get("phase")
        if phase == "decide":
            for text in e.get("voice") or []:
                call(e, ASR, "transcribe what VRChat played", repr(text))
            parts = [" ".join(str(x) for x in (e.get("intent"), e.get("target")) if x)]
            if e.get("reply"):
                parts.append(f"replies {e['reply']!r}")
            if e.get("say") and e.get("say") != e.get("reply"):
                parts.append(f"says {e['say']!r}")
            if e.get("observation"):
                parts.append(f"sees: {_short(e['observation'], 70)}")
            call(e, SPARK, "decide the next step from the frame", "; ".join(parts))
            call(e, SAM, 'find people: "character"', f"{len(e.get('people') or [])} person box(es)")
        elif phase == "scan" and not e.get("target"):
            call(e, SAM, f'find people: "character" (turned {e.get("turned")} deg)',
                 f"{len(e.get('people') or [])} person box(es)")
        elif phase in ("scan", "check"):
            n = len(e.get("candidates") or [])
            for p in _phrases(e.get("target")):  # sent at once; the log keeps only their union
                call(e, SAM, f"find {p!r}" + (f" (turned {e.get('turned')} deg)" if phase == "scan" else ""),
                     f"{n} distinct match(es) from both phrases" if n else "no match")
            if e.get("candidates"):
                pick = e.get("pick")
                call(e, SPARK, f"pick the real {e.get('target')!r} among {len(e['candidates'])} numbered matches",
                     (f"box {pick}" if pick else "none of them") + (f": {_short(e.get('check'), 60)}"
                                                                     if e.get("check") else ""))
        elif phase in ("approach", "follow", "aim"):
            found = e.get("box") is not None
            conf = f" conf {e['conf']:.2f}" if found and e.get("conf") is not None else ""
            call(e, SAM, f"ground {e.get('target')!r} ({phase})", (f"box{conf}" if found else "no match"))
        elif phase == "holding":
            call(e, SPARK, "is the hand holding something? (HUD 'Drop' prompt)",
                 f"{'yes' if e.get('took') else 'no'}: {_short(e.get('check'), 60)}")
            call(e, SAM, f"locate the held {e.get('target')!r}", "box" if e.get("box") else "no match")
    return out


def recorded(run: Path) -> list[dict]:
    """api_calls.jsonl as table rows, sorted by when each call finished."""
    path = run / "api_calls.jsonl"
    if not path.exists():
        return []
    rows = []
    for rec in (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()):
        model = NAMES.get(rec.get("api"), rec.get("model"))
        if rec.get("event") == "session":
            rows.append({"t": rec["t"], "model": model, "purpose": "open realtime session",
                         "returned": f"session {rec.get('session_id')}"})
            continue
        if rec.get("event") == "transcript":
            rows.append({"t": rec["t"], "model": model, "purpose": "utterance finished",
                         "returned": repr(rec.get("transcript"))})
            continue
        ids = rec.get("response_id") or next((v for k, v in rec.items() if "request" in k and "id" in k), "")
        usage = (rec.get("usage") or {}).get("total_tokens")
        rows.append({"t": rec["t"] + (rec.get("seconds") or 0), "model": model,
                     "purpose": f"{rec.get('phrase')!r}" if rec.get("phrase") else "frame + prompt",
                     "returned": " ".join(str(x) for x in (
                         rec.get("status", rec.get("error")), f"{rec.get('seconds')} s",
                         f"{usage} tokens" if usage else "", ids) if x)})
    return sorted(rows, key=lambda r: r["t"])


def table(run: Path, title: str | None = None) -> str:
    """CALLS.md for one run."""
    meta = json.loads((run / "run.json").read_text(encoding="utf-8")) if (run / "run.json").exists() else {}
    rows = recorded(run)
    derived = not rows
    if derived:
        rows = derive(_events(run))
    stamp = lambda t: datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%H:%M:%S")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["model"]] = counts.get(r["model"], 0) + 1
    lines = [f"# {title or run.name}: Meta Model API calls", ""]
    if meta.get("goal"):
        lines += [f"Goal: {meta['goal']}", ""]
    if rows:
        day = datetime.datetime.fromtimestamp(rows[0]["t"], datetime.timezone.utc).strftime("%Y-%m-%d")
        lines += [f"{day}, {stamp(rows[0]['t'])} to {stamp(rows[-1]['t'])} UTC. "
                  + ", ".join(f"{n} {m}" for m, n in counts.items()) + ".", ""]
    if derived:
        lines += ["Derived from `events.jsonl`: this run predates `api_calls.jsonl`, so each row is a call the "
                  "logged event implies (see `src/muse_body/calls.py`). There are no request ids or token "
                  "counts, failed calls are missing, and the counts are lower bounds. Times are when the "
                  "step's calls had returned. `frame` is the image in this folder that was sent.", ""]
    else:
        lines += ["From `api_calls.jsonl`, written by the client as each call finished.", ""]
    lines += ["| time (UTC) | step | frame | model | call | returned |", "|---|---|---|---|---|---|"]
    for r in rows:
        cells = [stamp(r["t"]), str(r.get("step") or ""), r.get("frame") or "", r["model"], r["purpose"],
                 r["returned"]]
        lines.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Write CALLS.md: the Meta Model API calls of a run.")
    ap.add_argument("run", type=Path, help="run folder (runs\\<timestamp>)")
    ap.add_argument("--title", help="heading for the table")
    ap.add_argument("--derived-jsonl", action="store_true",
                    help="also write api_calls_derived.jsonl for a run without api_calls.jsonl")
    args = ap.parse_args()
    (args.run / "CALLS.md").write_text(table(args.run, args.title), encoding="utf-8")
    if args.derived_jsonl and not (args.run / "api_calls.jsonl").exists():
        with open(args.run / "api_calls_derived.jsonl", "w", encoding="utf-8") as f:
            for r in derive(_events(args.run)):
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(args.run / "CALLS.md")


if __name__ == "__main__":
    main()
