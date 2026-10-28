"""Turn a SAM box into body commands: face the target, then walk until it is close."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .sam_format import Detection


@dataclass(frozen=True)
class SteerParams:
    fov_v_deg: float = 70.0
    # Box height as a fraction of the frame at which the target counts as reached.
    arrive_height: float = 0.55
    # Bearing (degrees) inside which the agent walks instead of only turning.
    walk_cone_deg: float = 12.0
    turn_gain: float = 1.0 / 30.0


@dataclass(frozen=True)
class Command:
    forward: float
    turn: float
    bearing_deg: float
    arrived: bool


def bearing_deg(det: Detection, fov_v_deg: float) -> float:
    """Horizontal angle from view centre to the box centre; positive is to the right."""
    cx, _ = det.center
    half_w = det.frame_w / 2
    tan_half_h = math.tan(math.radians(fov_v_deg) / 2) * det.frame_w / det.frame_h
    return math.degrees(math.atan((cx - half_w) / half_w * tan_half_h))


def steer(det: Detection, p: SteerParams = SteerParams()) -> Command:
    b = bearing_deg(det, p.fov_v_deg)
    turn = max(-1.0, min(1.0, b * p.turn_gain))
    if det.height_frac >= p.arrive_height:
        return Command(0.0, turn if abs(b) > p.walk_cone_deg else 0.0, b, True)
    forward = 1.0 if abs(b) <= p.walk_cone_deg else 0.0
    return Command(forward, turn, b, False)


def pick(dets: list[Detection], min_conf: float = 0.3) -> Detection | None:
    """The most confident, then largest, detection."""
    usable = [d for d in dets if d.conf is None or d.conf >= min_conf]
    if not usable:
        return None
    return max(usable, key=lambda d: ((d.conf or 0.0), d.area_frac))
