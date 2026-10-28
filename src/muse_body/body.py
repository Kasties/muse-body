"""The agent's body: VRChat's OSC input endpoints (desktop mode, OSC enabled in the Action Menu)."""

from __future__ import annotations

import time

from pythonosc.udp_client import SimpleUDPClient


class Body:
    def __init__(self, host: str = "127.0.0.1", port: int = 9000, dry_run: bool = False):
        self.dry_run = dry_run
        self.client = None if dry_run else SimpleUDPClient(host, port)

    def _send(self, address: str, value) -> None:
        if self.dry_run:
            print(f"[osc] {address} {value}")
            return
        self.client.send_message(address, value)

    def axes(self, forward: float = 0.0, strafe: float = 0.0, turn: float = 0.0) -> None:
        """Hold the movement axes (each -1..1) until the next call."""
        self._send("/input/Vertical", float(max(-1.0, min(1.0, forward))))
        self._send("/input/Horizontal", float(max(-1.0, min(1.0, strafe))))
        self._send("/input/LookHorizontal", float(max(-1.0, min(1.0, turn))))

    def stop(self) -> None:
        self.axes(0.0, 0.0, 0.0)

    def pulse(self, forward: float = 0.0, turn: float = 0.0, seconds: float = 0.3) -> None:
        self.axes(forward=forward, turn=turn)
        time.sleep(seconds)
        self.stop()

    def jump(self) -> None:
        self._send("/input/Jump", 1)
        time.sleep(0.1)
        self._send("/input/Jump", 0)

    def say(self, text: str) -> None:
        # Chatbox: text, send immediately, no notification sound.
        self._send("/chatbox/input", [text[:144], True, False])

    def emote(self, slot: int, seconds: float = 2.0) -> None:
        """Play an avatar emote via the VRCEmote parameter (avatar-dependent; 1 is wave on SDK menus)."""
        self._send("/avatar/parameters/VRCEmote", int(slot))
        time.sleep(seconds)
        self._send("/avatar/parameters/VRCEmote", 0)
