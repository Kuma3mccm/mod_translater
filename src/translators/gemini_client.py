"""Google Gemini translator."""

from __future__ import annotations

import json
import re

from google import genai
from google.genai import types

from .base import BaseTranslator

_SYSTEM = (
    "You are a professional Minecraft mod UI localizer. "
    "Translate English game UI / item / tooltip strings into natural Japanese. "
    "Keep Minecraft placeholders (%s, %d, %1$s, etc.) and section codes (§.) exactly. "
    "Do not add explanations. Return ONLY a JSON array of translated strings "
    "with the same length and order as the input array."
)


class GeminiTranslator(BaseTranslator):
    name = "Gemini"
    batch_size = 40

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        self.model = model
        self._client = genai.Client(api_key=api_key.strip())

    def translate_batch(self, texts: list[str]) -> list[str]:
        payload = json.dumps(texts, ensure_ascii=False)
        prompt = (
            f"{_SYSTEM}\n\nInput JSON array:\n{payload}\n\nOutput JSON array:"
        )
        response = self._client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
        raw = (response.text or "").strip()
        return _parse_json_array(raw, expected=len(texts))


def _parse_json_array(raw: str, expected: int) -> list[str]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if not m:
            raise ValueError(f"Gemini応答をJSON配列として解析できません: {raw[:200]}")
        data = json.loads(m.group(0))
    if not isinstance(data, list):
        raise ValueError("Gemini応答が配列ではありません")
    if len(data) != expected:
        raise ValueError(f"件数不一致: expected {expected}, got {len(data)}")
    return [str(x) for x in data]
