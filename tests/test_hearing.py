"""Hearing: Muse Voice Transcribe's realtime events in, finished utterances out to the decision."""
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

import muse_body.hearing as hearing
from muse_body.agent import Agent, Errands, Memory
from muse_body.config import Settings
from muse_body.hearing import Ears, Heard, to_pcm

ASK = "Hey, could you bring me a menu, please?"


def ears() -> Ears:
    return Ears(Settings(api_key="test-key"), echo=False)


def test_one_utterance_per_turn():
    # The realtime probe of 11-03, ENDPOINTING: the text comes with speechComplete, not speechEnd.
    e = ears()
    e.on_event({"type": "speechStart", "audioProcessedMs": 1740, "turnId": 0})
    e.on_event({"type": "transcript", "transcript": "Hey, could you", "final": False})
    assert e.listening() and e.take() == []
    e.on_event({"type": "speechEnd", "audioProcessedMs": 5020, "turnId": 0})
    assert e.listening()
    e.on_event({"type": "speechComplete", "audioProcessedMs": 5020, "turnId": 0, "transcript": ASK})
    assert not e.listening()
    assert [h.text for h in e.take()] == [ASK]
    assert e.take() == []


def test_overlapping_turns_and_empty_ones():
    e = ears()
    e.on_event({"type": "speechStart", "turnId": 1})
    e.on_event({"type": "speechStart", "turnId": 2})  # a later turn can open first
    e.on_event({"type": "speechComplete", "turnId": 1, "transcript": "Hi there."})
    assert e.listening()
    e.on_event({"type": "speechComplete", "turnId": 2, "transcript": "  "})
    assert not e.listening() and [h.text for h in e.take()] == ["Hi there."]
    e.on_event({"type": "transcript", "transcript": "", "final": True})  # after endStream
    assert e.take() == []


def test_long_noise_does_not_hold_the_agent(monkeypatch):
    # Music or a crowd can keep a turn open for a long time: the agent stops waiting for it.
    now = [1000.0]
    monkeypatch.setattr(hearing.time, "time", lambda: now[0])
    e = ears()
    e.on_event({"type": "speechStart", "turnId": 0})
    assert e.listening()
    now[0] += 11
    assert not e.listening()


def test_wait_until_quiet_gives_up():
    e = ears()
    e.on_event({"type": "speechStart", "turnId": 0})
    t = time.time()
    e.wait_until_quiet(timeout=0.3)
    assert 0.25 < time.time() - t < 1.0


def test_handshake_and_url():
    e = ears()
    assert e.url == "wss://api.meta.ai/v1/asr/realtime"
    h = e.handshake()
    assert h["authorization"] == {"accessToken": "Bearer test-key"}
    assert (h["model"], h["mode"], h["audioEncoding"]) == ("muse-voice-transcribe-1.0", "ENDPOINTING", "PCM_24KHZ")


def test_to_pcm():
    mono = np.array([[0.0], [0.5], [-1.0], [2.0]], dtype=np.float32)
    assert np.frombuffer(to_pcm(mono), "<i2").tolist() == [0, 16383, -32767, 32767]
    stereo = np.array([[1.0, 0.0], [-0.5, -0.5]], dtype=np.float32)
    assert np.frombuffer(to_pcm(stereo), "<i2").tolist() == [16383, -16383]


def test_prompt_lists_what_was_heard():
    p = Memory().prompt("help people", body="standing still", heard=[(2.4, ASK)])
    assert f'Heard 2 s ago: "{ASK}"' in p
    assert p.index("Body:") < p.index("Heard") < p.index("Recent:")
    assert "Heard" not in Memory().prompt("help people")


class FakeApi:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def see(self, image, system, prompt):
        self.prompts.append(prompt)
        return self.reply

    def segment(self, frame, phrase):
        return []


class FakeBody:
    def __init__(self):
        self.said = []

    def thinking(self, on):
        pass

    def mood(self, mood):
        pass

    def say(self, text):
        self.said.append(text)


class FakeEars:
    def __init__(self, heard):
        self.heard = heard

    def take(self):
        out, self.heard = self.heard, []
        return out


def listener(heard, reply) -> Agent:
    a = object.__new__(Agent)  # no camera, controller, microphone or API key
    a.api, a.pool, a.body, a.ears = FakeApi(reply), ThreadPoolExecutor(1), FakeBody(), FakeEars(heard)
    a.senses, a.memory, a.errands, a.goal, a.log_dir, a.step = None, Memory(), Errands(), "help people", None, 0
    a.holding, a.held_box, a.own_boxes = False, None, []
    return a


def test_a_spoken_request_becomes_the_errand():
    reply = ('{"heard": "Hey could you bring me a menu please", "new_errand": "bring a menu", '
             '"requester": "beige plush", "reply": "Sure, getting you a menu!", "intent": "look_around", '
             '"target": "menu"}')
    a = listener([Heard(ASK, time.time() - 2.0)], reply)
    d = a.decide(None)
    assert f'Heard 2 s ago: "{ASK}"' in a.api.prompts[0]
    assert d["voice"] == [ASK] and a.body.said == ["Sure, getting you a menu!"]
    # Muse Spark's copy dropped the punctuation; it is still what was said, not written.
    assert "who said 'Hey could you bring me a menu please'" in a.errands.describe()
    # The next decision hears nothing new, but remembers what was said.
    a.decide(None)
    assert "Heard" not in a.api.prompts[1].split("Recent:")[0]
    assert f"heard someone say {ASK!r}" in a.api.prompts[1]
