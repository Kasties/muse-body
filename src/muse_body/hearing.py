"""Hearing: other players' voices, as VRChat plays them, written down by Muse Voice Transcribe.

What the PC plays (VRChat's voices included) is captured from the default speaker's loopback and
streamed to Muse Voice Transcribe's realtime endpoint in ENDPOINTING mode. The model finds where
each utterance ends, so there is no voice activity detection here; every finished utterance
waits for the next decision.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import threading
import time
import warnings
from dataclasses import dataclass

import numpy as np

from .config import Settings

RATE = 24_000  # PCM_24KHZ, the model's native rate
CHUNK = RATE * 80 // 1000  # 80 ms frames, as in Meta's examples
# An utterance still open after this long is music or a crowd, not someone finishing a sentence.
OPEN_SECONDS = 10.0


@dataclass(frozen=True)
class Heard:
    text: str
    t: float  # when the transcript was complete (time.time())


def to_pcm(samples: np.ndarray) -> bytes:
    """Float samples in -1..1 (frames x channels) -> signed 16-bit little-endian mono."""
    mono = samples.mean(axis=1) if samples.ndim == 2 else samples
    return (np.clip(mono, -1.0, 1.0) * 32767).astype("<i2").tobytes()


class Ears:
    """Streams the speaker loopback to Muse Voice Transcribe and keeps what it heard."""

    def __init__(self, settings: Settings, echo: bool = True):
        self.url = settings.base_url.replace("https://", "wss://", 1).rstrip("/") + "/asr/realtime"
        self.key, self.model = settings.api_key, settings.asr_model
        self.echo = echo
        self.error: str | None = None
        self._heard: list[Heard] = []
        self._open: dict[object, float] = {}  # turnId -> when its speech started
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._q: asyncio.Queue | None = None

    def start(self) -> "Ears":
        threading.Thread(target=self._capture, name="ears-capture", daemon=True).start()
        threading.Thread(target=lambda: asyncio.run(self._stream()), name="ears-asr", daemon=True).start()
        return self

    def take(self) -> list[Heard]:
        """Everything heard since the last call."""
        with self._lock:
            out, self._heard = self._heard, []
        return out

    def listening(self) -> bool:
        """Someone is mid-utterance: speech started and its transcript is not complete yet."""
        now = time.time()
        with self._lock:
            return any(now - t0 < OPEN_SECONDS for t0 in self._open.values())

    def wait_until_quiet(self, timeout: float = 5.0) -> None:
        """Let a speaker finish their sentence before the next look and decision."""
        deadline = time.time() + timeout
        while self.listening() and time.time() < deadline:
            time.sleep(0.1)

    def close(self) -> None:
        self._stop.set()
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._offer, None)

    def handshake(self) -> dict:
        return {"authorization": {"accessToken": f"Bearer {self.key}"}, "audioEncoding": "PCM_24KHZ",
                "model": self.model, "mode": "ENDPOINTING", "emitAudioProgress": False}

    def on_event(self, event: dict) -> None:
        """One server event. The text arrives with speechComplete, not with speechEnd, and turns
        can overlap, so state is kept per turnId."""
        kind = event.get("type")
        with self._lock:
            if kind == "speechStart":
                self._open[event.get("turnId")] = time.time()
            elif kind == "speechComplete":
                self._open.pop(event.get("turnId"), None)
                text = str(event.get("transcript") or "").strip()
                if text:
                    self._heard.append(Heard(text, time.time()))
                    if self.echo:
                        print(f"[ears] heard {text!r}")
            elif kind == "error":
                self.error = str(event.get("message"))
                print(f"[ears] {self.error}")

    def _capture(self) -> None:
        try:
            import soundcard as sc  # imported here: it sets up COM for this thread
            warnings.filterwarnings("ignore", category=sc.SoundcardRuntimeWarning)
            speaker = sc.default_speaker()
            mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
            print(f"[ears] listening to {speaker.name}")
            # The recorder returns 80 ms every 80 ms, silence included, so it paces the stream.
            with mic.recorder(samplerate=RATE, channels=1, blocksize=CHUNK) as rec:
                while not self._stop.is_set():
                    pcm = to_pcm(rec.record(numframes=CHUNK))
                    loop = self._loop
                    if loop is not None:
                        loop.call_soon_threadsafe(self._offer, pcm)
        except Exception as e:  # no output device, or the loop is gone at shutdown
            if not self._stop.is_set():
                self.error = f"capture: {e}"
                print(f"[ears] {self.error}")

    def _offer(self, pcm: bytes | None) -> None:
        """In the event loop: queue one frame; while disconnected only the last ~5 s are kept."""
        if self._q.full():
            self._q.get_nowait()
        self._q.put_nowait(pcm)

    async def _stream(self) -> None:
        import websockets

        self._q = asyncio.Queue(maxsize=64)
        self._loop = asyncio.get_running_loop()
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.url, open_timeout=30) as ws:
                    await ws.send(json.dumps(self.handshake()))
                    ack = json.loads(await ws.recv())
                    if "sessionId" not in ack:
                        raise RuntimeError(f"handshake refused: {ack}")
                    backoff = 1.0
                    while not self._q.empty():  # start from now, not from audio queued offline
                        self._q.get_nowait()
                    sender = asyncio.ensure_future(self._send(ws))
                    try:
                        async for message in ws:  # until the server closes the session
                            if isinstance(message, str):
                                self.on_event(json.loads(message))
                    finally:
                        sender.cancel()
            except Exception as e:  # refused, dropped, or the 60 min session limit: reconnect
                if not self._stop.is_set():
                    print(f"[ears] stream: {type(e).__name__}: {e}")
            with self._lock:
                self._open.clear()
            if not self._stop.is_set():
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _send(self, ws) -> None:
        while True:
            pcm = await self._q.get()
            if pcm is None:  # closing: end input and let the server flush what it has
                await ws.send(json.dumps({"type": "endStream"}))
                return
            await ws.send(pcm)


def main() -> None:
    ap = argparse.ArgumentParser(description="Print what Muse Voice Transcribe hears from the PC's "
                                             "audio output (VRChat's voices included).")
    ap.add_argument("--seconds", type=float, default=0.0, help="stop after this long (default: Ctrl+C)")
    args = ap.parse_args()
    ears = Ears(Settings.from_env()).start()
    deadline = time.time() + args.seconds if args.seconds else float("inf")
    try:
        while time.time() < deadline:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        ears.close()
        time.sleep(1.0)  # let the last transcript arrive


if __name__ == "__main__":
    main()
