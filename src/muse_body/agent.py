"""The loop: hear (Muse Voice Transcribe) and see (Muse Spark) -> ground (SAM 3.1) -> move -> repeat."""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .body import GESTURES, THINKING_PARAM, Body
from .capture import Camera, is_foreground
from .config import Settings
from .hearing import Ears
from .meta_api import MetaClient, extract_json
from .sam_format import Detection
from .senses import Senses
from .steer import (SteerParams, bearing_deg, covered, elevation_deg, iou, pick, screen_x, screen_y,
                    steer, x_bearing)

SYSTEM = """You are the mind of an avatar in VRChat. You see one first-person frame at a time.
Choose ONE next intention. Reply with a single JSON object only:
{
  "observation": "<one sentence: what you see>",
  "heard": "<the words in a chat bubble above another avatar's head, or a line under Heard, copied exactly, else null>",
  "new_errand": "<if those words ask you to do something: the task in a few words, else null>",
  "requester": "<who asked: the name on their nameplate if readable, and 2-4 words on their look>",
  "reply": "<a short chat answer to those words, sent right away, else null>",
  "intent": "approach" | "follow" | "look_around" | "wave" | "say" | "gesture" | "grab" | "give" | "drop" | "crouch" | "wait",
  "target": "<2-4 word visual description of the thing to approach, follow, grab or give to, else null>",
  "target_xy": [<x>, <y>] or null,
  "target_is_person": true | false,
  "say": "<chat text for say or wave, or to say on arrival with approach, follow or give, else null>",
  "gesture": "fist" | "open" | "point" | "victory" | "rocknroll" | "gun" | "thumbsup" | "neutral" | null,
  "errand_done": true | false,
  "mood": "neutral" | "happy" | "curious" | "confused" | "surprised",
  "why": "<one short reason>"
}
"mood" is the face your avatar shows from now on; people next to you see it.
"target" is passed to a segmentation model, so describe what it LOOKS like: species,
colour, clothing ("raccoon", "green dinosaur", "girl with pink hair"). Name the object itself
with its usual noun ("black clipboard"), not what it stands on ("menu stand").
"target_xy" is where the target is in this frame, in 0-1000 coordinates (0,0 top-left).
"target_is_person" is true for any avatar or character, even far away or stylised; the body then
also tracks them with a generic person detector, so they can be followed while they walk.
"follow" walks with a person who is moving around, stays close and keeps facing them.
With "approach" or "follow" you may also fill "say" and "gesture": with approach they happen the
moment you are close, with follow at the end of following while you are still next to them. If the
goal asks you to greet someone, ALWAYS fill both in the approach or follow decision.
You cannot climb stairs: pick people on your own floor, not on balconies or upper levels.
"look_around" turns until a person comes into view (fast); with an object as "target" it turns until
that object is in view. Use it whenever what you need is not visible.
Ignore mirror reflections, menus, thumbnails and HUD overlays: they cannot be walked to.
"gesture" shows a hand sign with your right hand (it stays until you pick another; "neutral" relaxes it).
"grab" walks to a small loose object and picks it up with the right hand; "drop" lets go.
While you hold something, the HUD on the right shows a "Drop (B)" prompt; a prompt with an
RT icon and a name means your crosshair is on something you can grab or use.
"crouch" toggles crouching.
Other players talk by typing: their words appear in a chat bubble above their head and nameplate.
Read every bubble you can see; a bubble stays up for a while after it is written, so answer each
one once. They also talk by voice: what you heard since your last decision is listed under
"Heard", written down by a speech model, so a word or name can come out wrong. Heard words count
like a bubble; the speaker is usually the person nearest you or facing you. Ignore song lyrics
and talk not meant for you. When someone asks you for something, answer in "reply" and take it
on as your errand; it is listed under "Errand" until it is done. Work on it over the next
decisions, starting right away (no need to walk over to them first). To bring someone an object:
"grab" it if you can see it, else "look_around" with the object as "target"; once you hold it,
"look_around" without a target to find the person again, then "give". If it cannot be done, tell
them with "say". Once you have looked all around twice without finding what the errand needs,
tell them you could not find it and give the errand up.
Set "errand_done" when the errand is finished or given up.
"give" walks to a person (target, target_xy, target_is_person true) and hands over what your
right hand holds; put what to say while handing it over in "say".
Prefer approaching people, then greeting them once you are close. Keep chat short and friendly."""

# Naming every box first, and saying where carryable things are, took the café checks from 8 to
# 12 right out of 12; before, standing menus on the counter were called menu boards (11-02).
CHECK = """A segmentation model searched one first-person VRChat frame for an object and marked
each match with a numbered box. Reply with a single JSON object only:
{"boxes": {"1": "<what box 1 holds, 2-5 words>", ...}, "pick": <number of the box around the object itself, or null>, "why": "<one short reason>"}
The object itself is a thing someone could carry: it stands or lies on a counter, table, shelf or
the floor, even in a small stand or frame. Pictures of it are not it: posters, menu boards and
signs on a wall, screens, decals, mirror reflections and HUD icons."""


GENERIC_PERSON = ["character", "person"]
MARK = (255, 0, 200)  # numbered boxes Muse Spark picks from
# How far (fraction of the frame) an object's box may sit from where it was pointed at or last
# seen. Live, right picks were within 0.07 of Muse Spark's point and moved at most 0.2 between
# frames; picking the nearest box anywhere jumped to a wall menu board 0.32 and 0.64 away (11-02).
OBJECT_NEAR = 0.25
# Told to Muse Spark under Body without the gamepad (--input osc), so it does not plan on hands.
NO_PAD = "no gamepad, so you cannot grab, give, drop, crouch or show hand signs"
# Told under Body while carrying: Muse Spark took the agent's own furry arm at the right edge
# of the view for the requester and twice tried to hand it the clipboard (demo1, 11-03).
HOLDING = ("while you hold something, your own right arm reaches into the view from the right: "
           "fur or a hand at the right edge is you, not another person")
# An object this many degrees below the view centre gets looked down at while walking up to it.
LOW_DEG = 10.0


def parse_xy(value) -> tuple[float, float] | None:
    """A [x, y] pair in 0-1000 frame coordinates, or None."""
    try:
        x, y = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    return (x, y) if 0 <= x <= 1000 and 0 <= y <= 1000 else None


def phrase_tails(target: str, shortest: int = 1) -> list[str]:
    """'green striped dinosaur' -> ['green striped dinosaur', 'striped dinosaur', 'dinosaur'],
    plus the first adjective with the noun ('green dinosaur'), which SAM often finds when longer
    phrases miss."""
    words = target.split()
    out = [" ".join(words[i:]) for i in range(len(words) - shortest + 1)]
    if len(words) >= 3:
        # After the contiguous tails, before the bare noun: "black menu stand" must try
        # "menu stand" before "black stand" (live 10-28: that matched only the stand's base).
        out.insert(len(out) - 1, f"{words[0]} {words[-1]}")
    return list(dict.fromkeys(out))


def numbered(frame: Image.Image, dets: list[Detection]) -> Image.Image:
    """A copy of the frame with each detection boxed and numbered from 1."""
    img = frame.convert("RGB")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(28)
    for i, det in enumerate(dets, 1):
        draw.rectangle([det.x1, det.y1, det.x2, det.y2], outline=MARK, width=4)
        tw = draw.textlength(str(i), font=font)
        tx, ty = min(det.x1, img.width - tw - 14), det.y1 - 34 if det.y1 >= 34 else det.y1 + 4
        draw.rectangle([tx, ty, tx + tw + 14, ty + 32], fill=MARK)
        draw.text((tx + 7, ty + 1), str(i), fill=(255, 255, 255), font=font)
    return img


@dataclass
class Memory:
    """A short rolling log of what the agent did, fed back into the next decision."""
    events: list[str] = field(default_factory=list)
    limit: int = 8

    def add(self, text: str) -> None:
        self.events.append(text)
        del self.events[: -self.limit]

    def prompt(self, goal: str, body: str | None = None, errand: str | None = None,
               heard: list[tuple[float, str]] | None = None) -> str:
        recent = "\n".join(f"- {e}" for e in self.events) or "- (nothing yet)"
        errand_line = f"Errand: {errand}\n" if errand else ""
        body_line = f"Body: {body}\n" if body else ""
        heard_lines = "".join(f'Heard {age:.0f} s ago: "{text}"\n' for age, text in heard or [])
        return f"Goal: {goal}\n{errand_line}{body_line}{heard_lines}Recent:\n{recent}\nWhat next?"


def stalled(seen: list[tuple[float, float]]) -> bool:
    """Three moves and the target neither shifted nor grew in view: the body is not moving.
    (11-02: walking straight at a menu kept its bearing within 1 degree while its box grew
    from 6% to 13% of the frame, and the old bearing-only check gave up.)"""
    if len(seen) < 4:
        return False
    bearings = [b for b, _ in seen[-4:]]
    first, last = seen[-4][1], seen[-1][1]
    return max(bearings) - min(bearings) < 1.0 and last < first * 1.1


def _key(text: str) -> str:
    return " ".join(text.lower().split())


def _said(words: str, voice: list[str] | None) -> bool:
    """Whether Muse Spark's copy of the words came from what was heard rather than a bubble
    (its copy can drop punctuation or join two utterances)."""
    def bare(t: str) -> str:
        return " ".join(re.sub(r"[^\w\s]", " ", t.lower()).split())
    w = bare(words)
    return bool(w) and any(v and (v in w or w in v) for v in map(bare, voice or []))


@dataclass
class Errands:
    """What someone asked for in chat, kept until it is done.

    A chat bubble stays up for a while, so the same words show up in several frames; each
    text is answered and starts an errand only once.
    """
    current: dict | None = None
    heard: set[str] = field(default_factory=set)

    def read(self, d: dict) -> tuple[bool, dict | None]:
        """Take in one decision. Returns (the bubble text is new, the errand it started)."""
        # A give finishes the errand itself, once the hand-over happened (Muse Spark marks it
        # done in the same decision that starts walking over).
        if d.get("errand_done") and d.get("intent") != "give":
            self.current = None
        words = str(d.get("heard") or "").strip()
        fresh = bool(words) and _key(words) not in self.heard
        if fresh:
            self.heard.add(_key(words))
        task = str(d.get("new_errand") or "").strip()
        if not task or (words and not fresh):
            return fresh, None
        if not words:  # an errand Muse Spark inferred without a bubble: once per task
            if _key(task) in self.heard:
                return fresh, None
            self.heard.add(_key(task))
        self.current = {"task": task, "for": str(d.get("requester") or "the person who asked"),
                        "heard": words or None}
        if words and _said(words, d.get("voice")):
            self.current["spoken"] = True
        return fresh, self.current

    def done(self) -> None:
        self.current = None

    def describe(self) -> str | None:
        if not self.current:
            return None
        e = self.current
        how = "said" if e.get("spoken") else "wrote"
        asked = f", who {how} {e['heard']!r}" if e.get("heard") else ""
        missed = f"; looked all around {e['missed']} time(s) without finding it" if e.get("missed") else ""
        return f"{e['task']} (asked by {e['for']}{asked}){missed}"


class Agent:
    def __init__(self, settings: Settings, goal: str, dry_run: bool = False, log_dir: Path | None = None,
                 locomotion: str = "pad", hear: bool = True):
        self.api = MetaClient(settings)
        self.dry_run = dry_run
        self.cam = Camera()
        self.body = Body(settings.osc_host, settings.osc_port, dry_run=dry_run, locomotion=locomotion)
        try:
            self.senses: Senses | None = Senses(settings.osc_host, settings.osc_in_port,
                                                own=frozenset({THINKING_PARAM})).start()
        except OSError as e:  # port taken by another OSC app
            print(f"[senses] OSC output not available on {settings.osc_in_port}: {e}")
            self.senses = None
        # Voices around the avatar, as VRChat plays them, written down by Muse Voice Transcribe.
        self.ears: Ears | None = Ears(settings).start() if hear else None
        self.steer_params = SteerParams(fov_v_deg=settings.fov_v_deg)
        self.goal = goal
        self.memory = Memory()
        self.errands = Errands()
        # Seconds the held object is offered before it is let go in front of the person.
        self.handover_seconds = 2.5
        # While carrying: where the held object and our own reaching arm sit on screen.
        self.holding = False
        self.held_box: Detection | None = None
        self.own_boxes: list[Detection] = []
        # The phrase SAM found the object with in the last object scan, a fallback for grounding it.
        self.found_phrase: str | None = None
        # When the last approach arrived: the phrase it tracked the target with, and where the
        # target is now (0-1000 frame coordinates).
        self.tracked: tuple[str, tuple[float, float]] | None = None
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.people: list[Detection] = []
        self.follow_seconds = 20.0
        # Where the last tracked target was (bearing, time), so a search turns toward it.
        self.last_seen: tuple[float, float] | None = None
        self.log_dir = log_dir
        self.step = 0
        self.frame_no = 0
        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "run.json").write_text(json.dumps({"goal": goal, "start": time.time()}), encoding="utf-8")

    def log(self, frame: Image.Image, record: dict) -> None:
        """Every frame the agent acted on, with what it decided or tracked (for replay videos)."""
        if not self.log_dir:
            return
        self.frame_no += 1
        name = f"{self.frame_no:05d}.jpg"
        frame.save(self.log_dir / name, quality=80)
        with open(self.log_dir / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"step": self.step, "frame": name, "t": time.time(), **record}) + "\n")

    def act(self, text: str) -> None:
        """Remember an action and log it (no frame) for the replay."""
        self.memory.add(text)
        if self.log_dir:
            with open(self.log_dir / "events.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"step": self.step, "t": time.time(), "phase": "act", "act": text}) + "\n")

    def can(self, what: str) -> bool:
        """Whether the body has the buttons to grab, hand over, drop, crouch or show a hand sign.
        Without the gamepad (--input osc) the action is skipped and remembered instead."""
        if self.body.has_pad:
            return True
        self.memory.add(f"could not {what}: no gamepad (--input osc)")
        return False

    def decide(self, frame: Image.Image) -> dict:
        body = None
        if self.senses:
            for event in self.senses.take_events():
                self.memory.add(f"felt: {event}")
            body = self.senses.summary()
        notes = [body, None if self.body.has_pad else NO_PAD, HOLDING if self.holding else None]
        body = "; ".join(n for n in notes if n) or None
        heard = self.ears.take() if self.ears else []
        now = time.time()
        prompt = self.memory.prompt(self.goal, body, self.errands.describe(),
                                    heard=[(now - h.t, h.text) for h in heard])
        for h in heard:  # later decisions see it under Recent
            self.memory.add(f"heard someone say {h.text!r}")
        # The people detector runs while Muse Spark thinks, so it costs no extra time.
        people = self.pool.submit(self.find_people, frame)
        # The ~5 s decision is visible in-world: Thinking on the avatar, typing dots in chat.
        self.body.thinking(True)
        try:
            reply = self.api.see(frame, SYSTEM, prompt)
        finally:
            self.body.thinking(False)
        try:
            d = extract_json(reply)
        except ValueError:
            d = {"intent": "wait", "why": "unparseable reply", "raw": reply[:300]}
        self.people = people.result()
        d["people"] = [[p.x1, p.y1, p.x2, p.y2] for p in self.people]
        if self.ears:
            d["voice"] = [h.text for h in heard]  # for the errand and the replay
        if d.get("mood"):
            self.body.mood(str(d["mood"]))
        self.read_chat(d)
        return d

    def read_chat(self, d: dict) -> None:
        """Answer new chat bubbles right away and turn requests into the errand."""
        had = self.errands.current
        fresh, errand = self.errands.read(d)
        if had and self.errands.current is not had:
            self.act(f"errand {'replaced' if errand else 'finished'}: {had['task']}")
        if errand:
            self.act(f"{errand['for']} asked: {errand['task']}")
        if fresh and d.get("reply"):
            self.body.say(str(d["reply"]))
            self.act(f"replied {d['reply']!r}")
        d["errand"] = self.errands.current  # for the replay

    def find_people(self, frame: Image.Image) -> list[Detection]:
        """Every avatar in view. Descriptive phrases miss stylised avatars ("cat girl",
        "blonde girl" found nothing on 10-28) while "character" found both NPCs."""
        try:
            return [d for d in self.api.segment(frame, "character")
                    if (d.conf or 0) >= 0.4 and not self.is_own(d)]
        except Exception as e:  # a failed side sense must not stop the decision
            print(f"[people] {e}")
            return []

    def is_own(self, det: Detection) -> bool:
        """Part of our own arm, or of the object in our hand: while carrying they stay at the
        same place on screen (11-02: SAM 'character' matched the avatar's own furry arm, and
        a cartoon printed on the held menu)."""
        if not self.holding:
            return False
        if any(iou(det, own) >= 0.5 for own in self.own_boxes):
            return True
        if self.held_box is not None and covered(det, self.held_box) >= 0.8:
            return True
        # The right hand holds it, so our own arm reaches in from the lower right corner.
        if det.x2 >= det.frame_w - 2 and det.y2 >= det.frame_h - 2 and det.height_frac >= 0.5:
            self.own_boxes.append(det)
            return True
        return False

    def note_held(self, target: str) -> None:
        """Right after a grab, find where the held object sits on screen."""
        self.holding, self.own_boxes, self.found_phrase = True, [], None
        frame = self.cam.grab()
        self.held_box = None
        for phrase in dict.fromkeys([target, target.split()[-1]]):
            self.held_box = pick([x for x in self.api.segment(frame, phrase) if (x.conf or 0) >= 0.5],
                                 hint=(500.0, 500.0))
            if self.held_box is not None:
                break
        h = self.held_box
        self.log(frame, {"phase": "holding", "target": target,
                         **({"box": [h.x1, h.y1, h.x2, h.y2]} if h else {})})

    def let_go(self) -> None:
        self.body.drop()
        self.holding, self.held_box, self.own_boxes = False, None, []

    def beside_held_deg(self) -> float:
        """Bearing that keeps a person just left of what we carry: the object floats in the
        middle of the view and the right arm holding it fills the right side."""
        if not self.holding:
            return 0.0
        h = self.held_box
        if h is None:
            return -25.0
        x = max(h.x1 - 0.06 * h.frame_w, 0.1 * h.frame_w)
        return x_bearing(x, self.steer_params.fov_v_deg, h.frame_w, h.frame_h)

    def snap_to_person(self, hint: tuple[float, float] | None) -> tuple[float, float] | None:
        """Move the VLM's rough point onto the nearest detected person."""
        det = pick(self.people, hint=hint) if self.people else None
        if det is None:
            return hint
        return (1000 * det.center[0] / det.frame_w, 1000 * det.center[1] / det.frame_h)

    def ground(self, frame: Image.Image, target: str, hint: tuple[float, float] | None,
               person: bool = False, near: float | None = None):
        """SAM on the phrase, then on shorter tails of it: long phrases lose recall
        ("green striped dinosaur" found nothing where "green dinosaur" did).

        People go the other way round: the generic words first, kept on the right avatar by
        the hint, then the full description. Tails of a person's description are body parts
        (10-29: "girl with tail" -> "tail" locked onto a tail tip and a fish decal on the
        wall, "girl with yellow bow" onto her hair bow).

        With `near`, a box further than that from the hint does not count (see OBJECT_NEAR).

        If the last object scan found the object with a phrase that shares a word with the
        target, that phrase goes first, and only tails that keep the shared word follow: the
        others name something else (11-02: "colorful pen display" -> "display" was the
        whiteboard above the pens, "black menu stand" -> "black stand" a small black box). If
        nothing is found, SAM proposes with that phrase and Muse Spark picks, as in the scan
        (11-02: SAM found nothing for Muse Spark's "black menu stand", twice; the scan's own
        phrase also matched the menu boards on the wall)."""
        phrases = GENERIC_PERSON + [target] if person else phrase_tails(target)
        shared = set(self.found_phrase.split()) & set(target.split()) if self.found_phrase else set()
        scanned = not person and bool(shared)
        if scanned:
            phrases = list(dict.fromkeys([self.found_phrase] + [p for p in phrases if shared & set(p.split())]))
        for phrase in phrases:
            dets = self.api.segment(frame, phrase)
            if person:
                dets = [x for x in dets if not self.is_own(x)]
            det = pick(dets, hint=hint, near=near)
            if det is not None:
                # Stick with a phrase that worked unless it was a generic fallback.
                return det, target if phrase in GENERIC_PERSON else phrase
        if scanned:
            det, phrase, check = self.find_object(frame, self.found_phrase)
            self.log(frame, {"phase": "check", "target": target, **check,
                             **({"box": [det.x1, det.y1, det.x2, det.y2], "conf": det.conf} if det else {})})
            if det is not None:
                return det, phrase
        return None, target

    def aim(self, target: str, hint: tuple[float, float] | None, tries: int = 2):
        """Put the target under the screen-centre crosshair (desktop interaction ray)."""
        det = None
        for _ in range(tries):
            frame = self.cam.grab()
            det, target = self.ground(frame, target, hint)
            if det is None:
                return None
            b = bearing_deg(det, self.steer_params.fov_v_deg)
            e = elevation_deg(det, self.steer_params.fov_v_deg)
            self.log(frame, {"phase": "aim", "target": target, "box": [det.x1, det.y1, det.x2, det.y2],
                             "bearing": round(b, 1), "elevation": round(e, 1)})
            if abs(b) < 2.0 and abs(e) < 2.0:
                break
            self.body.turn_by(b)
            self.body.look_by(e)
            hint = (500.0, 500.0)
            time.sleep(0.2)
        return det

    def grab(self, target: str, hint: tuple[float, float] | None) -> None:
        if not self.can(f"pick up {target!r}"):
            return
        # Small objects never fill half the view; ~22% of the frame height is within reach
        # (cafe menu picked up at 27%, 10-28).
        if not self.approach(target, hint=hint, arrive_height=0.22):
            self.body.level()
            return
        # Aim with the phrase that found it on the way, starting where it is now (11-02:
        # re-grounding Muse Spark's "black menu stand" matched "black stand" on a small black
        # box 30 degrees off; and the screen centre is nearer a menu further back on the
        # counter than the one right in front, which sits low in the view).
        target, start = self.tracked or (target, (500.0, 500.0))
        det = self.aim(target, hint=start)
        if det is None:
            self.memory.add(f"lost {target!r} while aiming")
        else:
            self.body.interact()
            self.act(f"pressed grab on {target!r} (check the hand and the HUD 'Drop' prompt)")
        time.sleep(0.5)
        self.body.level()
        if det is not None:
            self.note_held(target)

    def give(self, target: str, hint: tuple[float, float] | None, d: dict) -> None:
        """Walk to a person and hand over what the right hand holds."""
        if not self.can(f"hand anything to {target}"):
            return
        if not self.people:
            # Only our own arm in view (demo1, 11-03: two approaches to the fur at the right edge
            # found nobody). Find them first; the next decision hands it over.
            self.memory.add(f"looked around for {target}: no one was in view to hand it to")
            self.scan()
            return

        def hand_over() -> None:
            line = str(d.get("say") or "Here you go!")
            self.body.say(line)
            self.act(f"said {line!r}")
            # They can take it out of the hand meanwhile; otherwise it is let go in front of them.
            time.sleep(self.handover_seconds)
            self.let_go()
            self.act(f"handed what I held to {target}")
            if self.errands.current:
                self.act(f"errand finished: {self.errands.current['task']}")
                self.errands.done()

        # Walk up with them beside the held object, not behind it, then face them on arrival
        # so the object ends up between us (11-02: the menu hid the requester).
        if not self.approach(target, hint=hint, person=True, on_arrive=hand_over,
                             offset_deg=self.beside_held_deg()):
            self.memory.add(f"did not reach {target} to hand it over (still holding it)")

    def approach(self, target: str, hint: tuple[float, float] | None = None, max_steps: int = 12,
                 arrive_height: float | None = None, person: bool = False, follow_seconds: float = 0.0,
                 on_arrive=None, offset_deg: float = 0.0) -> bool:
        """Closed loop on SAM boxes until the target fills enough of the view.

        With follow_seconds, keep going after arriving: stay close to a person who walks
        around and keep facing them, until the time is up or they are lost. offset_deg keeps
        the target at that bearing while walking up (see steer).
        """
        seen: list[tuple[float, float]] = []  # (bearing, box height) per frame
        misses = 0
        reached = False
        self.tracked = None
        start = time.time()
        i = 0
        while i < max_steps or (follow_seconds and time.time() - start < follow_seconds):
            i += 1
            frame = self.cam.grab()
            det, phrase = self.ground(frame, target, hint, person=person,
                                      near=None if person or hint is None else OBJECT_NEAR)
            if det is None:
                misses += 1
                self.log(frame, {"phase": "approach", "target": target, "found": False})
                self.body.stop()
                # A walking person can be hidden for a frame (furniture, another avatar).
                if person and misses <= 1:
                    continue
                if i == 1:
                    self.memory.add(f"segmentation found no {target!r} in view")
                else:
                    side = f", last seen {self.describe_last_seen()}" if self.last_seen else ""
                    self.memory.add(f"lost sight of {target!r}{side}")
                return reached
            misses = 0
            # Follow the box we chose, and the phrase that found it.
            hint = (1000 * det.center[0] / det.frame_w, 1000 * det.center[1] / det.frame_h)
            target = phrase
            if arrive_height is None and person:
                # People: 40% of the frame height is conversation distance; 55% was never
                # reached on the NPC world (closest 43%) and means bumping into them.
                arrive_height = 0.40
            cmd = steer(det, self.steer_params, arrive_height, offset_deg)
            seen.append((cmd.bearing_deg, det.height_frac))
            self.last_seen = (cmd.bearing_deg, time.time())
            self.log(frame, {"phase": "follow" if follow_seconds else "approach", "target": target,
                             "box": [det.x1, det.y1, det.x2, det.y2], "conf": det.conf,
                             "bearing": round(cmd.bearing_deg, 1), "arrived": cmd.arrived,
                             **({"offset": round(offset_deg, 1)} if offset_deg else {}),
                             **({"own": [[o.x1, o.y1, o.x2, o.y2] for o in self.own_boxes]}
                                if self.own_boxes else {})})
            if not person and not cmd.arrived and stalled(seen):
                # (Skipped for people: a person walking with us also keeps a steady view.)
                self.memory.add(f"moving toward {target!r} did not change the view (stuck?)")
                self.body.stop()
                return False
            if cmd.arrived and not reached:
                reached = True
                self.memory.add(f"reached {target}")
                self.body.stop()
                self.body.turn_by(cmd.turn_deg)  # face them before greeting
                hint = self.after_turn(det, cmd.turn_deg)
                self.tracked = (target, hint)
                if not follow_seconds:
                    if on_arrive:
                        on_arrive()
                    return True
                continue
            look = 0.0
            if not person and elevation_deg(det, self.steer_params.fov_v_deg) < -LOW_DEG:
                # Look down at a low object so it stays in view on the way (11-02: pens in a
                # tray under a whiteboard sank out of the bottom of the level view, twice).
                # Whoever started the approach levels the view again.
                look = 0.9 * elevation_deg(det, self.steer_params.fov_v_deg)
                self.body.look_by(look)
            self.body.turn_by(cmd.turn_deg)
            hint = self.after_turn(det, cmd.turn_deg, look)
            if cmd.walk and not cmd.arrived:
                self.body.walk(0.6)
        if follow_seconds:
            self.memory.add(f"followed {target} for {time.time() - start:.0f} s")
            # Still next to them: greet now, at the end of following.
            if reached and on_arrive:
                on_arrive()
            return reached
        self.memory.add(f"gave up approaching {target}")
        return False

    def after_turn(self, det: Detection, turn: float, look: float = 0.0) -> tuple[float, float]:
        """Where the tracked box should show (0-1000) once the body turned by `turn` degrees
        and the view pitched by `look`. (11-02: after a 36 degree turn the hint still pointed
        at the old spot.)"""
        fov = self.steer_params.fov_v_deg
        x = screen_x(bearing_deg(det, fov) - turn, fov, det.frame_w, det.frame_h)
        y = screen_y(elevation_deg(det, fov) - look, fov, det.frame_h)
        return (min(max(1000 * x / det.frame_w, 0.0), 1000.0), min(max(1000 * y / det.frame_h, 0.0), 1000.0))

    def describe_last_seen(self) -> str:
        b, t = self.last_seen
        return f"{abs(b):.0f} deg to the {'right' if b > 0 else 'left'} {time.time() - t:.0f} s ago"

    def search_turn(self) -> float:
        """Turn toward where the last target went if it was recent, else sweep right."""
        if self.last_seen and time.time() - self.last_seen[1] < 30.0:
            b = self.last_seen[0]
            # Past the edge where it left: half a field of view beyond the last bearing.
            turn = math.copysign(min(90.0, abs(b) + 45.0), b)
            self.last_seen = (0.0, self.last_seen[1])  # facing that way now
            return turn
        return 60.0

    def scan(self, step_deg: float = 45.0, target: str | None = None) -> None:
        """Turn in steps, running only SAM (~1 s) at each, and stop as soon as a person, or
        the target object, is in view; the next decision then sees it. A VLM decision per
        60 degree turn took ~5 s each (10-28). Muse Spark is asked only when SAM matches the
        object, to tell it from pictures of it, and the scan then turns to face it."""
        first = self.search_turn() if target is None else step_deg
        if target is None and self.holding:
            # While carrying, the held object and our own arm cover the middle and the right of
            # the view, and only ~37 degrees on the left stay clear. Steps of 45 (and a first
            # turn of 50) moved the requester from the left edge straight behind the clipboard,
            # and the scan saw nobody (demo1 step 5, 11-03). At 30, everyone passes the clear part.
            step_deg = min(step_deg, 30.0)
            first = math.copysign(step_deg, first)
        direction = math.copysign(1.0, first)
        turned = 0.0
        ruled_out = 0
        turns = [first] + [direction * step_deg] * int((360 - abs(first)) // step_deg)
        for turn in turns:
            self.body.turn_by(turn)
            turned += turn
            time.sleep(0.15)
            frame = self.cam.grab()
            side = f"{abs(turned):.0f} degrees {'right' if turned > 0 else 'left'}"
            if target is None:
                people = [p for p in self.find_people(frame) if (p.conf or 0) >= 0.5]
                self.log(frame, {"phase": "scan", "turned": round(turned),
                                 "people": [[p.x1, p.y1, p.x2, p.y2] for p in people]})
                if people:
                    self.memory.add(f"scanned {side} and now see {len(people)} person(s)")
                    return
                continue
            det, phrase, check = self.find_object(frame, target)
            self.log(frame, {"phase": "scan", "turned": round(turned), "target": target, **check,
                             **({"box": [det.x1, det.y1, det.x2, det.y2], "conf": det.conf} if det else {})})
            if det is None:
                ruled_out += len(check.get("candidates", []))
                continue
            # Face it, so the next decision sees it whole and in the middle of the view.
            self.body.turn_by(bearing_deg(det, self.steer_params.fov_v_deg))
            self.found_phrase = phrase
            self.memory.add(f"scanned {side} and now face {target!r}")
            return
        if target is None:
            self.memory.add("scanned a full circle and saw nobody")
            return
        others = f" ({ruled_out} pictures or look-alikes ruled out)" if ruled_out else ""
        self.memory.add(f"scanned a full circle and did not find {target!r}{others}")
        if self.errands.current:  # counted for the Errand line (11-02: seven circles for a pen)
            self.errands.current["missed"] = self.errands.current.get("missed", 0) + 1

    def find_object(self, frame: Image.Image, target: str) -> tuple[Detection | None, str, dict]:
        """SAM 3.1 proposes, Muse Spark picks. Every match of the phrase and of its bare noun
        ('printed menu' -> 'menu') is numbered on the frame, and Muse Spark says which box is the
        object itself (11-02: 'printed menu' matched only the menu board on the wall; 'menu' also
        found the clipboard menu on the counter below it). Returns the object, the phrase that
        found it, and what to log."""
        phrases = list(dict.fromkeys([target, target.split()[-1]]))
        cands: list[tuple[Detection, str]] = []
        for phrase, dets in self.pool.map(lambda p: (p, self.api.segment(frame, p)), phrases):
            for det in sorted(dets, key=lambda x: -(x.conf or 0)):
                if (det.conf or 0) >= 0.4 and all(iou(det, c) < 0.5 for c, _ in cands):
                    cands.append((det, phrase))
        cands = cands[:6]
        if not cands:
            return None, target, {}
        record: dict = {"candidates": [[c.x1, c.y1, c.x2, c.y2] for c, _ in cands]}
        try:
            d = extract_json(self.api.see(numbered(frame, [c for c, _ in cands]), CHECK,
                                          f"Looking for: {target}"))
        except Exception as e:  # without the check, trust SAM's most confident match
            print(f"[check] {e}")
            d = {"pick": 1 + max(range(len(cands)), key=lambda i: cands[i][0].conf or 0),
                 "why": "not checked"}
        try:
            n = int(d.get("pick"))
        except (TypeError, ValueError):  # null: none of them
            n = None
        n = n if n is not None and 1 <= n <= len(cands) else None
        record.update(pick=n, check=str(d.get("why") or ""))
        if isinstance(d.get("boxes"), dict):  # what Muse Spark took each box for
            record["labels"] = [str(d["boxes"].get(str(i), "")) for i in range(1, len(cands) + 1)]
        if n is None:
            return None, target, record
        det, phrase = cands[n - 1]
        return det, phrase, record

    def greet(self, d: dict) -> None:
        """Say and gesture what the decision planned for arrival."""
        if d.get("say"):
            self.body.say(str(d["say"]))
            self.act(f"said {d['say']!r}")
        if d.get("gesture") in GESTURES:
            self.sign(str(d["gesture"]))

    def sign(self, name: str) -> None:
        """Show a hand sign with the right hand; it stays until the next one."""
        if self.can(f"show {name}"):
            self.body.gesture(name)
            self.act(f"right hand now shows {name}")

    def wait_for_focus(self, timeout: float = 120.0) -> None:
        """VRChat ignores the gamepad while its window is not focused (11-02: the first six
        steps of a run turned nothing), so wait for focus instead of acting blind."""
        if self.dry_run or is_foreground() is not False:
            return
        print(f"[{self.step}] waiting for the VRChat window to be focused (controller input is ignored)")
        self.body.stop()
        deadline = time.time() + timeout
        while is_foreground() is False and time.time() < deadline:
            time.sleep(0.5)

    def tick(self) -> None:
        self.step += 1
        self.wait_for_focus()
        if self.ears:  # someone is mid-sentence: let them finish before looking and deciding
            self.ears.wait_until_quiet()
        frame = self.cam.grab()
        d = self.decide(frame)
        self.log(frame, {"phase": "decide", **d})
        intent = d.get("intent")
        print(f"[{self.step}] {intent}: {d.get('observation')} ({d.get('why')})")
        person = bool(d.get("target_is_person")) or intent == "give"
        hint = parse_xy(d.get("target_xy"))
        if person:
            hint = self.snap_to_person(hint)
        if intent in ("approach", "follow") and d.get("target"):
            # Greet inside the tracking loop (on arrival, or at the end of following),
            # not a decision later (10-28: the NPC had walked out of view by then).
            self.approach(str(d["target"]), hint=hint, person=person,
                          follow_seconds=self.follow_seconds if intent == "follow" else 0.0,
                          on_arrive=lambda: self.greet(d))
            self.body.level()
        elif intent == "look_around":
            self.scan(target=str(d["target"]) if d.get("target") and not person else None)
        elif intent == "wave":
            if d.get("say"):
                self.body.say(str(d["say"]))
            self.body.emote(1)
            self.act(f"waved{' and said ' + repr(d['say']) if d.get('say') else ''}")
            if d.get("gesture") in GESTURES:
                self.sign(str(d["gesture"]))
        elif intent == "say" and d.get("say"):
            self.body.say(str(d["say"]))
            self.act(f"said {d['say']!r}")
        elif intent == "gesture" and d.get("gesture") in GESTURES:
            self.sign(str(d["gesture"]))
        elif intent == "grab" and d.get("target"):
            self.grab(str(d["target"]), hint)
        elif intent == "give" and d.get("target"):
            self.give(str(d["target"]), hint, d)
        elif intent == "drop":
            if self.can("let go"):
                self.let_go()
                self.act("dropped what was in the right hand")
        elif intent == "crouch":
            if self.can("crouch"):
                self.body.crouch_toggle()
                self.act("toggled crouch")
        else:
            self.memory.add("waited")
            time.sleep(1.0)

    def run(self, steps: int) -> None:
        try:
            for _ in range(steps):
                self.tick()
        finally:
            self.pool.shutdown(wait=False)
            self.body.close()
            if self.senses:
                self.senses.close()
            if self.ears:
                self.ears.close()
            self.api.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the Muse body agent against a VRChat desktop window.")
    ap.add_argument("--goal", default="Find someone nearby, walk up to them and greet them.")
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true", help="print controller/OSC output instead of sending it")
    ap.add_argument("--input", choices=["pad", "osc"], default="pad",
                    help="locomotion via a virtual Xbox pad (default) or VRChat's OSC /input axes "
                         "(osc: no grabbing, crouching or hand signs)")
    ap.add_argument("--no-hear", action="store_true",
                    help="do not listen to voices (Muse Voice Transcribe on the PC's audio output)")
    ap.add_argument("--log-dir", type=Path, default=Path("runs") / time.strftime("%Y%m%d-%H%M%S"))
    args = ap.parse_args()
    Agent(Settings.from_env(), args.goal, dry_run=args.dry_run, log_dir=args.log_dir,
          locomotion=args.input, hear=not args.no_hear).run(args.steps)


if __name__ == "__main__":
    main()
