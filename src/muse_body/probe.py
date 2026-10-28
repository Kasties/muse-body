"""Check the API key and both model calls against one image, without touching VRChat."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from PIL import Image

from .agent import SYSTEM, Memory, parse_xy
from .config import Settings
from .meta_api import MetaClient, extract_json
from .sam_format import parse
from .steer import SteerParams, pick, steer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", type=Path, help="any screenshot, e.g. from VRChat")
    ap.add_argument("--phrase", default=None, help="segment this phrase instead of running the agent's decision")
    ap.add_argument("--goal", default="Find someone nearby, walk up to them and greet them.")
    args = ap.parse_args()

    api = MetaClient(Settings.from_env())
    img = Image.open(args.image)
    try:
        hint = None
        phrase = args.phrase
        if phrase is None:
            print("== Muse Spark decision ==")
            t = time.time()
            reply = api.see(img, SYSTEM, Memory().prompt(args.goal))
            print(f"({time.time() - t:.1f}s) {reply}")
            d = extract_json(reply)
            phrase, hint = d.get("target"), parse_xy(d.get("target_xy"))
            if not phrase:
                print("no target to ground")
                return
        print(f"== SAM 3.1: {phrase!r} hint={hint} ==")
        t = time.time()
        dets = parse(api.segment(img, phrase, raw=True))
        print(f"({time.time() - t:.1f}s) {len(dets)} detections")
        chosen = pick(dets, hint=hint)
        for d in dets:
            mark = "->" if d is chosen else "  "
            print(f"{mark} id={d.obj_id} box=({d.x1},{d.y1})-({d.x2},{d.y2}) conf={d.conf}")
        if chosen:
            cmd = steer(chosen, SteerParams())
            print(f"steer: bearing={cmd.bearing_deg:.1f} deg forward={cmd.forward} turn={cmd.turn:.2f} arrived={cmd.arrived}")
    finally:
        api.close()


if __name__ == "__main__":
    main()
