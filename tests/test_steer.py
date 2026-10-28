from muse_body.agent import phrase_tails
from muse_body.meta_api import extract_json
from muse_body.sam_format import Detection
from muse_body.steer import bearing_deg, pick, steer


def box(x1, y1, x2, y2, conf=None):
    return Detection("1", x1, y1, x2, y2, 1280, 720, conf=conf)


def test_centered_far_target_walks():
    cmd = steer(box(600, 300, 680, 420))
    assert abs(cmd.bearing_deg) < 1
    assert cmd.forward == 1.0 and not cmd.arrived


def test_off_axis_target_turns_only():
    cmd = steer(box(1100, 300, 1200, 420))
    assert cmd.bearing_deg > 12
    assert cmd.forward == 0.0 and cmd.turn > 0


def test_left_is_negative():
    assert bearing_deg(box(0, 300, 100, 400), 70.0) < 0


def test_big_centered_target_arrived():
    cmd = steer(box(500, 100, 780, 600))
    assert cmd.arrived and cmd.forward == 0.0 and cmd.turn == 0.0


def test_short_target_touching_bottom_arrived():
    # Live 10-28: sitting raccoon at (505,567)-(811,719) was lost one pulse later.
    assert steer(box(505, 567, 811, 719)).arrived
    assert not steer(box(600, 300, 680, 420)).arrived


def test_pick_prefers_confident():
    a, b = box(0, 0, 500, 500, conf=0.35), box(0, 0, 50, 50, conf=0.9)
    assert pick([a, b]) is b
    assert pick([box(0, 0, 10, 10, conf=0.1)]) is None


def test_pick_hint_beats_confidence():
    # Real case from rig3: "green dinosaur" matched the HUD preview (top right, 0.85)
    # and the reflection in the mirror (centre, 0.84).
    hud, body = box(991, 43, 1185, 249, conf=0.85), box(623, 336, 679, 471, conf=0.84)
    assert pick([hud, body]) is hud
    assert pick([hud, body], hint=(510, 560)) is body
    assert pick([hud, body], hint=(400, 600)) is body  # nearest when no box contains it


def test_phrase_tails():
    assert phrase_tails("green striped dinosaur") == [
        "green striped dinosaur", "green dinosaur", "striped dinosaur", "dinosaur"]
    assert phrase_tails("raccoon") == ["raccoon"]


def test_extract_json_tolerates_fences():
    assert extract_json('Sure!\n```json\n{"intent": "wait"}\n```')["intent"] == "wait"
    assert extract_json('{"intent": "say", "say": "hi"} trailing')["say"] == "hi"
