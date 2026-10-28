"""Thin client for the Meta Model API: Muse Spark (vision chat) and SAM 3.1 (segmentation)."""

from __future__ import annotations

import base64
import io
import json
import re
from typing import Any

import httpx
from PIL import Image

from .config import Settings
from .sam_format import Detection, parse


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
    def __init__(self, settings: Settings, timeout: float = 60.0):
        self.settings = settings
        self.http = httpx.Client(
            base_url=settings.base_url,
            headers={"Authorization": f"Bearer {settings.api_key}"},
            timeout=timeout,
        )

    def close(self) -> None:
        self.http.close()

    def see(self, image: Image.Image, system: str, prompt: str, max_tokens: int = 4096,
            reasoning_effort: str = "low") -> str:
        """Ask Muse Spark about one frame; returns the reply text.

        Muse Spark always reasons and max_tokens covers reasoning too: one decision
        spends 600-1000 reasoning tokens, so a 1024 cap can leave the answer empty.
        """
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
                        {"type": "image_url", "image_url": {"url": to_data_url(image)}},
                    ],
                },
            ],
        }
        r = self.http.post("/chat/completions", json=body)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""

    def segment(self, image: Image.Image, phrase: str, raw: bool = False) -> list[Detection] | str:
        """Find every instance of a short noun phrase with SAM 3.1."""
        body = {
            "model": self.settings.sam_model,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": phrase},
                        {"type": "input_image", "image_url": to_data_url(image)},
                    ],
                }
            ],
            "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"},
            "stream": False,
        }
        r = self.http.post("/responses", json=body)
        r.raise_for_status()
        text = _responses_text(r.json())
        return text if raw else parse(text)
