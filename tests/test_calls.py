"""The per-run log of Meta Model API calls (api_calls.jsonl) and its ticker in the replay."""
import json

import httpx
import pytest
from PIL import Image

from muse_body.config import Settings
from muse_body.hearing import Ears
from muse_body.meta_api import CallLog, MetaClient
from muse_body.replay import Fonts, Shot, load_calls, render

KEY = "test-key-not-for-logs"


def client(tmp_path, handler) -> tuple[MetaClient, CallLog]:
    calls = CallLog(tmp_path / "api_calls.jsonl")
    return MetaClient(Settings(api_key=KEY), calls=calls, transport=httpx.MockTransport(handler)), calls


def lines(tmp_path) -> list[dict]:
    return [json.loads(x) for x in (tmp_path / "api_calls.jsonl").read_text(encoding="utf-8").splitlines()]


def test_a_muse_spark_call_is_logged_with_the_apis_ids(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(200, headers={"x-request-id": "req-123", "content-type": "application/json"},
                              json={"id": "chatcmpl-9", "model": "muse-spark", "usage": {"total_tokens": 812},
                                    "choices": [{"message": {"content": '{"intent": "wait"}'}}]})

    api, _ = client(tmp_path, handler)
    assert api.see(Image.new("RGB", (64, 36)), "system", "prompt") == '{"intent": "wait"}'
    (rec,) = lines(tmp_path)
    assert rec["api"] == "chat/completions" and rec["status"] == 200
    assert rec["x-request-id"] == "req-123" and rec["response_id"] == "chatcmpl-9"
    assert rec["usage"] == {"total_tokens": 812} and rec["seconds"] >= 0 and rec["t"] > 1.7e9
    assert KEY not in (tmp_path / "api_calls.jsonl").read_text(encoding="utf-8")


def test_a_failed_sam_call_is_logged_too(tmp_path):
    api, _ = client(tmp_path, lambda r: httpx.Response(500, json={"error": "busy"}))
    with pytest.raises(httpx.HTTPStatusError):
        api.segment(Image.new("RGB", (64, 36)), "menu")
    (rec,) = lines(tmp_path)
    assert rec["api"] == "responses" and rec["status"] == 500 and rec["phrase"] == "menu"


def test_heard_utterances_are_logged_with_their_session(tmp_path):
    e = Ears(Settings(api_key=KEY), echo=False, calls=CallLog(tmp_path / "api_calls.jsonl"))
    e._session = "sess-1"
    e.on_event({"type": "speechStart", "turnId": 3})
    e.on_event({"type": "speechComplete", "turnId": 3, "transcript": "bring me a menu", "audioProcessedMs": 4100})
    (rec,) = lines(tmp_path)
    assert rec["event"] == "transcript" and rec["session_id"] == "sess-1" and rec["turn_id"] == 3
    assert rec["transcript"] == "bring me a menu" and rec["audio_ms"] == 4100


def test_replay_counts_the_calls_finished_so_far(tmp_path):
    log = CallLog(tmp_path / "api_calls.jsonl")
    log.write({"t": 100.0, "api": "asr/realtime", "event": "session", "seconds": 0.2})
    log.write({"t": 100.0, "api": "chat/completions", "seconds": 3.0, "status": 200})
    log.write({"t": 101.0, "api": "responses", "seconds": 0.5, "status": 200})
    calls = load_calls(tmp_path)
    assert [c["api"] for c in calls] == ["responses", "chat/completions"]  # sessions are not calls
    frame = tmp_path / "00001.jpg"
    Image.new("RGB", (1280, 720)).save(frame)
    img = render(Shot(frame, 102.0, {"phase": "scan", "step": 1}, None, []), "goal", 100.0, Fonts(), [], calls)
    assert img.size == (1920, 1080)
    assert load_calls(tmp_path / "missing") == []
