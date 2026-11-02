"""Carrying: the held object and the avatar's own arm stay put on screen (live 11-02)."""
from muse_body.agent import Agent
from muse_body.sam_format import Detection
from muse_body.steer import SteerParams, covered, iou, screen_x, steer, x_bearing


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
