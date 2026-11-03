"""--input osc: VRChat's desktop OSC input moves, turns and jumps; hand actions need the pad."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image

import muse_body.agent as agent_mod
from muse_body.agent import NO_PAD, Agent, Errands, Memory
from muse_body.body import Body
from muse_body.steer import SteerParams


class FakeApi:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def see(self, image, system, prompt):
        self.prompts.append(prompt)
        return self.reply

    def segment(self, frame, phrase):
        return []


class FakeCam:
    def grab(self):
        return Image.new("RGB", (1280, 720))


def agent_on(locomotion: str, reply: str = '{"intent": "wait"}') -> Agent:
    a = object.__new__(Agent)  # no camera, controller, microphone or API key
    a.api, a.pool, a.cam, a.ears, a.senses = FakeApi(reply), ThreadPoolExecutor(1), FakeCam(), None, None
    a.body, a.dry_run = Body(dry_run=True, locomotion=locomotion), True  # prints what it would send
    a.memory, a.errands, a.goal, a.log_dir, a.step = Memory(), Errands(), "help people", None, 0
    a.holding, a.held_box, a.own_boxes, a.people = False, None, [], []
    a.steer_params, a.last_seen, a.tracked, a.found_phrase = SteerParams(), None, None, None
    return a


def test_only_the_pad_has_buttons():
    assert Body(dry_run=True).has_pad
    assert not Body(dry_run=True, locomotion="osc").has_pad


def test_muse_spark_is_told_what_the_body_cannot_do():
    osc, pad = agent_on("osc"), agent_on("pad")
    osc.decide(None)
    pad.decide(None)
    assert f"Body: {NO_PAD}\n" in osc.api.prompts[0]
    assert "Body:" not in pad.api.prompts[0]


@pytest.mark.parametrize("reply, skipped", [
    ('{"intent": "gesture", "gesture": "thumbsup"}', "could not show thumbsup"),
    ('{"intent": "wave", "say": "Hi!", "gesture": "open"}', "could not show open"),
    ('{"intent": "grab", "target": "menu"}', "could not pick up 'menu'"),
    ('{"intent": "give", "target": "beige plush"}', "could not hand anything to beige plush"),
    ('{"intent": "drop"}', "could not let go"),
    ('{"intent": "crouch"}', "could not crouch"),
])
def test_hand_actions_are_skipped_and_remembered(monkeypatch, reply, skipped):
    monkeypatch.setattr(agent_mod.time, "sleep", lambda s: None)
    a = agent_on("osc", reply)
    a.tick()  # each of these raised ValueError (no OSC input for the button) and ended the run
    assert any(e.startswith(skipped) for e in a.memory.events)
    done = ("right hand now shows", "pressed grab", "handed", "dropped", "toggled")
    assert not any(e.startswith(done) for e in a.memory.events)


def test_a_greeting_still_talks_without_the_pad():
    a = agent_on("osc")
    a.greet({"say": "Hi there!", "gesture": "thumbsup"})
    assert a.memory.events == ["said 'Hi there!'", "could not show thumbsup: no gamepad (--input osc)"]


def test_the_pad_still_shows_hand_signs(monkeypatch):
    monkeypatch.setattr(agent_mod.time, "sleep", lambda s: None)
    a = agent_on("pad", '{"intent": "gesture", "gesture": "thumbsup"}')
    a.tick()
    assert a.memory.events[-1] == "right hand now shows thumbsup"
