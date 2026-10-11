"""Shared translation interfaces and provider routing."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class TranslationResult:
    translations: dict[str, str]
    errors: list[str] = field(default_factory=list)
    provider_used: str = ""


ProgressCallback = Callable[[int, int, str], None]


class BaseTranslator(ABC):
    name: str = "base"
    batch_size: int = 40

    @abstractmethod
    def translate_batch(self, texts: list[str]) -> list[str]:
        """Translate a list of English strings to Japanese. Same length as input."""

    def translate_entries(
        self,
        entries: dict[str, str],
        progress: ProgressCallback | None = None,
    ) -> TranslationResult:
        keys = list(entries.keys())
        values = [entries[k] for k in keys]
        out: dict[str, str] = {}
        errors: list[str] = []
        total = len(keys)
        done = 0

        for start in range(0, total, self.batch_size):
            chunk_keys = keys[start : start + self.batch_size]
            chunk_vals = values[start : start + self.batch_size]
            # Skip empty sources
            nonempty_idx = [i for i, v in enumerate(chunk_vals) if v.strip()]
            if not nonempty_idx:
                for k in chunk_keys:
                    out[k] = entries[k]
                done += len(chunk_keys)
                if progress:
                    progress(done, total, self.name)
                continue

            to_translate = [chunk_vals[i] for i in nonempty_idx]
            try:
                translated = self.translate_batch(to_translate)
                if len(translated) != len(to_translate):
                    raise ValueError(
                        f"翻訳件数不一致: expected {len(to_translate)}, got {len(translated)}"
                    )
            except Exception as exc:  # noqa: BLE001 — surface to UI
                errors.append(f"[{self.name}] バッチ失敗 ({start}-{start+len(chunk_keys)}): {exc}")
                # Fall through: leave those keys untranslated
                for i, k in enumerate(chunk_keys):
                    out[k] = ""
                done += len(chunk_keys)
                if progress:
                    progress(done, total, self.name)
                continue

            t_map = {nonempty_idx[j]: translated[j] for j in range(len(translated))}
            for i, k in enumerate(chunk_keys):
                if i in t_map:
                    out[k] = t_map[i]
                else:
                    out[k] = ""
            done += len(chunk_keys)
            if progress:
                progress(done, total, self.name)

        return TranslationResult(
            translations=out,
            errors=errors,
            provider_used=self.name,
        )


PROVIDER_GOOGLE = "Google翻訳"
PROVIDER_DEEPL = "DeepL"
PROVIDER_GEMINI = "Gemini"
PROVIDER_OPENAI = "OpenAI"

ALL_PROVIDERS = [PROVIDER_GOOGLE, PROVIDER_DEEPL, PROVIDER_GEMINI, PROVIDER_OPENAI]


def resolve_provider(selected: str, api_key: str) -> tuple[str, bool]:
    """
    Return (effective_provider, used_fallback).
    Falls back to Google when a key-requiring provider has no key.
    """
    key = (api_key or "").strip()
    if selected == PROVIDER_GOOGLE:
        return PROVIDER_GOOGLE, False
    if selected in (PROVIDER_DEEPL, PROVIDER_GEMINI, PROVIDER_OPENAI):
        if not key:
            return PROVIDER_GOOGLE, True
        return selected, False
    return PROVIDER_GOOGLE, True


def get_translator(
    provider: str,
    api_key: str = "",
    *,
    deepl_use_free: bool = True,
    gemini_model: str = "gemini-2.0-flash",
    openai_model: str = "gpt-4o-mini",
):
    from .deepl_client import DeepLTranslator
    from .gemini_client import GeminiTranslator
    from .google_client import GoogleTranslatorClient
    from .openai_client import OpenAITranslator

    effective, _ = resolve_provider(provider, api_key)
    if effective == PROVIDER_DEEPL:
        return DeepLTranslator(api_key=api_key, use_free=deepl_use_free)
    if effective == PROVIDER_GEMINI:
        return GeminiTranslator(api_key=api_key, model=gemini_model)
    if effective == PROVIDER_OPENAI:
        return OpenAITranslator(api_key=api_key, model=openai_model)
    return GoogleTranslatorClient()
