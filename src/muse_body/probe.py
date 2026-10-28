"""Check the API key and both model calls against one image, without touching VRChat."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from .config import Settings
from .meta_api import MetaClient
from .sam_format import parse


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", type=Path, help="any screenshot, e.g. from VRChat")
    ap.add_argument("--phrase", default="person")
    args = ap.parse_args()

    api = MetaClient(Settings.from_env())
    img = Image.open(args.image)
    try:
        print("== Muse Spark ==")
        print(api.see(img, "Describe the scene briefly.", "What do you see?"))
        print(f"== SAM 3.1: {args.phrase!r} ==")
        raw = api.segment(img, args.phrase, raw=True)
        print(raw[:600] + ("..." if len(raw) > 600 else ""))
        for d in parse(raw):
            print(f"  id={d.obj_id} box=({d.x1},{d.y1})-({d.x2},{d.y2}) conf={d.conf} frame={d.frame_w}x{d.frame_h}")
    finally:
        api.close()


if __name__ == "__main__":
    main()
