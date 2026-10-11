"""Key-free Google Translate (with free fallbacks if Google is rate-limited)."""

from __future__ import annotations

import time

import translators as ts
from deep_translator import MyMemoryTranslator
from deep_translator.exceptions import TooManyRequests

from .base import BaseTranslator, ProgressCallback, TranslationResult

_MAX_CHARS = 4500


class GoogleTranslatorClient(BaseTranslator):
    name = "Google翻訳"
    batch_size = 5

    def __init__(
        self,
        delay_sec: float = 0.35,
        rate_limit_wait: float = 5.0,
        max_retries: int = 4,
    ) -> None:
        self.delay_sec = delay_sec
        self.rate_limit_wait = rate_limit_wait
        self.max_retries = max_retries
        self._mymemory = MyMemoryTranslator(source="en-US", target="ja-JP")
        self._engine_used = "google"

    def translate_batch(self, texts: list[str]) -> list[str]:
        return [self._translate_one(t) if (t or "").strip() else t for t in texts]

    def translate_entries(
        self,
        entries: dict[str, str],
        progress: ProgressCallback | None = None,
    ) -> TranslationResult:
        keys = list(entries.keys())
        out: dict[str, str] = {}
        errors: list[str] = []
        total = len(keys)

        for i, key in enumerate(keys):
            text = entries[key]
            if not (text or "").strip():
                out[key] = ""
            else:
                try:
                    out[key] = self._translate_one(text)
                except Exception as exc:  # noqa: BLE001
                    out[key] = ""
                    errors.append(f"[{self.name}] {key}: {exc}")
            if progress:
                progress(i + 1, total, self.name)
            if self.delay_sec:
                time.sleep(self.delay_sec)

        label = self.name
        if self._engine_used != "google":
            label = f"{self.name}（{self._engine_used}フォールバック）"

        return TranslationResult(
            translations=out,
            errors=errors,
            provider_used=label,
        )

    def _translate_one(self, text: str) -> str:
        text = text.strip()
        if not text:
            return text
        if len(text) > _MAX_CHARS:
            text = text[:_MAX_CHARS]

        last_exc: Exception | None = None

        # 1) Google via translators (more reliable than deep-translator scrape)
        for attempt in range(self.max_retries):
            try:
                result = ts.translate_text(
                    text,
                    translator="google",
                    from_language="en",
                    to_language="ja",
                )
                if result:
                    self._engine_used = "google"
                    return str(result)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(self.rate_limit_wait * (1.3**attempt))

        # 2) MyMemory free API (no key) as last resort
        for attempt in range(3):
            try:
                result = self._mymemory.translate(text)
                if result:
                    self._engine_used = "MyMemory"
                    return str(result)
            except TooManyRequests as exc:
                last_exc = exc
                time.sleep(self.rate_limit_wait * (attempt + 1))
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(1.0 * (attempt + 1))

        raise RuntimeError(f"Google翻訳失敗: {last_exc}") from last_exc
