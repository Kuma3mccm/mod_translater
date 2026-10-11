"""Parse and serialize Minecraft language files (JSON and legacy .lang)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LangFile:
    """One language file discovered inside a JAR."""

    path: str  # zip-internal path, e.g. assets/foo/lang/en_us.json
    fmt: str  # "json" | "lang"
    locale: str  # e.g. en_us
    modid: str
    flat: dict[str, str] = field(default_factory=dict)
    was_nested: bool = False


_LANG_LINE_RE = re.compile(r"^([^#=\s][^=]*)=(.*)$")


def detect_modid(path: str) -> str:
    parts = path.replace("\\", "/").split("/")
    if len(parts) >= 3 and parts[0] == "assets":
        return parts[1]
    return "unknown"


def detect_locale(path: str) -> str:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    if name.endswith(".json"):
        return name[: -len(".json")]
    if name.endswith(".lang"):
        return name[: -len(".lang")]
    return name


def flatten_json(data: Any, prefix: str = "") -> dict[str, str]:
    """Flatten nested JSON objects into dotted keys. Non-string leaves become strings."""
    flat: dict[str, str] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            full = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                flat.update(flatten_json(value, full))
            elif isinstance(value, str):
                flat[full] = value
            elif value is None:
                continue
            else:
                flat[full] = str(value)
    return flat


def unflatten_json(flat: dict[str, str]) -> dict[str, Any]:
    """Restore dotted keys into nested dicts."""
    root: dict[str, Any] = {}
    for key, value in flat.items():
        parts = key.split(".")
        node: dict[str, Any] = root
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[parts[-1]] = value
    return root


def parse_lang_text(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LANG_LINE_RE.match(line)
        if not m:
            continue
        result[m.group(1).strip()] = m.group(2)
    return result


def serialize_lang(flat: dict[str, str]) -> str:
    lines = [f"{k}={v}" for k, v in sorted(flat.items())]
    return "\n".join(lines) + ("\n" if lines else "")


def parse_bytes(path: str, raw: bytes) -> LangFile:
    path = path.replace("\\", "/")
    locale = detect_locale(path)
    modid = detect_modid(path)
    fmt = "json" if path.endswith(".json") else "lang"

    text = raw.decode("utf-8-sig", errors="replace")
    if fmt == "json":
        data = json.loads(text) if text.strip() else {}
        if not isinstance(data, dict):
            raise ValueError(f"言語JSONのルートがオブジェクトではありません: {path}")
        was_nested = any(isinstance(v, dict) for v in data.values())
        if was_nested:
            flat = flatten_json(data)
        else:
            flat = {
                str(k): (v if isinstance(v, str) else str(v))
                for k, v in data.items()
                if v is not None
            }
        return LangFile(
            path=path,
            fmt=fmt,
            locale=locale,
            modid=modid,
            flat=flat,
            was_nested=was_nested,
        )

    return LangFile(
        path=path,
        fmt=fmt,
        locale=locale,
        modid=modid,
        flat=parse_lang_text(text),
        was_nested=False,
    )


def serialize_lang_file(lang: LangFile, flat: dict[str, str] | None = None) -> bytes:
    data = flat if flat is not None else lang.flat
    if lang.fmt == "json":
        obj = unflatten_json(data) if lang.was_nested else dict(sorted(data.items()))
        text = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
        return text.encode("utf-8")
    return serialize_lang(data).encode("utf-8")


def ja_path_for(en_path: str) -> str:
    path = en_path.replace("\\", "/")
    lower = path.lower()
    for suffix in ("en_us.json", "en_us.lang"):
        if lower.endswith(suffix):
            ja_name = "ja_jp.json" if suffix.endswith(".json") else "ja_jp.lang"
            return path[: -len(suffix)] + ja_name
    if path.endswith(".json"):
        return path.rsplit("/", 1)[0] + "/ja_jp.json"
    if path.endswith(".lang"):
        return path.rsplit("/", 1)[0] + "/ja_jp.lang"
    return path + ".ja_jp"
