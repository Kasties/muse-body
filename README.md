# muse-body

An embodied agent for VRChat built on Meta's models. Ask it for something, out loud or in
VRChat's chatbox, and it answers, finds the thing, picks it up and brings it to you. It moves
with a virtual gamepad, the way a player does.

**Demo video (3 min):** link added with the submission on Nov 4.

Muse Spark looks at the first-person view and picks an intention. SAM 3.1 finds the chosen
target in the frame. A small controller turns the box into movement on a virtual Xbox gamepad,
then the loop repeats. Muse Voice Transcribe writes down what people say to it. OSC carries the
chatbox and avatar parameters, and VRChat's OSC output comes back as body senses.

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

All three run through the Meta Model API (`https://api.meta.ai/v1` by default, `MUSE_BASE_URL` in
`.env`). No other model is used: steering, the scan and the errand bookkeeping are plain code.

| Model | Endpoint | What it does here |
|---|---|---|
| Muse Spark 1.3 | `POST /chat/completions` (one JPEG frame + text) | Picks the next intention (approach, look around, grab, give, say, wait, …) with a target phrase, a point on the frame and what to say; reads chat bubbles and nameplates; picks the real object among SAM's numbered matches; checks the HUD after a grab; sets the avatar's mood |
| SAM 3.1 | `POST /responses` (a noun phrase + one JPEG frame) | Boxes the target phrase in every frame of a move, so steering works from fresh boxes; boxes the people in view at every decision and at every step of a scan |
| Muse Voice Transcribe | `wss /asr/realtime` (16-bit PCM, 24 kHz, endpointing) | Writes down what people say near the avatar, one finished utterance at a time |

## What it has done live

Each run below is in [`demo_runs/`](demo_runs) with its log, the frames the models were sent,
and a table of the API calls it made (see [Logged runs and API calls](#logged-runs-and-api-calls)).

- **Voice errand (Nov 4, café world, the demo video):** the requester said "Hello Muse, how are
  you doing?" and then asked out loud for the café menu. It answered in chat, turned 180° until
  SAM 3.1 matched two menus, and Muse Spark picked the clipboard on the counter over the board on
  the wall. It walked up, grabbed it, checked the HUD's "Drop" prompt to see that the hand held
  it, turned back to find the requester and handed it over with "Here's the menu you asked for!"
  Asked for a joke, it told one. 11 decisions in 2 minutes:
  [`demo_runs/demo6_take`](demo_runs/demo6_take/CALLS.md).
- **Typed errand (Nov 2, café world):** the same errand from a chat message, "can you bring me
  the menu?": [`demo_runs/errand3`](demo_runs/errand3/CALLS.md).
- **Greeting (Oct 29, NPC world):** found a person walking around, followed them, then said
  "Hi there!" with a thumbs-up and waved: [`demo_runs/npc_run6`](demo_runs/npc_run6/CALLS.md).
- **Not yet:** a pen from the tray under the café whiteboard. From across the room a pen is
  about 5 pixels wide and SAM 3.1 does not find it. After two full circles the agent now says
  it could not find one (checked offline).

## Logged runs and API calls

Every run writes a folder, and nothing in it is edited afterwards:

| File | What it holds |
|---|---|
| `00001.jpg`, … | Each frame that was sent to Muse Spark or SAM 3.1, as captured from the VRChat window (1280×720) |
| `events.jsonl` | One line per step event, with its Unix time `t`, the frame, and what the models returned: Muse Spark's observation, reasoning, intent, target, reply and gesture; SAM's boxes and confidences; the words Muse Voice Transcribe heard |
| `run.json` | The goal and the start time |
| `api_calls.jsonl` | One line per API call, written by the client as each call finishes (runs from Nov 4 on, below) |
| `CALLS.md` | The calls as a table, made by `muse-calls <run folder>` |

**`api_calls.jsonl`** (from commit 096bee3 on) records per call: when it started (`t`, Unix
seconds), the endpoint and model, how long it took, the HTTP status or the error, the size of
the image and prompt sent, and what the API returned to identify the call: the response `id`,
`created`, token `usage` and any request-id headers. Muse Voice Transcribe adds a line per
realtime session, with the `sessionId` the server assigned, and a line per finished utterance
with its transcript. The API key is never written (a test checks this). These ids, times and
counts can be checked against the Meta developer dashboard's usage page, and the replay video
shows the calls in its bottom-right corner as they finish.

**The runs in `demo_runs/`** were recorded before that log existed, so their `CALLS.md` is
derived from `events.jsonl`: each logged event comes from one code path in
[`agent.py`](src/muse_body/agent.py), and [`calls.py`](src/muse_body/calls.py) lists the calls
that path makes (a decision is one Muse Spark call plus one SAM 3.1 "character" call, a scan
step is one or two SAM calls plus a Muse Spark pick when there are matches, and so on). Derived
rows are marked as such: they carry no request ids or token counts, failed calls are missing,
and the counts are lower bounds. The frame named in each row is the image that call was sent.

| Run | When (UTC) | Muse Spark | SAM 3.1 | Muse Voice Transcribe |
|---|---|---|---|---|
| [demo6_take](demo_runs/demo6_take/CALLS.md), voice errand | 2026-11-03 23:39–23:41 | 13 | 33 | 4 utterances |
| [errand3](demo_runs/errand3/CALLS.md), typed errand | 2026-11-02 02:08–02:10 | 15 | 52 | not built yet |
| [npc_run6](demo_runs/npc_run6/CALLS.md), greeting | 2026-10-29 00:56–00:57 | 6 | 26 | not built yet |

## Run it yourself

It runs on one Windows PC, next to the VRChat desktop client. There is no phone app and nothing
to host: the models are called through the Meta Model API. Steps 1–3 take a few minutes and
check the install and the model calls without VRChat. Steps 4–6 run the agent in VRChat.

You need:

- Windows 10 or 11, and Python 3.10 or newer
- A Meta Model API key with access to Muse Spark 1.3, SAM 3.1 and Muse Voice Transcribe
- For the VRChat run: VRChat (free on Steam) in desktop mode with an account for the agent, and
  a second person in the same instance to talk to it, such as a friend or your own second
  account on another PC

### 1. Install

In PowerShell:

```powershell
git clone https://github.com/Kasties/muse-body.git
cd muse-body
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,replay]"
```

If PowerShell refuses to run `Activate.ps1`, run `Set-ExecutionPolicy -Scope Process RemoteSigned`
and activate again.

The virtual gamepad (vgamepad) needs the ViGEmBus driver. If the driver is missing,
`pip install` opens its installer: accept it for the VRChat run. To install without the driver,
set `$env:VGAMEPAD_SKIP_VIGEMBUS_INSTALL = "true"` before `pip install`. The checks in step 3
work without it, and so does `muse-body --input osc`, minus grabbing and hand signs. You can add
the driver later from its [releases page](https://github.com/nefarius/ViGEmBus/releases).

### 2. Add your API key

```powershell
copy .env.example .env
notepad .env
```

Set `MODEL_API_KEY=` to your key and save. Run every command from the repo folder, because they
read `.env` from the current folder.

### 3. Check the models without VRChat

```powershell
pytest                                # offline tests: no key, no VRChat
muse-probe photo.jpg --phrase person  # SAM 3.1 boxes every person in the image
muse-probe photo.jpg                  # Muse Spark decides what to do, SAM 3.1 finds its target
muse-hear --seconds 30                # play a video with speech: prints each sentence it hears
```

`photo.jpg` stands for any image, such as a VRChat screenshot or a photo of people in a room.
`muse-hear` writes down whatever the PC plays on its default output device.

### 4. Set up VRChat

1. Start VRChat in desktop mode, windowed, so the terminal stays visible next to it.
2. Turn on OSC: open the Action Menu (R), then Options → OSC → Enabled. The chatbox and the avatar
   parameters go over OSC.
3. Meet your second person in a private or friends instance. The demo used the café world
   [咖啡厅 v1.31](https://vrchat.com/home/world/wrld_30251b70-8af3-4280-9d46-143e926da217),
   where the menus on the counter can be picked up.

### 5. Run the agent

```powershell
muse-body --dry-run --steps 3
muse-body --steps 40 --goal "Hang around near people and help anyone who asks you for something."
```

The dry run makes real model calls on the VRChat window but prints the gamepad and chat output
instead of sending it. For the real run, click into the VRChat window right after starting it:
VRChat ignores the gamepad while another window has focus, so the agent waits until VRChat is
in front.

Then, as the second person, stand where it can see you and say or type:

- **"Hi, how are you?"** It answers in the chatbox.
- **"Can you bring me a menu?"** (in the café) It answers, turns until it finds a menu on the
  counter, walks up and grabs it, turns back to find you, walks over and hands it to you.

Each decision takes about 5 s, and its chatbox shows typing dots meanwhile. Hearing streams
everything the PC plays, so pause videos and music, or add `--no-hear` to turn hearing off. Stop
with Ctrl+C. Without `--goal` the agent looks for someone, walks up and greets them, and
`--steps` defaults to 20.

### 6. Watch the replay

Each run saves its frames, `events.jsonl`, `api_calls.jsonl` and `run.json` to
`runs\<timestamp>\` (or to `--log-dir`). To turn a run into a 1080p video with the SAM boxes, people boxes, Muse Spark's pointing hint, its observation
and reasoning, and the actions it took drawn in:

```powershell
muse-replay runs\<timestamp>             # writes runs\<timestamp>\replay.mp4
muse-replay runs\<timestamp> --still 12  # one frame as a PNG, for checking
```

To list the API calls a run made (from its `api_calls.jsonl`, see
[Logged runs and API calls](#logged-runs-and-api-calls)):

```powershell
muse-calls runs\<timestamp>              # writes runs\<timestamp>\CALLS.md
```

### If something goes wrong

| You see | What to do |
|---|---|
| `MODEL_API_KEY is not set` | Create `.env` (step 2) and run from the repo folder |
| `virtual gamepad unavailable` | Install the [ViGEmBus driver](https://github.com/nefarius/ViGEmBus/releases), or run with `--input osc`: it then walks, turns and talks, but cannot pick things up or show hand signs |
| `waiting for the VRChat window to be focused` | Click into VRChat; the agent looks for a window titled "VRChat" |
| `[senses] OSC output not available on 9001` | Another OSC app holds the port; close it. The agent runs on without body senses |
| Nothing shows in its chatbox | Turn on OSC in VRChat (step 4) |
| It answers a video or music | Pause other audio, or run with `--no-hear` |

## How it works

### One step, call by call

1. **Capture.** The VRChat window is captured and scaled to 1280×720.
2. **Decide (~5 s).** Muse Spark 1.3 gets that frame as a JPEG (quality 85) with the goal, a short
   memory of recent steps, the errand in progress, the body senses and anything heard since the
   last step (`reasoning_effort: low`, `max_tokens: 4096`). It replies with JSON: what it sees,
   why, an intent, a target phrase, a point on the frame (0–1000), what to say or reply, a
   gesture and a mood. At the same time SAM 3.1 boxes every "character" in the frame, so Muse
   Spark's point can be snapped onto a real person.
3. **Act.** The intent runs as plain code:
   - **approach / give:** each frame, SAM 3.1 boxes the target phrase (shorter tails of the
     phrase if the full one finds nothing). The box's centre gives a bearing from the 70°
     vertical field of view; the body turns by it and walks. It has arrived when the box is 40%
     of the frame height for a person, or 22% for an object to pick up. At most 12 frames.
   - **look_around:** turn in 45° steps (30° while carrying) and run only SAM 3.1 at each, about
     1 s a step, until a person, or the target object, is in view.
   - **grab:** approach, put the object under the screen-centre crosshair with SAM boxes, press
     grab, then ask Muse Spark whether the HUD shows VRChat's "Drop" prompt.
   - **say / wave / wait:** chatbox text over OSC and hand signs on the gamepad.
4. **Log.** Every frame used is saved with its `events.jsonl` line, and every API call with its
   `api_calls.jsonl` line. Then the loop starts again at step 1.

### Errands

People ask the agent for things the way players talk: in VRChat's chatbox, or out loud. Muse
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

### Hearing

While the agent runs, what the PC plays (VRChat's voices included) streams to Muse Voice
Transcribe's realtime endpoint, which finds where each sentence ends and writes it down. Each
finished sentence goes into the next decision under "Heard", and Muse Spark treats it like a
chat bubble: it answers in chat and takes a request on as the errand. Talk not meant for it,
like a video playing on the PC, gets no answer. When someone is mid-sentence, the agent waits up
to 5 s for them to finish before it looks and decides.

It listens to the default output device, so it streams and transcribes everything the PC plays:
turn VRChat's world volume down and keep voices up. Streaming costs $0.18 per hour of audio.

### Avatar state

The agent sets avatar parameters over OSC so people next to it can see what it is doing. Add
them to the avatar's Expression Parameters (synced) and drive animations from them:

| Parameter | Type | Meaning |
|---|---|---|
| `Thinking` | Bool | true while Muse Spark decides (~5 s); the chatbox shows typing dots meanwhile |
| `Mood` | Int | 0 neutral, 1 happy, 2 curious, 3 confused, 4 surprised; Muse Spark picks one per decision |

Other custom bool parameters that turn true (for example a head-pat contact receiver) reach
Muse Spark as something the body felt. An avatar without these parameters works too.

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
| `src/muse_body/replay.py` | Run log → annotated replay video, with the API calls as they finish |
| `src/muse_body/calls.py` | `muse-calls`: a run's API calls as a table (`CALLS.md`), from `api_calls.jsonl` or derived from `events.jsonl` |
| `src/muse_body/probe.py` | `muse-probe`: one image through Muse Spark and SAM 3.1, to check the setup |
| `tests/` | Offline tests with stand-ins for the models, the gamepad and VRChat |
| `demo_runs/` | The logged live runs shown in the demo video: frames, `events.jsonl`, `CALLS.md` |

## Limits

- VRChat desktop on Windows only, and its window has to stay in front.
- Small, thin objects far away (pens) are below what SAM 3.1 finds in a 1280×720 frame.
- A decision takes about 5 s, so the agent reacts at walking pace.
- Hearing takes the PC's whole audio output, not only VRChat's.

## Credits

The Muse avatar the agent wears was modeled by Kasties during the hackathon. The voice-over in
the demo video and the requester's voice in the voice errand are Kasties too. The live runs took
place in VRChat community worlds; the café is 咖啡厅 v1.31. The worlds and the other avatars
belong to their creators.

## License

MIT, see [LICENSE](LICENSE).
