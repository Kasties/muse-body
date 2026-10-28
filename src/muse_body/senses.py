"""Body senses from VRChat's outgoing OSC (port 9001): motion, grounding, touch.

VRChat sends every avatar parameter when it changes, plus built-ins such as
VelocityMagnitude, Grounded and AngularY. Avatar-specific bools (contact receivers,
e.g. a head-pat contact) are reported as touch events.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer

BUILTIN = {
    "IsLocal", "Viseme", "Voice", "GestureLeft", "GestureRight", "GestureLeftWeight",
    "GestureRightWeight", "AngularY", "VelocityX", "VelocityY", "VelocityZ",
    "VelocityMagnitude", "Upright", "Grounded", "Seated", "AFK", "TrackingType",
    "VRMode", "MuteSelf", "InStation", "Earmuffs", "IsOnFriendsList", "AvatarVersion",
    "IsAnimatorEnabled", "ScaleModified", "ScaleFactor", "ScaleFactorInverse",
    "EyeHeightAsMeters", "EyeHeightAsPercent", "VRCEmote", "VRCFaceBlendH", "VRCFaceBlendV",
}


@dataclass
class Reading:
    value: object
    t: float


class Senses:
    def __init__(self, host: str = "127.0.0.1", port: int = 9001):
        self.params: dict[str, Reading] = {}
        self.events: list[tuple[float, str]] = []
        self.avatar: str | None = None
        self._lock = threading.Lock()
        d = Dispatcher()
        d.map("/avatar/parameters/*", self._on_param)
        d.map("/avatar/change", self._on_avatar)
        self.server = ThreadingOSCUDPServer((host, port), d)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> "Senses":
        self.thread.start()
        return self

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _on_avatar(self, address: str, *args) -> None:
        new = str(args[0]) if args else None
        with self._lock:
            # VRChat also sends /avatar/change when OSC output starts; only a different id is news.
            if self.avatar is not None and new != self.avatar:
                self.params.clear()
                self.events.append((time.time(), "avatar changed"))
            self.avatar = new

    def _on_param(self, address: str, *args) -> None:
        if not args:
            return
        name, value, now = address.rsplit("/", 1)[-1], args[0], time.time()
        with self._lock:
            old = self.params.get(name)
            self.params[name] = Reading(value, now)
            if name not in BUILTIN and isinstance(value, bool) and value and (old is None or not old.value):
                self.events.append((now, f"{name} became true"))
                del self.events[:-20]

    def get(self, name: str, default=None):
        with self._lock:
            r = self.params.get(name)
        return default if r is None else r.value

    def speed(self) -> float | None:
        v = self.get("VelocityMagnitude")
        return float(v) if isinstance(v, (int, float)) else None

    def take_events(self) -> list[str]:
        with self._lock:
            out = [e for _, e in self.events]
            self.events.clear()
        return out

    def summary(self) -> str:
        parts = []
        speed = self.speed()
        if speed is not None:
            parts.append(f"speed {speed:.1f} m/s")
        grounded = self.get("Grounded")
        if grounded is not None:
            parts.append("on the ground" if grounded else "in the air")
        if self.get("Seated"):
            parts.append("seated")
        if parts:
            return ", ".join(parts)
        # VRChat only sends a parameter when it changes, so silence while still is normal.
        return "standing still" if self.avatar or self.params else "no body state from VRChat yet"
