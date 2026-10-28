"""The loop: see (Muse Spark) -> ground (SAM 3.1) -> move (OSC) -> repeat."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from .body import Body
from .capture import Camera
from .config import Settings
from .meta_api import MetaClient, extract_json
from .steer import SteerParams, pick, steer

SYSTEM = """You are the mind of an avatar in VRChat. You see one first-person frame at a time.
Choose ONE next intention. Reply with a single JSON object only:
{
  "observation": "<one sentence: what you see>",
  "intent": "approach" | "look_around" | "wave" | "say" | "wait",
  "target": "<2-4 word visual description of the thing to approach, else null>",
  "target_xy": [<x>, <y>] or null,
  "say": "<chat text if intent is say or wave, else null>",
  "why": "<one short reason>"
}
"target" is passed to a segmentation model, so describe what it LOOKS like: species,
colour, clothing ("raccoon", "green dinosaur", "girl with pink hair"). Never use bare words
like "person", "avatar" or "player": avatars are stylised and those words match nothing.
"target_xy" is where the target is in this frame, in 0-1000 coordinates (0,0 top-left).
Ignore mirror reflections, menus, thumbnails and HUD overlays: they cannot be walked to.
Prefer approaching people, then greeting them once you are close. Keep chat short and friendly."""


def parse_xy(value) -> tuple[float, float] | None:
    """A [x, y] pair in 0-1000 frame coordinates, or None."""
    try:
        x, y = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    return (x, y) if 0 <= x <= 1000 and 0 <= y <= 1000 else None


@dataclass
class Memory:
    """A short rolling log of what the agent did, fed back into the next decision."""
    events: list[str] = field(default_factory=list)
    limit: int = 8

    def add(self, text: str) -> None:
        self.events.append(text)
        del self.events[: -self.limit]

    def prompt(self, goal: str) -> str:
        recent = "\n".join(f"- {e}" for e in self.events) or "- (nothing yet)"
        return f"Goal: {goal}\nRecent:\n{recent}\nWhat next?"


class Agent:
    def __init__(self, settings: Settings, goal: str, dry_run: bool = False, log_dir: Path | None = None):
        self.api = MetaClient(settings)
        self.cam = Camera()
        self.body = Body(settings.osc_host, settings.osc_port, dry_run=dry_run)
        self.steer_params = SteerParams(fov_v_deg=settings.fov_v_deg)
        self.goal = goal
        self.memory = Memory()
        self.log_dir = log_dir
        self.step = 0
        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)

    def log(self, frame: Image.Image, record: dict) -> None:
        if not self.log_dir:
            return
        frame.save(self.log_dir / f"{self.step:04d}.jpg", quality=80)
        with open(self.log_dir / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"step": self.step, "t": time.time(), **record}) + "\n")

    def decide(self, frame: Image.Image) -> dict:
        reply = self.api.see(frame, SYSTEM, self.memory.prompt(self.goal))
        try:
            return extract_json(reply)
        except ValueError:
            return {"intent": "wait", "why": "unparseable reply", "raw": reply[:300]}

    def approach(self, target: str, hint: tuple[float, float] | None = None, max_steps: int = 12) -> bool:
        """Closed loop on SAM boxes until the target fills enough of the view."""
        for _ in range(max_steps):
            frame = self.cam.grab()
            det = pick(self.api.segment(frame, target), hint=hint)
            if det is not None:
                # Follow the box we chose, not whatever else matches the phrase.
                hint = (1000 * det.center[0] / det.frame_w, 1000 * det.center[1] / det.frame_h)
            if det is None:
                self.memory.add(f"lost sight of {target}")
                self.log(frame, {"phase": "approach", "target": target, "found": False})
                self.body.stop()
                return False
            cmd = steer(det, self.steer_params)
            self.log(frame, {"phase": "approach", "target": target, "box": [det.x1, det.y1, det.x2, det.y2],
                             "conf": det.conf, "bearing": round(cmd.bearing_deg, 1), "arrived": cmd.arrived})
            if cmd.arrived and cmd.turn == 0.0:
                self.body.stop()
                self.memory.add(f"reached {target}")
                return True
            self.body.pulse(forward=cmd.forward, turn=cmd.turn, seconds=0.6 if cmd.forward else 0.3)
        self.memory.add(f"gave up approaching {target}")
        return False

    def tick(self) -> None:
        self.step += 1
        frame = self.cam.grab()
        d = self.decide(frame)
        self.log(frame, {"phase": "decide", **d})
        intent = d.get("intent")
        print(f"[{self.step}] {intent}: {d.get('observation')} ({d.get('why')})")
        if intent == "approach" and d.get("target"):
            self.approach(str(d["target"]), hint=parse_xy(d.get("target_xy")))
        elif intent == "look_around":
            self.body.pulse(turn=0.6, seconds=0.5)
            self.memory.add("turned to look around")
        elif intent == "wave":
            if d.get("say"):
                self.body.say(str(d["say"]))
            self.body.emote(1)
            self.memory.add(f"waved{' and said ' + repr(d['say']) if d.get('say') else ''}")
        elif intent == "say" and d.get("say"):
            self.body.say(str(d["say"]))
            self.memory.add(f"said {d['say']!r}")
        else:
            self.memory.add("waited")
            time.sleep(1.0)

    def run(self, steps: int) -> None:
        try:
            for _ in range(steps):
                self.tick()
        finally:
            self.body.stop()
            self.api.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the Muse body agent against a VRChat desktop window.")
    ap.add_argument("--goal", default="Find someone nearby, walk up to them and greet them.")
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true", help="print OSC messages instead of sending them")
    ap.add_argument("--log-dir", type=Path, default=Path("runs") / time.strftime("%Y%m%d-%H%M%S"))
    args = ap.parse_args()
    Agent(Settings.from_env(), args.goal, dry_run=args.dry_run, log_dir=args.log_dir).run(args.steps)


if __name__ == "__main__":
    main()
