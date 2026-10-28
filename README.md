# muse-body

An embodied agent for VRChat built on Meta's models. Muse Spark looks at the first-person
view and picks an intention. SAM 3.1 finds the chosen target in the frame. A small
controller turns the box into movement over VRChat's OSC input, then the loop repeats.

```
frame ──► Muse Spark 1.3 ──► intent + target phrase
  ▲                               │
  │                               ▼
  └──── OSC body ◄── steer ◄── SAM 3.1 boxes
```

Built for the Meta Global AI Developer Hackathon (Indie track). **All code in this repository
was written during the hackathon, from Oct 28 2026 onward.** No prior code is included.

## Setup

1. Python 3.10+, then `pip install -e ".[dev]"`.
2. Copy `.env.example` to `.env` and set `MODEL_API_KEY`.
3. VRChat on desktop, windowed, with OSC enabled (Action Menu → Options → OSC → Enabled).

## Run

```
muse-probe screenshot.png --phrase person   # check both model calls on one image
muse-body --dry-run --steps 5               # real models, OSC printed instead of sent
muse-body --goal "Walk up to someone and say hello"
```

Each run writes frames and `events.jsonl` to `runs/<timestamp>/`.

## Layout

| File | What it does |
|---|---|
| `src/muse_body/meta_api.py` | Meta Model API client: Muse Spark chat with an image, SAM 3.1 via Responses |
| `src/muse_body/sam_format.py` | Parser for SAM 3.1's `<\|box;...\|><\|mask;...\|>` output |
| `src/muse_body/steer.py` | Box → bearing → turn/walk command, arrival check |
| `src/muse_body/body.py` | VRChat OSC: axes, jump, chatbox, emotes |
| `src/muse_body/capture.py` | VRChat window capture |
| `src/muse_body/agent.py` | The decide → ground → move loop with a short memory |

## License

MIT
