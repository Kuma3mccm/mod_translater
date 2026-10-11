"""Detect Minecraft version from mod JARs and map to resource pack_format."""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import Any

# (min_version_tuple_inclusive, pack_format) — newest first for matching.
# Resource pack formats (Java Edition). Keep in sync with minecraft.wiki Pack format.
_FORMAT_TABLE: list[tuple[tuple[int, int, int], int]] = [
    ((26, 3, 0), 97),
    ((26, 2, 0), 88),
    ((26, 1, 0), 84),
    ((1, 21, 11), 75),
    ((1, 21, 9), 69),
    ((1, 21, 7), 64),
    ((1, 21, 6), 63),
    ((1, 21, 5), 55),
    ((1, 21, 4), 46),
    ((1, 21, 2), 42),
    ((1, 21, 0), 34),
    ((1, 20, 5), 32),
    ((1, 20, 3), 22),
    ((1, 20, 2), 18),
    ((1, 20, 0), 15),
    ((1, 19, 4), 13),
    ((1, 19, 3), 12),
    ((1, 19, 0), 9),
    ((1, 18, 0), 8),
    ((1, 17, 0), 7),
    ((1, 16, 2), 6),
    ((1, 15, 0), 5),
    ((1, 13, 0), 4),
    ((1, 11, 0), 3),
    ((1, 9, 0), 2),
    ((1, 6, 1), 1),
]

_VERSION_RE = re.compile(
    r"(?<![0-9])(\d{1,2})\.(\d{1,2})(?:\.(\d{1,2}))?(?![0-9])"
)
_RANGE_VERSION_RE = re.compile(
    r"[\[\(]?\s*(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)"
)


@dataclass(frozen=True)
class MinecraftVersionInfo:
    version: str  # e.g. "1.20.1"
    pack_format: int
    source: str  # where it was detected


@dataclass(frozen=True)
class ModIdentity:
    """Display name and version of the mod itself (not Minecraft)."""

    name: str
    version: str
    source: str


def parse_version_tuple(version: str) -> tuple[int, int, int] | None:
    m = _VERSION_RE.search(version.strip())
    if not m:
        return None
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    return major, minor, patch


def format_version(tup: tuple[int, int, int]) -> str:
    major, minor, patch = tup
    if patch:
        return f"{major}.{minor}.{patch}"
    return f"{major}.{minor}"


def pack_format_for_version(version: str) -> int:
    tup = parse_version_tuple(version)
    if tup is None:
        return 15  # safe modern default (1.20)
    for min_ver, fmt in _FORMAT_TABLE:
        if tup >= min_ver:
            return fmt
    return 1


def _normalize_dep_version(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return str(raw)
    if isinstance(raw, list) and raw:
        return _normalize_dep_version(raw[0])
    if isinstance(raw, dict):
        for key in ("version", "minecraft", "min", "minimum"):
            if key in raw:
                return _normalize_dep_version(raw[key])
        return None
    text = str(raw).strip().strip('"').strip("'")
    if not text:
        return None
    # "~1.20.1", "^1.20", ">=1.20.1", "1.20.x", "[1.20.1,1.21)"
    m = _RANGE_VERSION_RE.search(text.replace("x", "0"))
    if m:
        return m.group(1)
    m2 = _VERSION_RE.search(text)
    return m2.group(0) if m2 else None


def _from_fabric_like(data: dict[str, Any], label: str) -> MinecraftVersionInfo | None:
    depends = data.get("depends") or data.get("depends".upper()) or {}
    if not isinstance(depends, dict):
        return None
    for key in ("minecraft", "Minecraft"):
        if key in depends:
            ver = _normalize_dep_version(depends[key])
            if ver:
                return MinecraftVersionInfo(
                    version=ver,
                    pack_format=pack_format_for_version(ver),
                    source=label,
                )
    return None


def _from_mods_toml(text: str, label: str) -> MinecraftVersionInfo | None:
    # Prefer dependency blocks for minecraft
    blocks = re.split(r"\[\[dependencies[^\]]*\]\]", text, flags=re.IGNORECASE)
    for block in blocks[1:]:
        if not re.search(r'modId\s*=\s*"minecraft"', block, re.IGNORECASE):
            continue
        m = re.search(
            r'versionRange\s*=\s*"([^"]+)"', block, re.IGNORECASE
        ) or re.search(r"versionRange\s*=\s*'([^']+)'", block, re.IGNORECASE)
        if m:
            ver = _normalize_dep_version(m.group(1))
            if ver:
                return MinecraftVersionInfo(
                    version=ver,
                    pack_format=pack_format_for_version(ver),
                    source=label,
                )
    # Fallback: loaderVersion / displayMCVersion style keys
    for key in ("displayMCVersion", "mcversion", "minecraftVersion"):
        m = re.search(rf'{key}\s*=\s*"([^"]+)"', text, re.IGNORECASE)
        if m:
            ver = _normalize_dep_version(m.group(1))
            if ver:
                return MinecraftVersionInfo(
                    version=ver,
                    pack_format=pack_format_for_version(ver),
                    source=label,
                )
    return None


def _from_mcmod_info(raw: bytes, label: str) -> MinecraftVersionInfo | None:
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        return None
    items = data if isinstance(data, list) else [data]
    for item in items:
        if not isinstance(item, dict):
            continue
        ver = _normalize_dep_version(item.get("mcversion") or item.get("mcVersion"))
        if ver:
            return MinecraftVersionInfo(
                version=ver,
                pack_format=pack_format_for_version(ver),
                source=label,
            )
    return None


def _from_filename(jar_name: str) -> MinecraftVersionInfo | None:
    # Prefer versions that look like MC (1.xx) over mod versions (often 0.x or year)
    candidates = _VERSION_RE.findall(jar_name)
    best: tuple[int, int, int] | None = None
    for maj, minu, patch in candidates:
        tup = (int(maj), int(minu), int(patch or 0))
        if tup[0] == 1 and 6 <= tup[1] <= 21:
            best = tup
            break
        if tup[0] >= 26:  # new versioning scheme 26.x
            best = tup
            break
    if best is None:
        return None
    ver = format_version(best)
    return MinecraftVersionInfo(
        version=ver,
        pack_format=pack_format_for_version(ver),
        source="filename",
    )


def detect_minecraft_version(jar_bytes: bytes, jar_name: str = "") -> MinecraftVersionInfo:
    """Inspect mod metadata inside a JAR and return MC version + pack_format."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(jar_bytes), "r")
    except Exception:
        fallback = _from_filename(jar_name)
        return fallback or MinecraftVersionInfo("1.20.1", 15, "default")

    with zf:
        names = {n.replace("\\", "/"): n for n in zf.namelist()}

        # Fabric / Quilt
        for path, label in (
            ("fabric.mod.json", "fabric.mod.json"),
            ("quilt.mod.json", "quilt.mod.json"),
        ):
            if path in names:
                try:
                    data = json.loads(zf.read(names[path]).decode("utf-8-sig"))
                    if isinstance(data, dict):
                        info = _from_fabric_like(data, label)
                        if info:
                            return info
                except Exception:
                    pass

        # Forge / NeoForge mods.toml
        for path, label in (
            ("META-INF/neoforge.mods.toml", "neoforge.mods.toml"),
            ("META-INF/mods.toml", "mods.toml"),
        ):
            if path in names:
                try:
                    text = zf.read(names[path]).decode("utf-8-sig", errors="replace")
                    info = _from_mods_toml(text, label)
                    if info:
                        return info
                except Exception:
                    pass

        # Legacy mcmod.info
        if "mcmod.info" in names:
            info = _from_mcmod_info(zf.read(names["mcmod.info"]), "mcmod.info")
            if info:
                return info

    fallback = _from_filename(jar_name)
    return fallback or MinecraftVersionInfo("1.20.1", 15, "default")


def _clean_meta_str(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    # Strip common localization wrappers like fabric's name keys
    if text.startswith("%") and text.endswith("%") and len(text) > 2:
        return ""
    return text


def _identity_from_fabric(data: dict[str, Any], label: str) -> ModIdentity | None:
    name = _clean_meta_str(data.get("name")) or _clean_meta_str(data.get("id"))
    version = _clean_meta_str(data.get("version"))
    if name:
        return ModIdentity(name=name, version=version, source=label)
    return None


def _identity_from_mods_toml(text: str, label: str) -> ModIdentity | None:
    # First [[mods]] block
    m = re.search(r"\[\[mods\]\](.*?)(?=\n\[\[|\Z)", text, re.IGNORECASE | re.DOTALL)
    block = m.group(1) if m else text
    display = re.search(r'displayName\s*=\s*"([^"]+)"', block, re.IGNORECASE)
    mod_id = re.search(r'modId\s*=\s*"([^"]+)"', block, re.IGNORECASE)
    version = re.search(r'version\s*=\s*"([^"]+)"', block, re.IGNORECASE)
    name = ""
    if display:
        name = display.group(1).strip()
    elif mod_id:
        name = mod_id.group(1).strip()
    ver = version.group(1).strip() if version else ""
    # Ignore Forge placeholder tokens like ${file.jarVersion}
    if ver.startswith("${"):
        ver = ""
    if name:
        return ModIdentity(name=name, version=ver, source=label)
    return None


def _identity_from_mcmod_info(raw: bytes, label: str) -> ModIdentity | None:
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        return None
    items = data if isinstance(data, list) else [data]
    for item in items:
        if not isinstance(item, dict):
            continue
        name = _clean_meta_str(item.get("name")) or _clean_meta_str(item.get("modid"))
        version = _clean_meta_str(item.get("version"))
        if name:
            return ModIdentity(name=name, version=version, source=label)
    return None


def _identity_from_filename(jar_name: str) -> ModIdentity:
    base = jar_name.rsplit("/", 1)[-1]
    if base.lower().endswith(".jar"):
        base = base[: -len(".jar")]
    # Strip a trailing MC-looking version from the filename when possible
    name = base
    version = ""
    # Prefer last version-like token as mod version (e.g. modname-1.2.3)
    matches = list(re.finditer(r"(?<![0-9])(\d+\.\d+(?:\.\d+)?)(?![0-9])", base))
    if matches:
        last = matches[-1]
        version = last.group(1)
        name = base[: last.start()].rstrip("-_. ")
    if not name:
        name = base or "Unknown Mod"
    return ModIdentity(name=name, version=version, source="filename")


def detect_mod_identity(jar_bytes: bytes, jar_name: str = "") -> ModIdentity:
    """Detect mod display name and version from JAR metadata."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(jar_bytes), "r")
    except Exception:
        return _identity_from_filename(jar_name)

    with zf:
        names = {n.replace("\\", "/"): n for n in zf.namelist()}

        for path, label in (
            ("fabric.mod.json", "fabric.mod.json"),
            ("quilt.mod.json", "quilt.mod.json"),
        ):
            if path in names:
                try:
                    data = json.loads(zf.read(names[path]).decode("utf-8-sig"))
                    if isinstance(data, dict):
                        ident = _identity_from_fabric(data, label)
                        if ident:
                            return ident
                except Exception:
                    pass

        for path, label in (
            ("META-INF/neoforge.mods.toml", "neoforge.mods.toml"),
            ("META-INF/mods.toml", "mods.toml"),
        ):
            if path in names:
                try:
                    text = zf.read(names[path]).decode("utf-8-sig", errors="replace")
                    ident = _identity_from_mods_toml(text, label)
                    if ident:
                        return ident
                except Exception:
                    pass

        if "mcmod.info" in names:
            ident = _identity_from_mcmod_info(zf.read(names["mcmod.info"]), "mcmod.info")
            if ident:
                return ident

    return _identity_from_filename(jar_name)


def resource_pack_description(mod_name: str, minecraft_version: str) -> str:
    """Build pack.mcmeta description: mod名 + Minecraftバージョン + 日本語化パック."""
    name = (mod_name or "").strip() or "Unknown Mod"
    version = (minecraft_version or "").strip()
    if version:
        return f"{name} {version} 日本語化パック"
    return f"{name} 日本語化パック"


def build_pack_mcmeta(
    *,
    pack_format: int,
    description: str,
    mc_version: str,
) -> dict[str, Any]:
    """Build pack.mcmeta content compatible with the target format era."""
    pack: dict[str, Any] = {
        "pack_format": pack_format,
        "description": description,
    }
    # 1.20.2+ optional range (keeps pack_format as the primary target)
    if pack_format >= 18:
        pack["supported_formats"] = {
            "min_inclusive": pack_format,
            "max_inclusive": pack_format,
        }
    # 1.21.9+ also reads min_format / max_format
    if pack_format >= 69:
        pack["min_format"] = pack_format
        pack["max_format"] = pack_format
    return {"pack": pack}
