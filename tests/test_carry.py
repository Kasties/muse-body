"""Carrying: the held object and the avatar's own arm stay put on screen (live 11-02)."""
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

import muse_body.agent as agent_mod
from muse_body.agent import HOLDING, Agent, Errands, Memory
from muse_body.body import Body
from muse_body.sam_format import Detection
from muse_body.steer import (SteerParams, covered, elevation_deg, iou, screen_x, screen_y, steer,
                             x_bearing)


def box(x1, y1, x2, y2, conf=0.8):
    return Detection("1", x1, y1, x2, y2, 1280, 720, conf=conf)


# Boxes from runs/errand2: the menu after grabbing, the avatar's own furry arm, the requester,
# and a cartoon printed on the menu that SAM 'character' also matched.
MENU, ARM = box(460, 10, 740, 560), box(715, 113, 1279, 719)
PLUSH, CARTOON = box(120, 312, 308, 598), box(473, 430, 498, 462)


def carrying() -> Agent:
    a = object.__new__(Agent)  # just the carrying state, no camera or controller
    a.steer_params = SteerParams()
    a.holding, a.held_box, a.own_boxes = True, MENU, []
    return a


def test_screen_x_inverts_bearing():
    for x in (0.0, 383.0, 640.0, 1279.0):
        assert abs(screen_x(x_bearing(x, 70.0, 1280, 720), 70.0, 1280, 720) - x) < 1e-6


def test_screen_y_inverts_elevation():
    for y in (0, 200, 360, 719):
        assert abs(screen_y(elevation_deg(box(0, y, 10, y), 70.0), 70.0, 720) - y) < 1e-6


def test_overlap_measures():
    assert iou(ARM, ARM) == 1.0 and iou(ARM, PLUSH) == 0.0
    assert covered(CARTOON, MENU) == 1.0 and covered(MENU, CARTOON) < 0.01


def test_own_arm_and_held_object_are_not_people():
    a = carrying()
    assert a.is_own(ARM) and a.is_own(CARTOON)
    assert not a.is_own(PLUSH)
    # The arm is remembered, so a slightly smaller box of it next frame is caught too.
    assert a.own_boxes == [ARM] and a.is_own(box(716, 160, 1270, 719))


def test_person_is_kept_beside_the_held_object():
    a = carrying()
    offset = a.beside_held_deg()  # left of the menu: the arm fills the right side
    assert -30 < offset < -20
    # The requester 40 deg left: turn only part of the way, so they stay visible beside the menu.
    cmd = steer(PLUSH, arrive_height=0.40, offset_deg=offset)
    assert not cmd.arrived and -18 < cmd.turn_deg < -8
    # Once there, walk on with them at that bearing; on arrival face them fully.
    there = box(int(screen_x(offset, 70.0, 1280, 720)) - 50, 300, int(screen_x(offset, 70.0, 1280, 720)) + 50, 500)
    assert steer(there, arrive_height=0.40, offset_deg=offset).walk
    close = box(330, 150, 440, 600)
    arrived = steer(close, arrive_height=0.40, offset_deg=offset)
    assert arrived.arrived and arrived.turn_deg < -15


def test_nothing_held_means_no_offset():
    a = carrying()
    a.held_box = None
    assert a.beside_held_deg() == -25.0  # holding, but SAM did not find the object
    a.holding = False
    assert a.beside_held_deg() == 0.0 and not a.is_own(ARM)


class FakeApi:
    """Muse Spark always answers `reply`; SAM's 'character' finds the next box list in `seen`
    (the last one repeats)."""

    def __init__(self, reply, seen):
        self.reply, self.seen, self.prompts = reply, list(seen), []

    def see(self, image, system, prompt):
        self.prompts.append(prompt)
        return self.reply

    def segment(self, frame, phrase):
        if phrase != "character":
            return []
        return list(self.seen.pop(0) if len(self.seen) > 1 else self.seen[0])


class FakeCam:
    def grab(self):
        return Image.new("RGB", (1280, 720))


def deciding(reply='{"intent": "wait"}', seen=([],)) -> Agent:
    a = carrying()
    a.api, a.pool, a.cam, a.ears, a.senses = FakeApi(reply, seen), ThreadPoolExecutor(1), FakeCam(), None, None
    a.body, a.dry_run = Body(dry_run=True), True  # prints what it would send
    a.memory, a.errands, a.goal, a.log_dir, a.step = Memory(), Errands(), "help people", None, 0
    a.people, a.last_seen, a.tracked, a.found_phrase = [], None, None, None
    return a


def test_muse_spark_is_told_its_own_arm_is_in_view_while_carrying():
    a = deciding()
    a.decide(FakeCam().grab())
    assert f"Body: {HOLDING}\n" in a.api.prompts[0]
    a.let_go()
    a.decide(FakeCam().grab())
    assert "Body:" not in a.api.prompts[1]


# runs/demo1 steps 6-7 (11-03): with the clipboard in hand, Muse Spark pointed "give" at the fur
# at the right edge of the view; SAM's only 'character' was that arm, and both approaches were lost.
GIVE = ('{"intent": "give", "target": "beige fluffy avatar", "target_xy": [850, 500], '
        '"target_is_person": true, "say": "Here is your clipboard!"}')


def test_a_give_with_nobody_in_view_looks_for_them_first(monkeypatch):
    monkeypatch.setattr(agent_mod.time, "sleep", lambda s: None)
    # Decision: only the arm. Scan: the arm at 30 degrees, the plush too at 60.
    a = deciding(GIVE, seen=[[ARM], [ARM], [ARM, PLUSH]])
    walks = []
    a.approach = lambda target, **kw: walks.append((target, kw["hint"])) or True
    a.tick()
    assert walks == [] and a.holding
    assert a.memory.events == ["looked around for beige fluffy avatar: no one was in view to hand it to",
                               "scanned 60 degrees right and now see 1 person(s)"]
    # Next decision: the plush is in view, and the hand-over walks to them, not to the arm.
    a.tick()
    ((target, (x, y)),) = walks
    assert target == "beige fluffy avatar" and 160 < x < 175 and 625 < y < 640


def test_a_grab_counts_only_with_the_drop_prompt():
    # demo3 (11-04): grab pressed on a drink menu panel on the wall; the hand stayed empty.
    a = deciding('{"holding": false, "why": "No Drop prompt visible"}')
    a.note_held("standing menu board")
    assert not a.holding and a.held_box is None
    assert a.memory.events == ["the grab on 'standing menu board' did not take: no 'Drop' prompt, "
                               "the hand is empty"]
    b = deciding('{"holding": true, "why": "Drop prompt with B icon visible"}')
    b.holding = False
    b.note_held("menu")
    assert b.holding and b.memory.events == []
    c = deciding("no json here")  # no answer: counted as taken, as before the check
    c.holding = False
    c.note_held("menu")
    assert c.holding


def test_a_people_scan_takes_smaller_steps_while_carrying(monkeypatch):
    monkeypatch.setattr(agent_mod.time, "sleep", lambda s: None)
    a = deciding(seen=[[ARM]])  # nobody else anywhere
    turns = []
    a.body.turn_by = turns.append
    a.scan()
    # Only the ~37 degrees left of the held object are clear, so every step stays below that.
    assert turns == [30.0] * 12 and a.memory.events == ["scanned a full circle and saw nobody"]
    a.let_go()
    a.api.seen, turns[:] = [[]], []
    a.scan()
    assert turns == [60.0] + [45.0] * 6
