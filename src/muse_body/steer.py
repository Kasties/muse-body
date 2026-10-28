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
    # Bearings below this are left alone (box jitter, not worth a turn).
    turn_deadband_deg: float = 3.0
    # Turn a little less than the measured bearing, so errors stay on one side.
    turn_fraction: float = 0.9
    # A box this tall that reaches the bottom edge is close (short or sitting avatars
    # never reach arrive_height; walking on loses them below the view).
    arrive_height_at_edge: float = 0.18


@dataclass(frozen=True)
class Command:
    walk: bool
    turn_deg: float  # body turn to make first; positive is right
    bearing_deg: float
    arrived: bool


def bearing_deg(det: Detection, fov_v_deg: float) -> float:
    """Horizontal angle from view centre to the box centre; positive is to the right."""
    cx, _ = det.center
    half_w = det.frame_w / 2
    tan_half_h = math.tan(math.radians(fov_v_deg) / 2) * det.frame_w / det.frame_h
    return math.degrees(math.atan((cx - half_w) / half_w * tan_half_h))


def elevation_deg(det: Detection, fov_v_deg: float) -> float:
    """Vertical angle from view centre to the box centre; positive is up."""
    _, cy = det.center
    half_h = det.frame_h / 2
    return math.degrees(math.atan((half_h - cy) / half_h * math.tan(math.radians(fov_v_deg) / 2)))


def steer(det: Detection, p: SteerParams = SteerParams(), arrive_height: float | None = None) -> Command:
    b = bearing_deg(det, p.fov_v_deg)
    turn = b * p.turn_fraction if abs(b) > p.turn_deadband_deg else 0.0
    at_bottom = det.y2 >= det.frame_h - 2
    arrive = p.arrive_height if arrive_height is None else arrive_height
    if det.height_frac >= arrive or (at_bottom and det.height_frac >= p.arrive_height_at_edge):
        return Command(False, turn if abs(b) > p.walk_cone_deg else 0.0, b, True)
    return Command(abs(b) <= p.walk_cone_deg, turn, b, False)


def pick(dets: list[Detection], min_conf: float = 0.3,
         hint: tuple[float, float] | None = None) -> Detection | None:
    """Choose one detection.

    With a hint (x, y in 0-1000 frame coordinates, from the VLM) the box containing it wins,
    else the box whose centre is nearest. SAM matches a phrase everywhere, including mirror
    reflections, menu thumbnails and HUD previews; the hint says which one the VLM meant.
    Without a hint: the most confident, then largest, detection.
    """
    usable = [d for d in dets if d.conf is None or d.conf >= min_conf]
    if not usable:
        return None
    if hint is None:
        return max(usable, key=lambda d: ((d.conf or 0.0), d.area_frac))

    def score(d: Detection) -> tuple[bool, float]:
        hx, hy = hint[0] * d.frame_w / 1000, hint[1] * d.frame_h / 1000
        inside = d.x1 <= hx <= d.x2 and d.y1 <= hy <= d.y2
        cx, cy = d.center
        dist = math.hypot((cx - hx) / d.frame_w, (cy - hy) / d.frame_h)
        # Among boxes containing the hint, prefer the tightest one.
        return (not inside, d.area_frac if inside else dist)

    return min(usable, key=score)
