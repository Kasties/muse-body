"""Parse SAM 3.1 special-token output into boxes and masks.

SAM 3.1 on the Meta Model API answers with one text line per frame:

    <0f>1<|box;x1=..;y1=..;x2=..;y2=..;w=W;h=H;c=0.91|><|mask;data=H,W,~...|>,2<|box;...|>...

Boxes are in source pixels. Fields are parsed by key, not position.
Mask payloads are base85; they are kept raw here and decoded on demand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_FRAME = re.compile(r"<(\d+)f>")
# Base85 mask payloads may contain '|', '<', ';' and ',', so records are split on
# "<id><|box;" starts and the box token (plain ints) is the only one parsed by regex.
_RECORD_START = re.compile(r"(?:^|,)\s*(\w+)\s*<\|box;")
_BOX = re.compile(r"<\|box;([^|]*)\|>")
_MASK = re.compile(r"<\|mask;(.*)\|>\s*$", re.S)


@dataclass
class Detection:
    obj_id: str
    x1: int
    y1: int
    x2: int
    y2: int
    frame_w: int
    frame_h: int
    conf: float | None = None
    mask: str | None = None
    frame: int = 0
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def center(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2

    @property
    def height_frac(self) -> float:
        return (self.y2 - self.y1) / self.frame_h if self.frame_h else 0.0

    @property
    def area_frac(self) -> float:
        if not self.frame_w or not self.frame_h:
            return 0.0
        return (self.x2 - self.x1) * (self.y2 - self.y1) / (self.frame_w * self.frame_h)


def _fields(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in body.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def parse(text: str) -> list[Detection]:
    """Parse every frame line of a SAM 3.1 response."""
    detections: list[Detection] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        frame = 0
        m = _FRAME.match(line)
        if m:
            frame = int(m.group(1))
            line = line[m.end():]
        # Split into records: an id followed by one or more tokens.
        starts = [(m.start(), m.start(1), m.group(1)) for m in _RECORD_START.finditer(line)]
        for i, (_, start, obj_id) in enumerate(starts):
            end = starts[i + 1][0] if i + 1 < len(starts) else len(line)
            det = _record(obj_id, line[start:end], frame)
            if det is not None:
                detections.append(det)
    return detections


def _record(obj_id: str, chunk: str, frame: int) -> Detection | None:
    bm = _BOX.search(chunk)
    if bm is None:
        return None
    box = _fields(bm.group(1))
    mask: str | None = None
    mm = _MASK.search(chunk, bm.end())
    if mm:
        body = mm.group(1)
        # data=H,W,<enc>payload is the last field; keep everything after it verbatim.
        idx = body.find("data=")
        mask = body[idx + 5:] if idx >= 0 else body
    try:
        det = Detection(
            obj_id=obj_id,
            x1=int(float(box.pop("x1"))),
            y1=int(float(box.pop("y1"))),
            x2=int(float(box.pop("x2"))),
            y2=int(float(box.pop("y2"))),
            frame_w=int(float(box.pop("w"))),
            frame_h=int(float(box.pop("h"))),
            frame=frame,
            mask=mask,
        )
    except (KeyError, ValueError):
        return None
    if "c" in box:
        det.conf = float(box.pop("c"))
    det.extra = box
    return det
