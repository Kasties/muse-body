# muse-body

An embodied agent for VRChat built on Meta's models. Muse Spark looks at the first-person
view and picks an intention. SAM 3.1 finds the chosen target in the frame. A small
controller turns the box into movement on a virtual Xbox gamepad, the way a player moves,
then the loop repeats. Muse Voice Transcribe writes down what people say to it. OSC carries
the chatbox and avatar parameters, and VRChat's OSC output comes back as body senses.

```
voices ──► Muse Voice Transcribe ──► words ──┐
                                             ▼
 frame ─────────────────────────────► Muse Spark 1.3 ──► intent + target phrase
   ▲                                                          │
   │                                                          ▼
   └───────────────────── gamepad body ◄── steer ◄── SAM 3.1 boxes
```

Built for the Meta Global AI Developer Hackathon (Indie track). **All code in this repository
was written during the hackathon, from Oct 28 2026 onward.** No prior code is included, and the
commit history shows the build step by step.

## Meta models in the loop

All three run through the Meta Model API; no other model is used.

| Model | What it does here |
|---|---|
| Muse Spark 1.3 | Looks at each first-person frame and picks the next intention (approach, look around, grab, give, say, …) with a target phrase and a point; reads chat bubbles and nameplates; picks the real object among SAM's matches; sets the avatar's mood |
| SAM 3.1 | Finds the target phrase again in every frame of a move, so steering works from fresh boxes; finds the people in view at every decision |
| Muse Voice Transcribe | Writes down what people say near the avatar, one finished sentence at a time (realtime, turn detection) |

## What it has done live

- **Greeting (Oct 29, NPC world):** found a person, walked up, stayed, said "Hi there!" with a
  thumbs-up and waved.
- **Errand (Nov 2, café world):** a player typed "can you bring me the menu?" It answered, found
  the menu on the counter rather than the menu boards on the wall, grabbed it, turned to find
  the player, walked over and handed it to them with "Here's the menu!"
- **Not yet:** a pen from the tray under the café whiteboard. From across the room a pen is
  about 5 pixels wide and SAM 3.1 does not find it. After two full circles the agent now says
  it could not find one (checked offline).

## Setup

1. Python 3.10+, then `pip install -e ".[dev]"` (with `VGAMEPAD_SKIP_VIGEMBUS_INSTALL=true` set).
2. The [ViGEmBus](https://github.com/nefarius/ViGEmBus/releases) driver for the virtual gamepad.
3. Copy `.env.example` to `.env` and set `MODEL_API_KEY`.
4. VRChat on desktop, windowed, with OSC enabled (Action Menu → Options → OSC → Enabled).
   VRChat ignores gamepad input while its window is not focused, so keep it in front.

## Run

```
muse-probe screenshot.png --phrase person   # check both model calls on one image
muse-body --dry-run --steps 5               # real models, OSC printed instead of sent
muse-body --goal "Walk up to someone and say hello"
```

Each run writes its frames, `events.jsonl` and `run.json` to `runs/<timestamp>/`. To turn a run into
a 1080p replay with the SAM boxes, people boxes, Muse Spark's pointing hint, its observation and
reasoning, and the actions it took drawn in:

```
pip install -e ".[replay]"
muse-replay runs/<timestamp>                # writes runs/<timestamp>/replay.mp4
muse-replay runs/<timestamp> --still 12     # one frame as a PNG, for checking
```

## Errands

People ask the agent for things the way players talk: by typing in VRChat's chatbox. Muse
Spark reads the bubble above their head (and the name on their nameplate), answers in chat,
and works the request off over the next decisions: it turns until SAM 3.1 finds the object,
walks up and grabs it, turns to find the person again, walks over and hands it to them.

While turning, SAM 3.1 proposes and Muse Spark picks. SAM matches pictures of the object too:
"menu" finds the menu boards on a café wall as well as the menu on the counter. So every match
is numbered on the frame, and Muse Spark names what each box holds and says which number is the
object itself, or none. On logged café frames that check was right 12 times out of 12 (8 of 12
before Muse Spark had to name every box). The turn stops only on the real object and faces it.
If Muse Spark's own name for the object finds nothing on the way there, the same check runs
again with the phrase the scan found it with. After looking all around twice without finding
it, the agent tells the person it could not find it and drops the errand.

```
muse-body --goal "Hang around near people and help anyone who asks you for something."
```

## Hearing

People can also just talk to it. While the agent runs, what the PC plays (VRChat's voices
included) streams to Muse Voice Transcribe's realtime endpoint, which finds where each sentence
ends and writes it down. Each finished sentence goes into the next decision under "Heard", and
Muse Spark treats it like a chat bubble: it answers in chat and takes a request on as the errand.
Talk not meant for it, like a video playing on the PC, gets no answer. When someone is
mid-sentence, the agent waits up to 5 s for them to finish before it looks and decides.

```
muse-hear              # print what it hears, to check the setup
muse-body --no-hear    # without hearing
```

It listens to the default output device, so everything the PC plays is streamed and
transcribed while it runs: pause videos and music, and turn VRChat's world volume down while
keeping voices up. Streaming costs $0.18 per hour of audio.

## Avatar state

The agent sets avatar parameters over OSC so people next to it can see what it is doing. Add
them to the avatar's Expression Parameters (synced) and drive animations from them:

| Parameter | Type | Meaning |
|---|---|---|
| `Thinking` | Bool | true while Muse Spark decides (~5 s); the chatbox shows typing dots meanwhile |
| `Mood` | Int | 0 neutral, 1 happy, 2 curious, 3 confused, 4 surprised; Muse Spark picks one per decision |

Other custom bool parameters that turn true (for example a head-pat contact receiver) reach
Muse Spark as something the body felt.

## Layout

| File | What it does |
|---|---|
| `src/muse_body/meta_api.py` | Meta Model API client: Muse Spark chat with an image, SAM 3.1 via Responses |
| `src/muse_body/sam_format.py` | Parser for SAM 3.1's `<\|box;...\|><\|mask;...\|>` output |
| `src/muse_body/steer.py` | Box → bearing → turn/walk command, arrival check |
| `src/muse_body/body.py` | Virtual gamepad (calibrated turns, walking, grab, drop, gestures) and OSC (chatbox, avatar parameters) |
| `src/muse_body/senses.py` | VRChat's OSC output as body senses: speed, grounded, touches |
| `src/muse_body/hearing.py` | The PC's audio output → Muse Voice Transcribe (realtime, turn detection) → what was said |
| `src/muse_body/capture.py` | VRChat window capture |
| `src/muse_body/agent.py` | The decide → ground → move loop with a short memory |
| `src/muse_body/replay.py` | Run log → annotated replay video |
| `src/muse_body/probe.py` | `muse-probe`: one image through Muse Spark and SAM 3.1, to check the setup |

## Limits

- VRChat desktop on Windows only, and its window has to stay in front.
- Small, thin objects far away (pens) are below what SAM 3.1 finds in a 1280×720 frame.
- A decision takes about 5 s, so the agent reacts at walking pace.
- Hearing takes the PC's whole audio output, not only VRChat's.

## Credits

The live runs took place in VRChat community worlds; the café is 咖啡厅 v1.31. The worlds and
avatars belong to their creators.

## License

MIT, see [LICENSE](LICENSE).
