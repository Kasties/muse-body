"""Object scans: SAM 3.1 proposes, Muse Spark picks (live 11-02, cafe world)."""
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

import muse_body.agent as agent_mod
from muse_body.agent import MARK, Agent, Errands, Memory, numbered
from muse_body.sam_format import Detection
from muse_body.steer import SteerParams


def box(x1, y1, x2, y2, conf):
    return Detection("1", x1, y1, x2, y2, 1280, 720, conf=conf)


# runs/errand3 frame 7: "printed menu" matched only the menu board on the wall; "menu" also
# found a screen on the wall and the clipboard menu on the counter.
BOARD, SCREEN, CLIPBOARD = (1081, 33, 1279, 160), (807, 176, 939, 285), (1104, 272, 1155, 322)
FRAME7 = {"printed menu": [box(*BOARD, 0.69)],
          "menu": [box(*SCREEN, 0.57), box(*BOARD, 0.85), box(*CLIPBOARD, 0.52)]}


class FakeApi:
    def __init__(self, found, reply):
        self.found, self.reply, self.asked = found, reply, []

    def segment(self, frame, phrase):
        return list(self.found.get(phrase, []))

    def see(self, image, system, prompt):
        self.asked.append((image.size, prompt))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class FakeBody:
    has_pad = True

    def __init__(self):
        self.turns, self.looks = [], []

    def turn_by(self, deg):
        self.turns.append(deg)

    def look_by(self, deg):
        self.looks.append(deg)

    def stop(self):
        pass

    def walk(self, seconds=0.6):
        pass


class FakeCam:
    def grab(self):
        return Image.new("RGB", (1280, 720))


def scanner(found, reply='{"pick": null, "why": "a wall board"}') -> Agent:
    a = object.__new__(Agent)  # no camera, controller or API key
    a.api, a.pool = FakeApi(found, reply), ThreadPoolExecutor(2)
    a.body, a.cam, a.memory, a.log_dir = FakeBody(), FakeCam(), Memory(), None
    a.steer_params, a.errands, a.last_seen = SteerParams(), Errands(), None
    a.holding, a.held_box, a.own_boxes, a.found_phrase = False, None, [], None
    return a


def test_muse_spark_picks_the_real_object_among_sams_matches():
    a = scanner(FRAME7, '{"pick": 3, "why": "the menu on the counter"}')
    det, phrase, record = a.find_object(Image.new("RGB", (1280, 720)), "printed menu")
    # The board found by both phrases is numbered once.
    assert record["candidates"] == [list(BOARD), list(SCREEN), list(CLIPBOARD)]
    assert (det.x1, det.y1, det.x2, det.y2) == CLIPBOARD and phrase == "menu"
    assert record["pick"] == 3 and record["check"] == "the menu on the counter"
    assert a.api.asked == [((1280, 720), "Looking for: printed menu")]


def test_pictures_of_it_are_not_it():
    a = scanner({"printed menu": [box(301, 184, 706, 279, 0.7)]})  # errand1: overhead board only
    det, phrase, record = a.find_object(Image.new("RGB", (1280, 720)), "printed menu")
    assert det is None and record["pick"] is None and len(record["candidates"]) == 1


def test_no_match_asks_nobody():
    a = scanner({})
    assert a.find_object(Image.new("RGB", (1280, 720)), "printed menu") == (None, "printed menu", {})
    assert a.api.asked == []


def test_odd_picks():
    frame = Image.new("RGB", (1280, 720))
    assert scanner(FRAME7, '{"pick": 7}').find_object(frame, "printed menu")[0] is None
    assert scanner(FRAME7, '{"pick": "none"}').find_object(frame, "printed menu")[0] is None
    det = scanner(FRAME7, '{"pick": "2"}').find_object(frame, "printed menu")[0]
    assert (det.x1, det.y1, det.x2, det.y2) == SCREEN
    # Without an answer the scan trusts SAM's most confident match, as before the check.
    det, _, record = scanner(FRAME7, TimeoutError("slow")).find_object(frame, "printed menu")
    assert (det.x1, det.y1, det.x2, det.y2) == BOARD and record["check"] == "not checked"


def test_scan_turns_to_face_what_it_found(monkeypatch):
    monkeypatch.setattr(agent_mod.time, "sleep", lambda s: None)
    a = scanner({"menu": [box(*CLIPBOARD, 0.52)]}, '{"pick": 1, "why": "on the counter"}')
    a.scan(target="printed menu")
    first, face = a.body.turns
    assert first == 45.0 and 43 < face < 44  # live, the approach measured it at 43.6 deg
    assert a.found_phrase == "menu"
    assert a.memory.events == ["scanned 45 degrees right and now face 'printed menu'"]


def test_scan_goes_on_past_pictures(monkeypatch):
    monkeypatch.setattr(agent_mod.time, "sleep", lambda s: None)
    a = scanner({"printed menu": [box(*BOARD, 0.69)]})
    a.scan(target="printed menu")
    assert a.body.turns == [45.0] * 8 and a.found_phrase is None
    assert a.memory.events == ["scanned a full circle and did not find 'printed menu' "
                               "(8 pictures or look-alikes ruled out)"]


def test_grab_grounds_with_the_scans_phrase_and_muse_sparks_pick():
    # errand4 step 3: SAM found nothing for "black menu stand" or its tails, and the scan's
    # phrase "restaurant menu" only matched a wall board 0.32 away from where Muse Spark pointed.
    board, counter = box(749, 129, 942, 242, 0.73), box(544, 352, 572, 393, 0.5)
    a = scanner({"restaurant menu": [board], "menu": [board, counter]},
                '{"pick": 2, "why": "on the counter"}')
    frame, hint = Image.new("RGB", (1280, 720)), (566.0, 564.0)
    assert a.ground(frame, "black menu stand", hint, near=0.25) == (None, "black menu stand")
    assert a.api.asked == []  # no scan phrase yet: Muse Spark is not asked
    a.found_phrase = "restaurant menu"
    det, phrase = a.ground(frame, "black menu stand", hint, near=0.25)
    assert det is counter and phrase == "menu"
    assert a.api.asked == [((1280, 720), "Looking for: restaurant menu")]
    assert a.ground(frame, "red cup", hint, near=0.25) == (None, "red cup")  # not what the scan found


def test_grab_aims_where_the_approach_arrived(monkeypatch):
    # errand4 step 3: aiming re-grounded "black menu stand" and turned toward a "black stand".
    monkeypatch.setattr(agent_mod.time, "sleep", lambda s: None)
    a, aimed = scanner({}), []
    a.body.level = lambda: None

    def approach(target, **kw):
        a.tracked = ("restaurant menu", (537.0, 735.0))
        return True

    a.approach, a.aim = approach, lambda target, hint: aimed.append((target, hint))
    a.grab("black menu stand", (566.0, 564.0))
    assert aimed == [("restaurant menu", (537.0, 735.0))]


def test_aim_starts_at_the_menu_in_front():
    # errand4 frame 20, arrived: the menu right in front sits low; another stands further back.
    front, back = box(627, 402, 749, 657, 0.8), box(384, 374, 424, 490, 0.7)
    a = scanner({"restaurant menu": [back, front]})
    hint = a.after_turn(front, 5.3 * 0.9)
    det, _ = a.ground(Image.new("RGB", (1280, 720)), "restaurant menu", hint)
    assert det is front
    det, _ = a.ground(Image.new("RGB", (1280, 720)), "restaurant menu", (500.0, 500.0))
    assert det is back  # what the screen centre picked


def test_the_scans_phrase_goes_before_tails_of_the_name():
    # errand5 step 2: the scan had found the pens as "small pen"; Muse Spark then asked to
    # grab the "colorful pen display", and its tail "display" was the whiteboard above them.
    pen, whiteboard = box(728, 380, 736, 422, 0.6), box(662, 241, 789, 342, 0.68)
    a = scanner({"small pen": [pen], "display": [whiteboard]})
    a.found_phrase = "small pen"
    det, phrase = a.ground(Image.new("RGB", (1280, 720)), "colorful pen display", (571.0, 526.0),
                           near=0.25)
    assert det is pen and phrase == "small pen" and a.api.asked == []
    # Live, SAM did not see the pens from there at all: no "display" then, the check is asked.
    b = scanner({"display": [whiteboard]})
    b.found_phrase = "small pen"
    assert b.ground(Image.new("RGB", (1280, 720)), "colorful pen display", (571.0, 526.0),
                    near=0.25) == (None, "colorful pen display")
    assert b.api.asked == []  # no pen candidates, so nothing to check


def test_full_circles_without_it_are_counted_on_the_errand(monkeypatch):
    # errand5: seven full circles for a pen from next to the whiteboard.
    monkeypatch.setattr(agent_mod.time, "sleep", lambda s: None)
    a = scanner({})
    a.errands.current = {"task": "get a pen", "for": "plush", "heard": "Can you get me a pen?"}
    a.scan(target="small pen")
    a.scan(target="pen")
    assert a.errands.current["missed"] == 2
    assert a.errands.describe().endswith("; looked all around 2 time(s) without finding it")


def test_approach_looks_down_at_a_low_object():
    # errand5 frame 19: walking up to a pen in a tray below the view centre, about -20 degrees;
    # the next frame it had sunk out of view.
    a = scanner({})
    frames = [box(718, 506, 732, 579, 0.78), box(600, 250, 700, 420, 0.8)]
    hints = []

    def ground(frame, target, hint, person=False, near=None):
        hints.append(hint)
        return frames.pop(0), target

    a.ground = ground
    assert a.approach("small pen", hint=(560.0, 753.0), arrive_height=0.22)
    (look,) = a.body.looks
    assert -19 < look < -16
    assert 480 < hints[1][1] < 560  # expected back near the middle of the view


def test_check_logs_what_each_box_is():
    reply = '{"boxes": {"1": "wall menu board", "2": "wall screen", "3": "countertop menu stand"}, "pick": 3}'
    _, _, record = scanner(FRAME7, reply).find_object(Image.new("RGB", (1280, 720)), "printed menu")
    assert record["labels"] == ["wall menu board", "wall screen", "countertop menu stand"]


def test_numbered_draws_on_a_copy():
    frame = Image.new("RGB", (1280, 720))
    marked = numbered(frame, [box(*CLIPBOARD, 0.5)])
    assert marked.size == frame.size and frame.getpixel((1104, 300)) == (0, 0, 0)
    assert marked.getpixel((1104, 300)) == MARK
