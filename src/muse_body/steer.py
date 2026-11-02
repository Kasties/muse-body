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


def x_bearing(x: float, fov_v_deg: float, frame_w: int, frame_h: int) -> float:
    """Horizontal angle from view centre to frame column x; positive is to the right."""
    half_w = frame_w / 2
    tan_half_h = math.tan(math.radians(fov_v_deg) / 2) * frame_w / frame_h
    return math.degrees(math.atan((x - half_w) / half_w * tan_half_h))


def bearing_deg(det: Detection, fov_v_deg: float) -> float:
    """Horizontal angle from view centre to the box centre; positive is to the right."""
    return x_bearing(det.center[0], fov_v_deg, det.frame_w, det.frame_h)


def screen_x(bearing: float, fov_v_deg: float, frame_w: int, frame_h: int) -> float:
    """Inverse of x_bearing: the frame column at which something at this bearing shows."""
    half_w = frame_w / 2
    tan_half_h = math.tan(math.radians(fov_v_deg) / 2) * frame_w / frame_h
    return half_w + half_w * math.tan(math.radians(bearing)) / tan_half_h


def iou(a: Detection, b: Detection) -> float:
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    union = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter
    return inter / union if union > 0 else 0.0


def covered(a: Detection, b: Detection) -> float:
    """How much of a lies inside b (0-1)."""
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    area = (a.x2 - a.x1) * (a.y2 - a.y1)
    return ix * iy / area if area > 0 else 0.0


def elevation_deg(det: Detection, fov_v_deg: float) -> float:
    """Vertical angle from view centre to the box centre; positive is up."""
    _, cy = det.center
    half_h = det.frame_h / 2
    return math.degrees(math.atan((half_h - cy) / half_h * math.tan(math.radians(fov_v_deg) / 2)))


def steer(det: Detection, p: SteerParams = SteerParams(), arrive_height: float | None = None,
          offset_deg: float = 0.0) -> Command:
    """offset_deg keeps the target at that bearing instead of straight ahead while walking up
    (beside a held object that would hide it); on arrival the body faces the target."""
    b = bearing_deg(det, p.fov_v_deg)
    at_bottom = det.y2 >= det.frame_h - 2
    arrive = p.arrive_height if arrive_height is None else arrive_height
    if det.height_frac >= arrive or (at_bottom and det.height_frac >= p.arrive_height_at_edge):
        # Close up, keep facing them (10-29: a person stayed 11 deg off-centre for 12 frames).
        return Command(False, b * p.turn_fraction if abs(b) > p.turn_deadband_deg else 0.0, b, True)
    off = b - offset_deg
    turn = off * p.turn_fraction if abs(off) > p.turn_deadband_deg else 0.0
    return Command(abs(off) <= p.walk_cone_deg, turn, b, False)


def pick(dets: list[Detection], min_conf: float = 0.3,
         hint: tuple[float, float] | None = None, near: float | None = None) -> Detection | None:
    """Choose one detection.

    With a hint (x, y in 0-1000 frame coordinates, from the VLM) the box containing it wins,
    else the box whose centre is nearest. SAM matches a phrase everywhere, including mirror
    reflections, menu thumbnails and HUD previews; the hint says which one the VLM meant.
    With `near` as well, a box that does not contain the hint must have its centre within that
    distance of it (as a fraction of the frame), or nothing is picked.
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

    best = min(usable, key=score)
    outside, dist = score(best)
    return None if near is not None and outside and dist > near else best
