"""CALLS.md: the calls a run made, from api_calls.jsonl or derived from events.jsonl."""
import json

from muse_body.calls import ASR, SAM, SPARK, derive, table
from muse_body.meta_api import CallLog


def test_a_decision_implies_spark_people_and_the_utterances_it_heard():
    rows = derive([{"step": 2, "t": 10.0, "phase": "decide", "frame": "00003.jpg", "intent": "say",
                    "reply": "hi!", "say": "hi!", "people": [[0, 0, 1, 1]], "voice": ["hello"]}])
    assert [r["model"] for r in rows] == [ASR, SPARK, SAM]
    assert rows[1]["returned"] == "say; replies 'hi!'"  # said once, not twice
    assert all(r["derived"] and r["frame"] == "00003.jpg" for r in rows)


def test_an_object_scan_implies_both_phrases_and_the_spark_pick():
    rows = derive([{"step": 4, "t": 1.0, "phase": "scan", "turned": 180, "target": "cafe menu",
                    "candidates": [[0, 0, 1, 1], [2, 2, 3, 3]], "pick": 2, "check": "on the counter"}])
    assert [(r["model"], r["purpose"].split(" (")[0]) for r in rows] == [
        (SAM, "find 'cafe menu'"), (SAM, "find 'menu'"), (SPARK, "pick the real 'cafe menu' among 2 numbered matches")]
    assert derive([{"t": 1.0, "phase": "scan", "turned": 45, "target": "menu"}])[0]["returned"] == "no match"


def test_a_people_scan_and_an_act_line(tmp_path):
    rows = derive([{"t": 1.0, "phase": "scan", "turned": 60, "people": []}, {"t": 2.0, "phase": "act", "act": "x"}])
    assert len(rows) == 1 and rows[0]["model"] == SAM


def test_the_table_prefers_the_recorded_log(tmp_path):
    (tmp_path / "events.jsonl").write_text(json.dumps({"t": 5.0, "phase": "decide", "intent": "wait"}) + "\n")
    assert "Derived from" in table(tmp_path)
    CallLog(tmp_path / "api_calls.jsonl").write({"t": 1.7e9, "api": "chat/completions", "seconds": 4.2,
                                                 "status": 200, "response_id": "chatcmpl-1",
                                                 "usage": {"total_tokens": 900}})
    md = table(tmp_path)
    assert "From `api_calls.jsonl`" in md and "chatcmpl-1" in md and "900 tokens" in md
