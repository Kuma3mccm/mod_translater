"""Minecraft format placeholder and color-code validation."""

from __future__ import annotations

import re
from typing import Iterable

# %s, %d, %f, %%, positional %1$s, etc.
_PLACEHOLDER_RE = re.compile(
    r"%%|%(?:\d+\$)?[-#+ 0,(]*\d*(?:\.\d+)?[bBhHsScCdoxXeEfgGaAtT%n]|%s|%d"
)
_SECTION_RE = re.compile(r"§.")


def extract_placeholders(text: str) -> list[str]:
    return _PLACEHOLDER_RE.findall(text or "")


def extract_section_codes(text: str) -> list[str]:
    return _SECTION_RE.findall(text or "")


def validate_translation(source: str, translated: str) -> list[str]:
    """Return human-readable warnings when placeholders/codes are lost."""
    warnings: list[str] = []
    src_ph = extract_placeholders(source)
    dst_ph = extract_placeholders(translated)
    if sorted(src_ph) != sorted(dst_ph):
        warnings.append(
            f"プレースホルダ不一致: 原文={src_ph} / 訳文={dst_ph}"
        )

    src_sec = extract_section_codes(source)
    dst_sec = extract_section_codes(translated)
    if sorted(src_sec) != sorted(dst_sec):
        warnings.append(
            f"書式コード(§)不一致: 原文={src_sec} / 訳文={dst_sec}"
        )
    return warnings


def validate_batch(
    pairs: Iterable[tuple[str, str, str]],
) -> dict[str, list[str]]:
    """Validate (key, source, translated) pairs. Returns key -> warnings."""
    result: dict[str, list[str]] = {}
    for key, source, translated in pairs:
        warns = validate_translation(source, translated)
        if warns:
            result[key] = warns
    return result
