from muse_body.agent import phrase_tails, stalled
from muse_body.meta_api import extract_json
from muse_body.sam_format import Detection
from muse_body.steer import bearing_deg, pick, steer


def box(x1, y1, x2, y2, conf=None):
    return Detection("1", x1, y1, x2, y2, 1280, 720, conf=conf)


def test_centered_far_target_walks():
    cmd = steer(box(600, 300, 680, 420))
    assert abs(cmd.bearing_deg) < 1
    assert cmd.walk and cmd.turn_deg == 0.0 and not cmd.arrived


def test_off_axis_target_turns_only():
    cmd = steer(box(1100, 300, 1200, 420))
    assert cmd.bearing_deg > 12
    assert not cmd.walk and cmd.turn_deg == cmd.bearing_deg * 0.9


def test_left_is_negative():
    assert bearing_deg(box(0, 300, 100, 400), 70.0) < 0


def test_big_centered_target_arrived():
    cmd = steer(box(500, 100, 780, 600))
    assert cmd.arrived and not cmd.walk and cmd.turn_deg == 0.0


def test_short_target_touching_bottom_arrived():
    # Live 10-28: sitting raccoon at (505,567)-(811,719) was lost one pulse later.
    assert steer(box(505, 567, 811, 719)).arrived
    assert not steer(box(600, 300, 680, 420)).arrived


def test_arrived_off_centre_still_turns():
    # Live 10-29: person at 64% height, 11 deg right, never re-centred.
    cmd = steer(box(780, 100, 960, 560))
    assert cmd.arrived and not cmd.walk and cmd.turn_deg > 3


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


def test_pick_near_leaves_out_far_boxes():
    # Live 11-02 (runs/errand4, step 3): Muse Spark pointed at the counter; the only match
    # for "restaurant menu" was the menu board on the wall, 0.32 of the frame away.
    board, hint = box(749, 129, 942, 242), (566, 564)
    assert pick([board], hint=hint) is board
    assert pick([board], hint=hint, near=0.25) is None
    menu = box(690, 380, 740, 440)
    assert pick([board, menu], hint=hint, near=0.25) is menu
    big = box(500, 300, 900, 700)  # contains the hint: kept however far its centre is
    assert pick([big], hint=(400, 450), near=0.01) is big


def test_stalled_needs_steady_bearing_and_no_growth():
    # Live 11-02 (runs/errand3, step 3): walking straight at the menu, bearing steady, box growing.
    walking = [(1.5, 0.06), (0.7, 0.07), (1.0, 0.09), (1.4, 0.13)]
    assert not stalled(walking)
    assert stalled([(1.5, 0.06), (0.7, 0.06), (1.0, 0.06), (1.4, 0.062)])
    assert not stalled([(1.5, 0.06), (0.7, 0.06), (1.0, 0.06)])  # too few moves
    assert not stalled([(5.0, 0.06), (0.7, 0.06), (1.0, 0.06), (1.4, 0.06)])  # still turning


def test_phrase_tails():
    assert phrase_tails("green striped dinosaur") == [
        "green striped dinosaur", "striped dinosaur", "green dinosaur", "dinosaur"]
    assert phrase_tails("raccoon") == ["raccoon"]


def test_extract_json_tolerates_fences():
    assert extract_json('Sure!\n```json\n{"intent": "wait"}\n```')["intent"] == "wait"
    assert extract_json('{"intent": "say", "say": "hi"} trailing')["say"] == "hi"
