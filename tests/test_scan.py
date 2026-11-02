"""Object scans: SAM 3.1 proposes, Muse Spark picks (live 11-02, cafe world)."""
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

import muse_body.agent as agent_mod
from muse_body.agent import MARK, Agent, Memory, numbered
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
    def __init__(self):
        self.turns = []

    def turn_by(self, deg):
        self.turns.append(deg)


class FakeCam:
    def grab(self):
        return Image.new("RGB", (1280, 720))


def scanner(found, reply='{"pick": null, "why": "a wall board"}') -> Agent:
    a = object.__new__(Agent)  # no camera, controller or API key
    a.api, a.pool = FakeApi(found, reply), ThreadPoolExecutor(2)
    a.body, a.cam, a.memory, a.log_dir = FakeBody(), FakeCam(), Memory(), None
    a.steer_params = SteerParams()
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


def test_grab_grounds_with_the_phrase_the_scan_found():
    # errand3 step 2: SAM found nothing for "black menu stand" or any of its tails.
    a = scanner({"menu": [box(*SCREEN, 0.61), box(*BOARD, 0.84), box(*CLIPBOARD, 0.53)]})
    frame, hint = Image.new("RGB", (1280, 720)), (859.0, 375.0)
    assert a.ground(frame, "black menu stand", hint) == (None, "black menu stand")
    a.found_phrase = "menu"
    det, phrase = a.ground(frame, "black menu stand", hint)
    assert (det.x1, det.y1, det.x2, det.y2) == CLIPBOARD and phrase == "menu"
    assert a.ground(frame, "red cup", hint) == (None, "red cup")  # not what the scan found


def test_numbered_draws_on_a_copy():
    frame = Image.new("RGB", (1280, 720))
    marked = numbered(frame, [box(*CLIPBOARD, 0.5)])
    assert marked.size == frame.size and frame.getpixel((1104, 300)) == (0, 0, 0)
    assert marked.getpixel((1104, 300)) == MARK
