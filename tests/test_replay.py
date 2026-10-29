import json

from PIL import Image

from muse_body.replay import load, render, Fonts


def test_load_attaches_actions_and_decision(tmp_path):
    for name in ("00001.jpg", "00002.jpg"):
        Image.new("RGB", (1280, 720)).save(tmp_path / name)
    events = [
        {"step": 1, "frame": "00001.jpg", "t": 10.0, "phase": "decide", "intent": "follow",
         "observation": "a person", "target_xy": [500, 500], "people": [[600, 300, 700, 500]]},
        {"step": 1, "t": 11.0, "phase": "act", "act": "said 'hi'"},
        {"step": 1, "frame": "00002.jpg", "t": 12.5, "phase": "follow", "target": "person",
         "box": [600, 300, 700, 500], "conf": 0.7, "bearing": 1.0, "arrived": True},
        {"step": 1, "frame": "missing.jpg", "t": 13.0, "phase": "scan", "people": []},
    ]
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    shots = load(tmp_path)
    assert [s.record["phase"] for s in shots] == ["decide", "follow"]
    assert shots[0].acts == ["said 'hi'"] and shots[0].duration == 2.5
    assert shots[1].decision["intent"] == "follow"
    img = render(shots[1], "goal", shots[0].t, Fonts(), ["said 'hi'"])
    assert img.size == (1920, 1080)
