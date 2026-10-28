"""The agent's body.

Locomotion goes through a virtual Xbox 360 controller (ViGEmBus + vgamepad), which VRChat
desktop reads like a real gamepad: analog move, analog look (yaw and pitch), buttons.
OSC (port 9000) stays for what a controller cannot do: the chatbox and avatar parameters.
The older OSC /input axes remain as a fallback locomotion backend (--input osc).
"""

from __future__ import annotations

import time

from pythonosc.udp_client import SimpleUDPClient


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

    def __init__(self, osc: OscOut):
        self.osc = osc

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
    """A virtual Xbox 360 pad. Left stick moves, right stick looks."""

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

    def set(self, forward: float, strafe: float, turn: float, pitch: float) -> None:
        if self.dry_run:
            print(f"[pad] move=({strafe:+.2f},{forward:+.2f}) look=({turn:+.2f},{pitch:+.2f})")
            return
        self.pad.left_joystick_float(_clamp(strafe), _clamp(forward))
        self.pad.right_joystick_float(_clamp(turn), _clamp(pitch))
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

    def axes(self, forward: float = 0.0, strafe: float = 0.0, turn: float = 0.0, pitch: float = 0.0) -> None:
        """Hold the movement and look axes (each -1..1) until the next call."""
        self.loco.set(forward, strafe, turn, pitch)

    def stop(self) -> None:
        self.axes(0.0, 0.0, 0.0, 0.0)

    def pulse(self, forward: float = 0.0, turn: float = 0.0, pitch: float = 0.0, seconds: float = 0.3) -> None:
        self.axes(forward=forward, turn=turn, pitch=pitch)
        time.sleep(seconds)
        self.stop()

    def press(self, button: str, seconds: float = 0.1) -> None:
        self.loco.button(button, True)
        time.sleep(seconds)
        self.loco.button(button, False)

    def jump(self) -> None:
        self.press("A")

    def say(self, text: str) -> None:
        # Chatbox: text, send immediately, no notification sound.
        self.osc.send("/chatbox/input", [text[:144], True, False])

    def param(self, name: str, value) -> None:
        self.osc.send(f"/avatar/parameters/{name}", value)

    def emote(self, slot: int, seconds: float = 2.0) -> None:
        """Play an avatar emote via the VRCEmote parameter (avatar-dependent; 1 is wave on SDK menus)."""
        self.param("VRCEmote", int(slot))
        time.sleep(seconds)
        self.param("VRCEmote", 0)

    def close(self) -> None:
        self.stop()
        self.loco.close()
