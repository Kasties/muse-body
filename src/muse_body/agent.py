"""The loop: see (Muse Spark) -> ground (SAM 3.1) -> move (OSC) -> repeat."""

from __future__ import annotations

import argparse
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from .body import GESTURES, Body
from .capture import Camera, is_foreground
from .config import Settings
from .meta_api import MetaClient, extract_json
from .sam_format import Detection
from .senses import Senses
from .steer import SteerParams, bearing_deg, elevation_deg, pick, steer

SYSTEM = """You are the mind of an avatar in VRChat. You see one first-person frame at a time.
Choose ONE next intention. Reply with a single JSON object only:
{
  "observation": "<one sentence: what you see>",
  "heard": "<the words in a chat bubble above another avatar's head, copied exactly, else null>",
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
  "why": "<one short reason>"
}
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
Read every bubble you can see. When someone asks you for something, answer in "reply" and take it
on as your errand; it is listed under "Errand" until it is done. Work on it over the next
decisions, starting right away (no need to walk over to them first). To bring someone an object:
"grab" it if you can see it, else "look_around" with the object as "target"; once you hold it,
"look_around" without a target to find the person again, then "give". If it cannot be done, tell
them with "say".
Set "errand_done" when the errand is finished or given up.
"give" walks to a person (target, target_xy, target_is_person true) and hands over what your
right hand holds; put what to say while handing it over in "say".
Prefer approaching people, then greeting them once you are close. Keep chat short and friendly."""


GENERIC_PERSON = ["character", "person"]


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


@dataclass
class Memory:
    """A short rolling log of what the agent did, fed back into the next decision."""
    events: list[str] = field(default_factory=list)
    limit: int = 8

    def add(self, text: str) -> None:
        self.events.append(text)
        del self.events[: -self.limit]

    def prompt(self, goal: str, body: str | None = None, errand: str | None = None) -> str:
        recent = "\n".join(f"- {e}" for e in self.events) or "- (nothing yet)"
        errand_line = f"Errand: {errand}\n" if errand else ""
        body_line = f"Body: {body}\n" if body else ""
        return f"Goal: {goal}\n{errand_line}{body_line}Recent:\n{recent}\nWhat next?"


def _key(text: str) -> str:
    return " ".join(text.lower().split())


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
        return fresh, self.current

    def done(self) -> None:
        self.current = None

    def describe(self) -> str | None:
        if not self.current:
            return None
        e = self.current
        asked = f", who wrote {e['heard']!r}" if e.get("heard") else ""
        return f"{e['task']} (asked by {e['for']}{asked})"


class Agent:
    def __init__(self, settings: Settings, goal: str, dry_run: bool = False, log_dir: Path | None = None,
                 locomotion: str = "pad"):
        self.api = MetaClient(settings)
        self.cam = Camera()
        self.body = Body(settings.osc_host, settings.osc_port, dry_run=dry_run, locomotion=locomotion)
        try:
            self.senses: Senses | None = Senses(settings.osc_host, settings.osc_in_port).start()
        except OSError as e:  # port taken by another OSC app
            print(f"[senses] OSC output not available on {settings.osc_in_port}: {e}")
            self.senses = None
        self.steer_params = SteerParams(fov_v_deg=settings.fov_v_deg)
        self.goal = goal
        self.memory = Memory()
        self.errands = Errands()
        # Seconds the held object is offered before it is dropped at the person's feet.
        self.handover_seconds = 2.5
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

    def decide(self, frame: Image.Image) -> dict:
        body = None
        if self.senses:
            for event in self.senses.take_events():
                self.memory.add(f"felt: {event}")
            body = self.senses.summary()
        # The people detector runs while Muse Spark thinks, so it costs no extra time.
        people = self.pool.submit(self.find_people, frame)
        reply = self.api.see(frame, SYSTEM, self.memory.prompt(self.goal, body, self.errands.describe()))
        try:
            d = extract_json(reply)
        except ValueError:
            d = {"intent": "wait", "why": "unparseable reply", "raw": reply[:300]}
        self.people = people.result()
        d["people"] = [[p.x1, p.y1, p.x2, p.y2] for p in self.people]
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
            return [d for d in self.api.segment(frame, "character") if (d.conf or 0) >= 0.4]
        except Exception as e:  # a failed side sense must not stop the decision
            print(f"[people] {e}")
            return []

    def snap_to_person(self, hint: tuple[float, float] | None) -> tuple[float, float] | None:
        """Move the VLM's rough point onto the nearest detected person."""
        det = pick(self.people, hint=hint) if self.people else None
        if det is None:
            return hint
        return (1000 * det.center[0] / det.frame_w, 1000 * det.center[1] / det.frame_h)

    def ground(self, frame: Image.Image, target: str, hint: tuple[float, float] | None,
               person: bool = False):
        """SAM on the phrase, then on shorter tails of it: long phrases lose recall
        ("green striped dinosaur" found nothing where "green dinosaur" did).

        People go the other way round: the generic words first, kept on the right avatar by
        the hint, then the full description. Tails of a person's description are body parts
        (10-29: "girl with tail" -> "tail" locked onto a tail tip and a fish decal on the
        wall, "girl with yellow bow" onto her hair bow)."""
        phrases = GENERIC_PERSON + [target] if person else phrase_tails(target)
        for phrase in phrases:
            det = pick(self.api.segment(frame, phrase), hint=hint)
            if det is not None:
                # Stick with a phrase that worked unless it was a generic fallback.
                return det, target if phrase in GENERIC_PERSON else phrase
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
        # Small objects never fill half the view; ~22% of the frame height is within reach
        # (cafe menu picked up at 27%, 10-28).
        if not self.approach(target, hint=hint, arrive_height=0.22):
            return
        det = self.aim(target, hint=(500.0, 500.0))
        if det is None:
            self.memory.add(f"lost {target!r} while aiming")
        else:
            self.body.interact()
            self.act(f"pressed grab on {target!r} (check the hand and the HUD 'Drop' prompt)")
        time.sleep(0.5)
        self.body.level()

    def give(self, target: str, hint: tuple[float, float] | None, d: dict) -> None:
        """Walk to a person and hand over what the right hand holds."""
        def hand_over() -> None:
            line = str(d.get("say") or "Here you go!")
            self.body.say(line)
            self.act(f"said {line!r}")
            # They can take it out of the hand meanwhile; otherwise it drops in front of them.
            time.sleep(self.handover_seconds)
            self.body.drop()
            self.act(f"handed what I held to {target}")
            if self.errands.current:
                self.act(f"errand finished: {self.errands.current['task']}")
                self.errands.done()

        if not self.approach(target, hint=hint, person=True, on_arrive=hand_over):
            self.memory.add(f"did not reach {target} to hand it over (still holding it)")

    def approach(self, target: str, hint: tuple[float, float] | None = None, max_steps: int = 12,
                 arrive_height: float | None = None, person: bool = False, follow_seconds: float = 0.0,
                 on_arrive=None) -> bool:
        """Closed loop on SAM boxes until the target fills enough of the view.

        With follow_seconds, keep going after arriving: stay close to a person who walks
        around and keep facing them, until the time is up or they are lost.
        """
        bearings: list[float] = []
        misses = 0
        reached = False
        start = time.time()
        i = 0
        while i < max_steps or (follow_seconds and time.time() - start < follow_seconds):
            i += 1
            frame = self.cam.grab()
            det, phrase = self.ground(frame, target, hint, person=person)
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
            cmd = steer(det, self.steer_params, arrive_height)
            bearings.append(cmd.bearing_deg)
            self.last_seen = (cmd.bearing_deg, time.time())
            self.log(frame, {"phase": "follow" if follow_seconds else "approach", "target": target,
                             "box": [det.x1, det.y1, det.x2, det.y2], "conf": det.conf,
                             "bearing": round(cmd.bearing_deg, 1), "arrived": cmd.arrived})
            if (not person and len(bearings) >= 4 and max(bearings[-4:]) - min(bearings[-4:]) < 1.0
                    and not cmd.arrived):
                # Three moves and the target has not shifted in view: the body is not moving.
                # (Skipped for people: a person walking with us also keeps a steady bearing.)
                self.memory.add(f"moving toward {target!r} did not change the view (stuck?)")
                self.body.stop()
                return False
            if cmd.arrived and not reached:
                reached = True
                self.memory.add(f"reached {target}")
                self.body.stop()
                self.body.turn_by(cmd.turn_deg)  # face them before greeting
                if not follow_seconds:
                    if on_arrive:
                        on_arrive()
                    return True
                continue
            self.body.turn_by(cmd.turn_deg)
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
        60 degree turn took ~5 s each (10-28)."""
        first = self.search_turn() if target is None else step_deg
        direction = math.copysign(1.0, first)
        turned = 0.0
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
            det = self.find_object(frame, target)
            self.log(frame, {"phase": "scan", "turned": round(turned), "target": target,
                             **({"box": [det.x1, det.y1, det.x2, det.y2], "conf": det.conf} if det else {})})
            if det is not None:
                self.memory.add(f"scanned {side} and now see {target!r}")
                return
        self.memory.add("scanned a full circle and saw nobody" if target is None
                        else f"scanned a full circle and did not find {target!r}")

    def find_object(self, frame: Image.Image, target: str) -> Detection | None:
        """The target phrase, then its bare noun ('cafe menu' -> 'menu')."""
        for phrase in dict.fromkeys([target, target.split()[-1]]):
            det = pick([x for x in self.api.segment(frame, phrase) if (x.conf or 0) >= 0.5])
            if det is not None:
                return det
        return None

    def greet(self, d: dict) -> None:
        """Say and gesture what the decision planned for arrival."""
        if d.get("say"):
            self.body.say(str(d["say"]))
            self.act(f"said {d['say']!r}")
        if d.get("gesture") in GESTURES:
            self.body.gesture(str(d["gesture"]))
            self.act(f"right hand now shows {d['gesture']}")

    def tick(self) -> None:
        self.step += 1
        if is_foreground() is False:
            print(f"[{self.step}] warning: VRChat is not the focused window; controller input will be ignored")
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
        elif intent == "look_around":
            self.scan(target=str(d["target"]) if d.get("target") and not person else None)
        elif intent == "wave":
            if d.get("say"):
                self.body.say(str(d["say"]))
            self.body.emote(1)
            self.act(f"waved{' and said ' + repr(d['say']) if d.get('say') else ''}")
            if d.get("gesture") in GESTURES:
                self.body.gesture(str(d["gesture"]))
                self.act(f"right hand now shows {d['gesture']}")
        elif intent == "say" and d.get("say"):
            self.body.say(str(d["say"]))
            self.act(f"said {d['say']!r}")
        elif intent == "gesture" and d.get("gesture") in GESTURES:
            self.body.gesture(str(d["gesture"]))
            self.act(f"right hand now shows {d['gesture']}")
        elif intent == "grab" and d.get("target"):
            self.grab(str(d["target"]), hint)
        elif intent == "give" and d.get("target"):
            self.give(str(d["target"]), hint, d)
        elif intent == "drop":
            self.body.drop()
            self.act("dropped what was in the right hand")
        elif intent == "crouch":
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
            self.api.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the Muse body agent against a VRChat desktop window.")
    ap.add_argument("--goal", default="Find someone nearby, walk up to them and greet them.")
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true", help="print controller/OSC output instead of sending it")
    ap.add_argument("--input", choices=["pad", "osc"], default="pad",
                    help="locomotion via a virtual Xbox pad (default) or VRChat's OSC /input axes")
    ap.add_argument("--log-dir", type=Path, default=Path("runs") / time.strftime("%Y%m%d-%H%M%S"))
    args = ap.parse_args()
    Agent(Settings.from_env(), args.goal, dry_run=args.dry_run, log_dir=args.log_dir,
          locomotion=args.input).run(args.steps)


if __name__ == "__main__":
    main()
