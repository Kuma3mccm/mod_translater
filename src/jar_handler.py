"""Extract language files from Minecraft mod JARs and rebuild outputs."""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field

from .lang_parser import LangFile, ja_path_for, parse_bytes, serialize_lang_file
from .mc_version import (
    MinecraftVersionInfo,
    ModIdentity,
    build_pack_mcmeta,
    detect_minecraft_version,
    detect_mod_identity,
    resource_pack_description,
)


def _is_lang_entry(name: str) -> bool:
    """True for assets/<modid>/lang/*.(json|lang)."""
    parts = name.replace("\\", "/").split("/")
    if len(parts) < 4 or parts[0] != "assets" or parts[2] != "lang":
        return False
    lower = parts[-1].lower()
    return lower.endswith(".json") or lower.endswith(".lang")


@dataclass
class ModLangBundle:
    """Language content extracted from a single JAR upload."""

    jar_name: str
    jar_bytes: bytes
    sources: list[LangFile] = field(default_factory=list)  # en_us files
    existing_ja: dict[str, LangFile] = field(default_factory=dict)  # ja path -> file
    # Working translations keyed by source en_path -> {key: translated}
    translations: dict[str, dict[str, str]] = field(default_factory=dict)
    mc_version: MinecraftVersionInfo | None = None
    mod_identity: ModIdentity | None = None

    def ensure_translation_dicts(self) -> None:
        for src in self.sources:
            ja_path = ja_path_for(src.path)
            if src.path not in self.translations:
                existing = self.existing_ja.get(ja_path)
                if existing:
                    seeded = {k: existing.flat.get(k, "") for k in src.flat}
                    self.translations[src.path] = seeded
                else:
                    self.translations[src.path] = {k: "" for k in src.flat}
            else:
                cur = self.translations[src.path]
                for k in src.flat:
                    cur.setdefault(k, "")


def extract_lang_bundle(jar_bytes: bytes, jar_name: str = "mod.jar") -> ModLangBundle:
    sources: list[LangFile] = []
    existing_ja: dict[str, LangFile] = {}

    with zipfile.ZipFile(io.BytesIO(jar_bytes), "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if not _is_lang_entry(name):
                continue
            try:
                raw = zf.read(info)
                lang = parse_bytes(name, raw)
            except Exception:
                continue
            locale_norm = lang.locale.lower()
            if locale_norm == "en_us":
                sources.append(lang)
            elif locale_norm == "ja_jp":
                existing_ja[lang.path] = lang

    sources.sort(key=lambda x: x.path)
    mc_version = detect_minecraft_version(jar_bytes, jar_name)
    mod_identity = detect_mod_identity(jar_bytes, jar_name)
    bundle = ModLangBundle(
        jar_name=jar_name,
        jar_bytes=jar_bytes,
        sources=sources,
        existing_ja=existing_ja,
        mc_version=mc_version,
        mod_identity=mod_identity,
    )
    bundle.ensure_translation_dicts()
    return bundle


def build_translated_jar(bundle: ModLangBundle) -> bytes:
    """Copy original JAR and inject/overwrite ja_jp language files."""
    out_buf = io.BytesIO()
    ja_payloads: dict[str, bytes] = {}

    for src in bundle.sources:
        ja_path = ja_path_for(src.path)
        flat = bundle.translations.get(src.path, {})
        ja_lang = LangFile(
            path=ja_path,
            fmt=src.fmt,
            locale="ja_jp",
            modid=src.modid,
            flat=flat,
            was_nested=src.was_nested,
        )
        ja_payloads[ja_path] = serialize_lang_file(ja_lang)

    with zipfile.ZipFile(io.BytesIO(bundle.jar_bytes), "r") as zin:
        with zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                name = info.filename.replace("\\", "/")
                if name in ja_payloads:
                    continue
                data = zin.read(info)
                new_info = zipfile.ZipInfo(filename=info.filename, date_time=info.date_time)
                new_info.compress_type = zipfile.ZIP_DEFLATED
                new_info.external_attr = info.external_attr
                zout.writestr(new_info, data)
            for ja_path, payload in sorted(ja_payloads.items()):
                info = zipfile.ZipInfo(filename=ja_path)
                info.compress_type = zipfile.ZIP_DEFLATED
                zout.writestr(info, payload)

    return out_buf.getvalue()


def build_resource_pack(bundle: ModLangBundle) -> bytes:
    """
    Build a Minecraft resource pack ZIP:
      pack.mcmeta
      assets/<modid>/lang/ja_jp.*
    pack_format is derived from the mod's Minecraft version.
    """
    mc = bundle.mc_version or detect_minecraft_version(bundle.jar_bytes, bundle.jar_name)
    ident = bundle.mod_identity or detect_mod_identity(bundle.jar_bytes, bundle.jar_name)
    desc = resource_pack_description(ident.name, mc.version)
    meta = build_pack_mcmeta(
        pack_format=mc.pack_format,
        description=desc,
        mc_version=mc.version,
    )

    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        zout.writestr(
            "pack.mcmeta",
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        )
        for src in bundle.sources:
            ja_path = ja_path_for(src.path)
            flat = bundle.translations.get(src.path, {})
            ja_lang = LangFile(
                path=ja_path,
                fmt=src.fmt,
                locale="ja_jp",
                modid=src.modid,
                flat=flat,
                was_nested=src.was_nested,
            )
            zout.writestr(ja_path, serialize_lang_file(ja_lang))
    return out_buf.getvalue()
