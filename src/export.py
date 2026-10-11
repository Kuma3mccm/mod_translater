"""Download helpers for translated JAR and resource pack outputs."""

from __future__ import annotations

from .jar_handler import ModLangBundle, build_resource_pack, build_translated_jar


def translated_jar_filename(original_name: str) -> str:
    name = original_name or "mod.jar"
    if name.lower().endswith(".jar"):
        return name[: -len(".jar")] + "-ja.jar"
    return name + "-ja.jar"


def resource_pack_filename(original_name: str, mc_version: str | None = None) -> str:
    name = original_name or "mod.jar"
    base = name[: -len(".jar")] if name.lower().endswith(".jar") else name
    if mc_version:
        return f"{base}-ja_jp-RP-mc{mc_version}.zip"
    return f"{base}-ja_jp-RP.zip"


def export_jar_bytes(bundle: ModLangBundle) -> tuple[bytes, str]:
    return build_translated_jar(bundle), translated_jar_filename(bundle.jar_name)


def export_resource_pack_bytes(bundle: ModLangBundle) -> tuple[bytes, str]:
    ver = bundle.mc_version.version if bundle.mc_version else None
    return build_resource_pack(bundle), resource_pack_filename(bundle.jar_name, ver)
