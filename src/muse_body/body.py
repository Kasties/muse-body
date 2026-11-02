"""The agent's body.

Locomotion goes through a virtual Xbox 360 controller (ViGEmBus + vgamepad), which VRChat
desktop reads like a real gamepad: analog move, analog look (yaw and pitch), buttons.
OSC (port 9000) stays for what a controller cannot do: the chatbox and avatar parameters.
The older OSC /input axes remain as a fallback locomotion backend (--input osc).
"""

from __future__ import annotations

import math
import time

from pythonosc.udp_client import SimpleUDPClient


# VRChat's standard hand gestures, in GestureLeft/GestureRight order.
GESTURES = ["neutral", "fist", "open", "point", "victory", "rocknroll", "gun", "thumbsup"]

# Avatar parameters the agent drives so people next to it can see its state. They do nothing
# until the avatar has them (synced, in its Expression Parameters); VRChat ignores unknown ones.
THINKING_PARAM = "Thinking"  # bool: true while Muse Spark decides
MOOD_PARAM = "Mood"  # int: index into MOODS
MOODS = ["neutral", "happy", "curious", "confused", "surprised"]


def _clamp(v: float) -> float:
    return float(max(-1.0, min(1.0, v)))


class OscOut:
    def __init__(self, host: str, port: int, dry_run: bool = False):
        self.dry_run = dry_run
        self.client = None if dry_run else SimpleUDPClient(host, port)

    def send(self, address: str, value) -> None:
        if self.dry_run:
            print(f"[osc] {address} {value}")
            return
        self.client.send_message(address, value)


class OscLocomotion:
    """VRChat's /input/* axes. No vertical look over OSC in desktop mode."""

    # Live 10-28: LookHorizontal -1 for 0.3 s turned ~68 deg; assumed linear below that.
    max_turn_rate = 225.0
    walk_stick = 1.0

    def __init__(self, osc: OscOut):
        self.osc = osc

    def turn_stick(self, rate: float) -> float:
        return rate / self.max_turn_rate

    def set(self, forward: float, strafe: float, turn: float, pitch: float) -> None:
        self.osc.send("/input/Vertical", _clamp(forward))
        self.osc.send("/input/Horizontal", _clamp(strafe))
        self.osc.send("/input/LookHorizontal", _clamp(turn))

    def button(self, name: str, down: bool) -> None:
        address = {"A": "/input/Jump"}.get(name)
        if address is None:
            raise ValueError(f"no OSC input for button {name!r}")
        self.osc.send(address, int(down))

    def close(self) -> None:
        pass


class PadLocomotion:
    """A virtual Xbox 360 pad. Left stick moves, right stick looks.

    VRChat desktop has a wide stick dead zone. Measured twice 10-28 via OSC AngularY and
    VelocityMagnitude: right stick x <= 0.55 does not turn, 0.6 -> 32-46 deg/s,
    0.7 -> 120-136, 0.8 -> 160-192, 0.9 and 1.0 -> 200 (second run) to 255 (first).
    Left stick y 0.3 -> 0.1 m/s, 0.45 -> 1.1, 0.6 -> 2.2, 0.8 -> 3.5, 1.0 -> 4.0 (run).
    """

    turn_dead = 0.55
    turn_slope = 700.0  # deg/s per stick unit above the dead zone
    max_turn_rate = 200.0
    walk_stick = 0.6  # ~2.2 m/s: slow enough to stop near a person
    warmup_seconds = 3.0

    # Pitch (right stick y, positive up) has a smaller dead zone. Measured 10-28 by
    # tracking a SAM box: 0.3 -> 4 deg/s, 0.4 -> 44, 0.5 -> 79, 0.6 -> 106, then it
    # flattens (0.8 -> ~185, 1.0 -> ~200). Kept to the linear part.
    pitch_dead = 0.28
    pitch_slope = 340.0
    max_pitch_rate = 100.0

    def turn_stick(self, rate: float) -> float:
        if rate == 0:
            return 0.0
        return math.copysign(self.turn_dead + abs(rate) / self.turn_slope, rate)

    def pitch_stick(self, rate: float) -> float:
        if rate == 0:
            return 0.0
        return math.copysign(self.pitch_dead + abs(rate) / self.pitch_slope, rate)

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.pad = None
        if dry_run:
            return
        try:
            import vgamepad as vg
            self._buttons = {
                "A": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
                "B": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
                "X": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
                "Y": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
                "LB": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
                "RB": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
                "LS": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
                "RS": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
                "START": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
                "BACK": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
            }
            self.pad = vg.VX360Gamepad()
        except Exception as e:  # ViGEmBus missing raises from the client DLL
            raise SystemExit(
                f"virtual gamepad unavailable ({e}). Install the ViGEmBus driver "
                "(https://github.com/nefarius/ViGEmBus/releases) or run with --input osc."
            ) from e
        self.pad.reset()
        self.pad.update()
        # VRChat ignores a newly plugged pad for a few seconds ("Controller Connected"
        # toast). Then a nudge inside the stick dead zone makes it the active device
        # without moving anything.
        time.sleep(self.warmup_seconds)
        self.sticks(0.0, 0.0, 0.3, 0.0)
        time.sleep(0.3)
        self.sticks(0.0, 0.0, 0.0, 0.0)

    def set(self, forward: float, strafe: float, turn: float, pitch: float) -> None:
        self.sticks(strafe, forward, turn, pitch)

    def sticks(self, lx: float, ly: float, rx: float, ry: float) -> None:
        if self.dry_run:
            print(f"[pad] left=({lx:+.2f},{ly:+.2f}) right=({rx:+.2f},{ry:+.2f})")
            return
        self.pad.left_joystick_float(_clamp(lx), _clamp(ly))
        self.pad.right_joystick_float(_clamp(rx), _clamp(ry))
        self.pad.update()

    def button(self, name: str, down: bool) -> None:
        if self.dry_run:
            print(f"[pad] {name} {'down' if down else 'up'}")
            return
        if name in ("LT", "RT"):
            trigger = self.pad.left_trigger_float if name == "LT" else self.pad.right_trigger_float
            trigger(1.0 if down else 0.0)
        else:
            (self.pad.press_button if down else self.pad.release_button)(self._buttons[name])
        self.pad.update()

    def close(self) -> None:
        if self.pad is not None:
            self.pad.reset()
            self.pad.update()


class Body:
    def __init__(self, host: str = "127.0.0.1", port: int = 9000, dry_run: bool = False, locomotion: str = "pad"):
        self.osc = OscOut(host, port, dry_run=dry_run)
        self.loco = PadLocomotion(dry_run) if locomotion == "pad" else OscLocomotion(self.osc)
        self.pitch_deg = 0.0  # net look_by since start, for level()

    def axes(self, forward: float = 0.0, strafe: float = 0.0, turn: float = 0.0, pitch: float = 0.0) -> None:
        """Hold the movement and look axes (each -1..1) until the next call."""
        self.loco.set(forward, strafe, turn, pitch)

    def stop(self) -> None:
        self.axes(0.0, 0.0, 0.0, 0.0)

    def pulse(self, forward: float = 0.0, turn: float = 0.0, pitch: float = 0.0, seconds: float = 0.3) -> None:
        self.axes(forward=forward, turn=turn, pitch=pitch)
        time.sleep(seconds)
        self.stop()

    def turn_by(self, degrees: float, min_rate: float = 60.0, max_seconds: float = 0.4) -> None:
        """Turn the body by about this many degrees (positive is right), open loop.

        Rate is chosen so the turn takes at most max_seconds; small turns run at
        min_rate, where the stick response is still reliable.
        """
        if abs(degrees) < 0.5:
            return
        rate = min(self.loco.max_turn_rate, max(min_rate, abs(degrees) / max_seconds))
        self.axes(turn=self.loco.turn_stick(math.copysign(rate, degrees)))
        time.sleep(abs(degrees) / rate)
        self.stop()

    def look_by(self, degrees: float, min_rate: float = 40.0, max_seconds: float = 0.4) -> None:
        """Pitch the view by about this many degrees (positive is up), open loop. Pad only."""
        if abs(degrees) < 0.5 or not isinstance(self.loco, PadLocomotion):
            return
        rate = min(self.loco.max_pitch_rate, max(min_rate, abs(degrees) / max_seconds))
        self.axes(pitch=self.loco.pitch_stick(math.copysign(rate, degrees)))
        time.sleep(abs(degrees) / rate)
        self.stop()
        self.pitch_deg += degrees

    def level(self) -> None:
        """Undo the pitch this body applied, back to the view it started with."""
        self.look_by(-self.pitch_deg)

    def walk(self, seconds: float = 0.6) -> None:
        self.axes(forward=self.loco.walk_stick)
        time.sleep(seconds)
        self.stop()

    def press(self, button: str, seconds: float = 0.1) -> None:
        self.loco.button(button, True)
        time.sleep(seconds)
        self.loco.button(button, False)

    def jump(self) -> None:
        self.press("A")

    # VRChat desktop gamepad bindings (wiki.vrchat.com/wiki/Controls). Verified live 10-28:
    # gestures (RB + stick, GestureLeft/Right over OSC) and crouch (LS click, Upright 1.0 <-> 0.6).
    # From the wiki only, not yet verified: LT/RT interact/pick up, B/X drop.

    def interact(self, hand: str = "right") -> None:
        """Interact with / pick up whatever is under the screen-centre crosshair."""
        self.press("RT" if hand == "right" else "LT", seconds=0.15)

    def drop(self, hand: str = "right") -> None:
        self.press("B" if hand == "right" else "X")

    def crouch_toggle(self) -> None:
        self.press("LS")

    def gesture(self, name: str, hand: str = "right", hold: float = 0.5) -> None:
        """Select a hand gesture: RB held, stick pushed to the gesture's direction.
        The gesture stays until another is selected; 'neutral' (stick up) resets it."""
        if not isinstance(self.loco, PadLocomotion):
            raise ValueError("gestures need the pad (GestureLeft/Right are read-only over OSC)")
        index = GESTURES.index(name)
        # 0 is straight up, then clockwise in 45 degree steps (measured: NE=1 ... NW=7).
        a = math.radians(90 - 45 * index)
        x, y = math.cos(a), math.sin(a)
        stick = (0.0, 0.0, x, y) if hand == "right" else (x, y, 0.0, 0.0)
        self.loco.button("RB", True)
        time.sleep(0.15)
        self.loco.sticks(*stick)
        time.sleep(hold)
        self.loco.sticks(0.0, 0.0, 0.0, 0.0)
        time.sleep(0.2)
        self.loco.button("RB", False)

    def say(self, text: str) -> None:
        # Chatbox: text, send immediately, no notification sound.
        self.osc.send("/chatbox/input", [text[:144], True, False])

    def param(self, name: str, value) -> None:
        self.osc.send(f"/avatar/parameters/{name}", value)

    def thinking(self, on: bool) -> None:
        """Show that the mind is busy: the Thinking parameter and the chatbox typing dots."""
        self.param(THINKING_PARAM, bool(on))
        self.osc.send("/chatbox/typing", bool(on))

    def mood(self, name: str) -> None:
        if name in MOODS:
            self.param(MOOD_PARAM, MOODS.index(name))

    def emote(self, slot: int, seconds: float = 2.0) -> None:
        """Play an avatar emote via the VRCEmote parameter (avatar-dependent; 1 is wave on SDK menus)."""
        self.param("VRCEmote", int(slot))
        time.sleep(seconds)
        self.param("VRCEmote", 0)

    def close(self) -> None:
        self.stop()
        self.loco.close()
