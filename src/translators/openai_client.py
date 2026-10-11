"""OpenAI translator."""

from __future__ import annotations

import json
import re

from openai import OpenAI

from .base import BaseTranslator

_SYSTEM = (
    "You are a professional Minecraft mod UI localizer. "
    "Translate English game UI / item / tooltip strings into natural Japanese. "
    "Keep Minecraft placeholders (%s, %d, %1$s, etc.) and section codes (§.) exactly. "
    "Do not add explanations. Return ONLY a JSON array of translated strings "
    "with the same length and order as the input array."
)


class OpenAITranslator(BaseTranslator):
    name = "OpenAI"
    batch_size = 40

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self.model = model
        self._client = OpenAI(api_key=api_key.strip())

    def translate_batch(self, texts: list[str]) -> list[str]:
        payload = json.dumps(texts, ensure_ascii=False)
        response = self._client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM},
                {
                    "role": "user",
                    "content": (
                        'Return a JSON object: {"translations": [...]} '
                        f"for this input array:\n{payload}"
                    ),
                },
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
        return _parse_translations(raw, expected=len(texts))


def _parse_translations(raw: str, expected: int) -> list[str]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}|\[.*\]", raw, re.DOTALL)
        if not m:
            raise ValueError(f"OpenAI応答を解析できません: {raw[:200]}")
        data = json.loads(m.group(0))

    if isinstance(data, dict):
        for key in ("translations", "result", "items"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
        else:
            # single-key dict whose value is list
            lists = [v for v in data.values() if isinstance(v, list)]
            if len(lists) == 1:
                data = lists[0]
            else:
                raise ValueError("OpenAI応答に translations 配列がありません")

    if not isinstance(data, list):
        raise ValueError("OpenAI応答が配列ではありません")
    if len(data) != expected:
        raise ValueError(f"件数不一致: expected {expected}, got {len(data)}")
    return [str(x) for x in data]
