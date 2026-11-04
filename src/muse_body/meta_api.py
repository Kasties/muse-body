"""Thin client for the Meta Model API: Muse Spark (vision chat) and SAM 3.1 (segmentation)."""

from __future__ import annotations

import base64
import io
import json
import re
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from .config import Settings
from .sam_format import Detection, parse


class CallLog:
    """One JSON line per Meta Model API call (runs/<name>/api_calls.jsonl), so a run can be checked
    against the API's own records: when each call started, how long it took, which model and
    endpoint answered, and the ids and token usage the API sent back. The key is never written."""

    ID_HEADER = re.compile(r"(^|-)(request|trace|correlation)(-|$)|(^|-)id$", re.I)

    def __init__(self, path: Path | None):
        self.path = path
        self._lock = threading.Lock()

    def write(self, record: dict[str, Any]) -> None:
        if self.path is None:
            return
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    @classmethod
    def ids(cls, response: httpx.Response) -> dict[str, str]:
        """The response headers that identify the request on Meta's side."""
        return {k.lower(): v for k, v in response.headers.items() if cls.ID_HEADER.search(k)}


def to_data_url(image: Image.Image, quality: int = 85) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model reply (tolerates code fences and prose)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    if start < 0:
        raise ValueError(f"no JSON object in reply: {text[:200]!r}")
    obj, _ = json.JSONDecoder().raw_decode(candidate[start:])
    if not isinstance(obj, dict):
        raise ValueError("reply JSON is not an object")
    return obj


def _responses_text(payload: dict[str, Any]) -> str:
    """Collect output text from a non-streaming Responses API payload."""
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    parts: list[str] = []
    for item in payload.get("output", []) or []:
        for c in item.get("content", []) or []:
            if c.get("type") in ("output_text", "text") and isinstance(c.get("text"), str):
                parts.append(c["text"])
    return "\n".join(parts)


class MetaClient:
    def __init__(self, settings: Settings, timeout: float = 60.0, calls: CallLog | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.calls = calls or CallLog(None)
        self.http = httpx.Client(
            base_url=settings.base_url,
            headers={"Authorization": f"Bearer {settings.api_key}"},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self.http.close()

    def _post(self, path: str, body: dict[str, Any], model: str, **info: Any) -> dict[str, Any]:
        """POST to the API and log the call, whether it worked or not."""
        t0 = time.time()
        record: dict[str, Any] = {"t": t0, "api": path.strip("/"), "model": model, **info}
        try:
            r = self.http.post(path, json=body)
        except httpx.HTTPError as e:
            self.calls.write({**record, "seconds": round(time.time() - t0, 3), "error": type(e).__name__})
            raise
        record.update(seconds=round(time.time() - t0, 3), status=r.status_code, **CallLog.ids(r))
        try:
            payload = r.json()
        except ValueError:
            payload = {}
        if isinstance(payload, dict):
            for key in ("id", "model", "created", "usage"):
                if payload.get(key) is not None:
                    record["response_" + key if key in ("id", "model") else key] = payload[key]
        self.calls.write(record)
        r.raise_for_status()
        return payload

    def see(self, image: Image.Image, system: str, prompt: str, max_tokens: int = 4096,
            reasoning_effort: str = "low") -> str:
        """Ask Muse Spark about one frame; returns the reply text.

        Muse Spark always reasons and max_tokens covers reasoning too: one decision
        spends 600-1000 reasoning tokens, so a 1024 cap can leave the answer empty.
        """
        url = to_data_url(image)
        body = {
            "model": self.settings.model,
            "max_tokens": max_tokens,
            "reasoning_effort": reasoning_effort,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": url}},
                    ],
                },
            ],
        }
        payload = self._post("/chat/completions", body, self.settings.model,
                             image_kb=round(len(url) * 3 / 4 / 1024, 1), prompt_chars=len(system) + len(prompt))
        return payload["choices"][0]["message"]["content"] or ""

    def segment(self, image: Image.Image, phrase: str, raw: bool = False) -> list[Detection] | str:
        """Find every instance of a short noun phrase with SAM 3.1."""
        url = to_data_url(image)
        body = {
            "model": self.settings.sam_model,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": phrase},
                        {"type": "input_image", "image_url": url},
                    ],
                }
            ],
            "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"},
            "stream": False,
        }
        payload = self._post("/responses", body, self.settings.sam_model, phrase=phrase,
                             image_kb=round(len(url) * 3 / 4 / 1024, 1))
        text = _responses_text(payload)
        return text if raw else parse(text)
