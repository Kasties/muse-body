"""Turn a run log (runs/<name>/events.jsonl + frames) into a replay video.

Each logged frame is shown for as long as it lasted in the run (scaled by --speed), with
what the agent knew at that moment drawn over it: the SAM 3.1 box it is tracking, the
people the detector sees, Muse Spark's pointing hint, and in the side panels the current
decision (what it sees, what it wants, why) and the actions it just took.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
VIEW_W, VIEW_H = 1440, 810  # the game frame, scaled up from 1280x720
FPS = 15

BG = (14, 16, 22)
PANEL = (24, 27, 36)
TEXT = (232, 234, 240)
MUTED = (140, 146, 162)
TARGET = (255, 176, 32)
PEOPLE = (64, 200, 255)
HINT = (255, 72, 160)
ACT = (110, 220, 120)
ERRAND = (255, 210, 90)
INTENT_COLORS = {
    "give": ERRAND,
    "look_around": (120, 130, 255), "approach": TARGET, "follow": TARGET, "grab": (255, 120, 80),
    "wave": ACT, "say": ACT, "gesture": ACT, "drop": (255, 120, 80), "crouch": MUTED, "wait": MUTED,
}


def _font(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


SANS = ["segoeui.ttf", "DejaVuSans.ttf", "arial.ttf"]
BOLD = ["segoeuib.ttf", "DejaVuSans-Bold.ttf", "arialbd.ttf"]
MONO = ["consola.ttf", "DejaVuSansMono.ttf", "cour.ttf"]


@dataclass
class Fonts:
    title: ImageFont.FreeTypeFont = field(default_factory=lambda: _font(BOLD, 34))
    label: ImageFont.FreeTypeFont = field(default_factory=lambda: _font(BOLD, 20))
    body: ImageFont.FreeTypeFont = field(default_factory=lambda: _font(SANS, 24))
    small: ImageFont.FreeTypeFont = field(default_factory=lambda: _font(SANS, 19))
    mono: ImageFont.FreeTypeFont = field(default_factory=lambda: _font(MONO, 20))


def wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


@dataclass
class Shot:
    """One logged frame and the state the agent was in when it was taken."""
    frame: Path
    t: float
    record: dict
    decision: dict | None  # the latest Muse Spark decision at or before this frame
    acts: list[str]  # actions taken since the previous frame, newest last
    duration: float = 0.0


def load(run: Path) -> list[Shot]:
    shots: list[Shot] = []
    decision, pending = None, []
    for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("phase") == "act":
            # An action belongs to the frame that led to it. Replies to chat are sent while
            # the step's decision is made, before its frame is logged: they wait for it.
            if shots and shots[-1].record.get("step") == r.get("step"):
                shots[-1].acts.append(r["act"])
            else:
                pending.append(r["act"])
            continue
        if r.get("phase") == "decide":
            decision = r
        if not r.get("frame") or not (run / r["frame"]).exists():
            continue
        shots.append(Shot(run / r["frame"], r["t"], r, decision, pending))
        pending = []
    for a, b in zip(shots, shots[1:]):
        a.duration = b.t - a.t
    if shots:
        shots[-1].duration = 3.0
    return shots


def load_calls(run: Path) -> list[dict]:
    """The run's Meta Model API calls (api_calls.jsonl, logged since Nov 4), ordered by when they
    finished; empty for older runs."""
    path = run / "api_calls.jsonl"
    if not path.exists():
        return []
    calls = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    calls = [c for c in calls if c.get("event") != "session"]
    for c in calls:
        c["done"] = c["t"] + (c.get("seconds") or 0.0)
    return sorted(calls, key=lambda c: c["done"])


CALL_NAMES = {"chat/completions": "Muse Spark", "responses": "SAM 3.1", "asr/realtime": "Voice Transcribe"}


def _calls(d: ImageDraw.ImageDraw, calls: list[dict], now: float, f: Fonts, x: int, y: int) -> None:
    """The API calls finished by `now`: how many, and the last few with their clock time."""
    done = [c for c in calls if c["done"] <= now]
    d.text((x, y), f"META API CALLS  {len(done)}", fill=MUTED, font=f.label)
    y += 32
    for c in done[-5:]:
        clock = time.strftime("%H:%M:%S", time.localtime(c["t"]))
        name = CALL_NAMES.get(c.get("api"), c.get("api", "?"))
        took = f"{c['seconds']:4.1f} s" if c.get("seconds") is not None else "  text"
        failed = "" if c.get("status", 200) < 400 and not c.get("error") else " !"
        d.text((x, y), f"{clock}  {name:<16}{took}{failed}", fill=TEXT, font=f.mono)
        y += 28


def _box(draw, box, scale, color, width, label=None, font=None):
    x1, y1, x2, y2 = (v * scale for v in box)
    draw.rectangle([x1, y1, x2, y2], outline=color, width=width)
    if label and font:
        tw = draw.textlength(label, font=font)
        tx, ty = min(x1, VIEW_W - tw - 12), y1 - 28 if y1 >= 28 else y2 + 2  # kept inside the view
        draw.rectangle([tx, ty, tx + tw + 12, ty + 26], fill=color)
        draw.text((tx + 6, ty + 1), label, fill=BG, font=font)


def render(shot: Shot, goal: str, t0: float, f: Fonts, recent_acts: list[str],
           calls: list[dict] | None = None) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    frame = Image.open(shot.frame).convert("RGB")
    scale = VIEW_W / frame.width
    img.paste(frame.resize((VIEW_W, round(frame.height * scale)), Image.LANCZOS), (0, 0))
    d = ImageDraw.Draw(img)
    r, dec = shot.record, shot.decision or {}
    phase = r.get("phase", "")

    # Desktop interaction crosshair.
    cx, cy = VIEW_W // 2, VIEW_H // 2
    d.line([cx - 12, cy, cx + 12, cy], fill=(255, 255, 255), width=2)
    d.line([cx, cy - 12, cx, cy + 12], fill=(255, 255, 255), width=2)

    for p in r.get("people") or []:
        _box(d, p, scale, PEOPLE, 3, "person", f.small)
    for o in r.get("own") or []:
        _box(d, o, scale, MUTED, 3, "own arm (ignored)", f.small)
    # An object scan's SAM matches, numbered as Muse Spark saw them when it picked one.
    cands, chosen, labels = r.get("candidates") or [], r.get("pick"), r.get("labels") or []
    for i, c in enumerate(cands, 1):
        if i != chosen:
            what = labels[i - 1] if i <= len(labels) else ""
            _box(d, c, scale, MUTED, 3, f"{i} not it: {what}" if what else f"{i} not it", f.small)
    if r.get("box"):
        conf = f" {r['conf']:.2f}" if r.get("conf") is not None else ""
        number = f"{chosen} · " if cands and chosen else ""
        _box(d, r["box"], scale, TARGET, 5, f"{number}SAM 3.1: {r.get('target', '')}{conf}", f.small)
        bx = (r["box"][0] + r["box"][2]) / 2 * scale
        by = (r["box"][1] + r["box"][3]) / 2 * scale
        d.line([cx, cy, bx, by], fill=TARGET, width=2)
    if phase == "decide" and dec.get("target_xy"):
        hx, hy = dec["target_xy"][0] / 1000 * VIEW_W, dec["target_xy"][1] / 1000 * VIEW_H
        d.ellipse([hx - 16, hy - 16, hx + 16, hy + 16], outline=HINT, width=4)
        d.ellipse([hx - 4, hy - 4, hx + 4, hy + 4], fill=HINT)
    if phase == "approach" and r.get("found") is False:
        d.text((24, 20), "SAM 3.1: target not in view", fill=TARGET, font=f.label,
               stroke_width=3, stroke_fill=BG)
    spoken = " ".join(dec.get("voice") or [])
    if phase == "decide" and (spoken or dec.get("heard")):
        # What Muse Voice Transcribe heard, or what Muse Spark read in someone's chat bubble,
        # as a caption over the view.
        caption = f"heard: “{spoken}”" if spoken else f"read in chat: “{dec['heard']}”"
        lines = wrap(d, caption, f.body, VIEW_W - 240)[:2]
        tw = max(d.textlength(line, font=f.body) for line in lines)
        x0 = (VIEW_W - tw) / 2 - 18
        d.rounded_rectangle([x0, 112, x0 + tw + 36, 124 + 32 * len(lines)], radius=12, fill=(250, 250, 250))
        for i, line in enumerate(lines):
            d.text((x0 + 18, 116 + 32 * i), line, fill=BG, font=f.body)
    if cands and r.get("check"):
        verdict = f"Muse Spark picks {chosen}" if chosen else "Muse Spark: none of them"
        lines = wrap(d, f"{verdict}: {r['check']}", f.body, VIEW_W - 240)[:2]
        tw = max(d.textlength(line, font=f.body) for line in lines)
        x0, y0 = (VIEW_W - tw) / 2 - 18, VIEW_H - 40 - 32 * len(lines)
        d.rounded_rectangle([x0, y0, x0 + tw + 36, y0 + 12 + 32 * len(lines)], radius=12,
                            fill=BG, outline=TARGET, width=2)
        for i, line in enumerate(lines):
            d.text((x0 + 18, y0 + 4 + 32 * i), line, fill=TEXT, font=f.body)

    # Right panel: goal, decision, live telemetry.
    px, pw = VIEW_W + 28, W - VIEW_W - 56
    d.rectangle([VIEW_W, 0, W, H], fill=PANEL)
    y = 26
    d.text((px, y), "muse-body", fill=TEXT, font=f.title)
    y += 48
    d.text((px, y), "Muse Spark decides  ·  SAM 3.1 grounds", fill=MUTED, font=f.small)
    if "voice" in dec:  # the run listened
        y += 26
        d.text((px, y), "Muse Voice Transcribe hears", fill=MUTED, font=f.small)
    y += 44
    d.text((px, y), "GOAL", fill=MUTED, font=f.label)
    y += 28
    for line in wrap(d, goal, f.body, pw)[:4]:
        d.text((px, y), line, fill=TEXT, font=f.body)
        y += 32
    y += 20
    errand = dec.get("errand")
    if errand:
        d.text((px, y), "ERRAND", fill=MUTED, font=f.label)
        y += 28
        for line in wrap(d, f"{errand['task']} (for {errand['for']})", f.body, pw)[:3]:
            d.text((px, y), line, fill=ERRAND, font=f.body)
            y += 32
        y += 20
    d.text((px, y), f"STEP {r.get('step', '?')}", fill=MUTED, font=f.label)
    d.text((px + pw - 110, y), f"t+{shot.t - t0:5.1f} s", fill=MUTED, font=f.mono)
    y += 34
    intent = dec.get("intent", "")
    if intent:
        color = INTENT_COLORS.get(intent, TEXT)
        label = intent.replace("_", " ").upper()
        tw = d.textlength(label, font=f.label)
        d.rounded_rectangle([px, y, px + tw + 24, y + 34], radius=8, fill=color)
        d.text((px + 12, y + 4), label, fill=BG, font=f.label)
        y += 46
    if dec.get("target"):
        for line in wrap(d, f"target: {dec['target']}", f.small, pw)[:2]:
            d.text((px, y), line, fill=TEXT, font=f.small)
            y += 26
    if dec.get("say"):
        d.text((px, y), f"plans to say: “{dec['say']}”", fill=TEXT, font=f.small)
        y += 26
    if dec.get("gesture"):
        d.text((px, y), f"plans gesture: {dec['gesture']}", fill=TEXT, font=f.small)
        y += 26
    if dec.get("mood"):
        d.text((px, y), f"mood: {dec['mood']}", fill=TEXT, font=f.small)
        y += 26
    y += 18

    d.text((px, y), "NOW", fill=MUTED, font=f.label)
    y += 30
    now = {"decide": "thinking (Muse Spark)", "follow": "following", "approach": "approaching",
           "scan": "scanning", "aim": "aiming crosshair",
           "holding": "noting what it holds"}.get(phase, phase)
    if cands:
        now = "checking SAM's matches"
    d.text((px, y), now, fill=TEXT, font=f.body)
    y += 46
    rows = []
    if r.get("bearing") is not None:
        rows.append(f"bearing   {r['bearing']:+6.1f}°")
    if r.get("elevation") is not None:
        rows.append(f"elevation {r['elevation']:+6.1f}°")
    if r.get("box"):
        rows.append(f"height    {(r['box'][3] - r['box'][1]) / frame.height:6.0%}")
    if phase == "scan":
        rows.append(f"turned    {r.get('turned', 0):+6d}°")
    if cands:
        rows.append(f"matches   {len(cands):6d}")
        rows.append(f"picked    {'#' + str(chosen) if chosen else 'none':>6}")
    if r.get("people") is not None:
        rows.append(f"people    {len(r['people']):6d}")
    if r.get("arrived"):
        rows.append("arrived   yes")
    for row in rows:
        d.text((px, y), row, fill=TEXT, font=f.mono)
        y += 28

    # Actions taken (chatbox, gestures, buttons), kept on screen for a few frames.
    if recent_acts:
        lines = [line for act in recent_acts for line in wrap(d, act, f.body, pw)[:2]][-6:]
        y = max(y + 20, H - 30 - 32 * len(lines) - 30)
        d.text((px, y), "DID", fill=MUTED, font=f.label)
        y += 30
        for line in lines:
            d.text((px, y), line, fill=ACT, font=f.body)
            y += 32

    # Bottom strip: what Muse Spark saw and why it chose this.
    d.rectangle([0, VIEW_H, VIEW_W, H], fill=BG)
    text_w = VIEW_W - 56
    if calls:  # the API calls so far, on the right of the strip
        text_w = VIEW_W - 520
        _calls(d, calls, shot.t, f, VIEW_W - 460, VIEW_H + 22)
    y = VIEW_H + 22
    d.text((28, y), "MUSE SPARK SEES", fill=MUTED, font=f.label)
    y += 30
    for line in wrap(d, dec.get("observation") or "…", f.body, text_w)[:3]:
        d.text((28, y), line, fill=TEXT, font=f.body)
        y += 32
    if dec.get("why"):
        y += 10
        for line in wrap(d, f"why: {dec['why']}", f.small, text_w)[:2]:
            d.text((28, y), line, fill=MUTED, font=f.small)
            y += 26
    return img


def write_video(run: Path, out: Path, goal: str, speed: float = 1.0,
                min_hold: float = 0.5, max_hold: float = 4.0) -> int:
    import imageio_ffmpeg

    shots = load(run)
    if not shots:
        raise SystemExit(f"no logged frames in {run}")
    calls = load_calls(run)
    f = Fonts()
    t0 = shots[0].t
    writer = imageio_ffmpeg.write_frames(str(out), (W, H), fps=FPS, codec="libx264",
                                         pix_fmt_out="yuv420p", quality=8, macro_block_size=8)
    writer.send(None)
    recent: list[tuple[int, str]] = []
    frames = 0
    try:
        for i, shot in enumerate(shots):
            recent = [(j, a) for j, a in recent if i - j < 4] + [(i, a) for a in shot.acts]
            img = render(shot, goal, t0, f, [a for _, a in recent[-3:]], calls)
            hold = min(max_hold, max(min_hold, shot.duration / speed))
            data = img.tobytes()
            for _ in range(max(1, round(hold * FPS))):
                writer.send(data)
                frames += 1
    finally:
        writer.close()
    return frames


def main() -> None:
    ap = argparse.ArgumentParser(description="Render a run log into a replay video.")
    ap.add_argument("run", type=Path, help="run directory with events.jsonl and frames")
    ap.add_argument("--out", type=Path, help="output .mp4 (default: <run>/replay.mp4)")
    ap.add_argument("--goal", help="goal text for the panel (default: from run.json, if logged)")
    ap.add_argument("--speed", type=float, default=1.0, help="playback speed relative to the run")
    ap.add_argument("--still", type=int, help="write only this frame index as a PNG preview")
    args = ap.parse_args()
    goal = args.goal
    meta = args.run / "run.json"
    if goal is None and meta.exists():
        goal = json.loads(meta.read_text(encoding="utf-8")).get("goal")
    goal = goal or ""
    if args.still is not None:
        shots = load(args.run)
        out = args.out or args.run / f"still_{args.still:03d}.png"
        render(shots[args.still], goal, shots[0].t, Fonts(), shots[args.still].acts,
               load_calls(args.run)).save(out)
        print(out)
        return
    out = args.out or args.run / "replay.mp4"
    n = write_video(args.run, out, goal, args.speed)
    print(f"{out}: {n / FPS:.1f} s")


if __name__ == "__main__":
    main()
