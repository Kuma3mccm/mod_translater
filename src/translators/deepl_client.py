"""DeepL API translator."""

from __future__ import annotations

import deepl

from .base import BaseTranslator


class DeepLTranslator(BaseTranslator):
    name = "DeepL"
    batch_size = 40

    def __init__(self, api_key: str, use_free: bool = True) -> None:
        kwargs: dict = {"auth_key": api_key.strip()}
        if use_free:
            kwargs["server_url"] = "https://api-free.deepl.com"
        self._translator = deepl.Translator(**kwargs)

    def translate_batch(self, texts: list[str]) -> list[str]:
        # DeepL accepts list and returns list of Result
        results = self._translator.translate_text(
            texts,
            source_lang="EN",
            target_lang="JA",
            preserve_formatting=True,
        )
        if not isinstance(results, list):
            results = [results]
        return [r.text for r in results]
