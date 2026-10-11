"""Minecraft Mod Japanese localization tool — Streamlit entrypoint."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.export import export_jar_bytes, export_resource_pack_bytes
from src.jar_handler import ModLangBundle, extract_lang_bundle
from src.lang_parser import ja_path_for
from src.placeholder import validate_batch
from src.translators.base import (
    ALL_PROVIDERS,
    PROVIDER_DEEPL,
    PROVIDER_GEMINI,
    PROVIDER_GOOGLE,
    PROVIDER_OPENAI,
    get_translator,
    resolve_provider,
)

st.set_page_config(
    page_title="Minecraft Mod 日本語化ツール",
    page_icon="🧱",
    layout="wide",
)

# Entries processed per rerun so the Stop button can be clicked between chunks.
_TRANSLATE_CHUNK = 5


def init_state() -> None:
    defaults = {
        "bundle": None,
        "last_errors": [],
        "last_warnings": {},
        "provider_used": "",
        "upload_widget_id": 0,
        "preview_gen": 0,
        "translating": False,
        "translate_stop": False,
        "translate_queue": [],
        "translate_index": 0,
        "translate_total": 0,
        "translate_settings": None,
        "translate_errors": [],
        "translate_warnings": {},
        "translate_only_untranslated": True,
        "translate_ui_ready": False,
        "flash": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def show_flash() -> None:
    flash = st.session_state.get("flash")
    if not flash:
        return
    kind, message = flash
    st.session_state.flash = None
    if kind == "success":
        st.success(message)
    elif kind == "warning":
        st.warning(message)
    else:
        st.info(message)


def is_busy() -> bool:
    return bool(st.session_state.get("translating"))


def clear_mod() -> None:
    """Remove loaded mod and reset UI so a new JAR can be uploaded."""
    st.session_state.bundle = None
    st.session_state._jar_fp = None
    st.session_state.last_errors = []
    st.session_state.last_warnings = {}
    st.session_state.provider_used = ""
    st.session_state.translating = False
    st.session_state.translate_stop = False
    st.session_state.translate_queue = []
    st.session_state.translate_index = 0
    st.session_state.translate_total = 0
    st.session_state.translate_settings = None
    st.session_state.translate_errors = []
    st.session_state.translate_warnings = {}
    st.session_state.translate_ui_ready = False
    st.session_state.upload_widget_id = int(st.session_state.get("upload_widget_id", 0)) + 1
    st.session_state.preview_gen = int(st.session_state.get("preview_gen", 0)) + 1


def load_jar(uploaded) -> ModLangBundle | None:
    if uploaded is None:
        return None
    data = uploaded.getvalue()
    try:
        bundle = extract_lang_bundle(data, jar_name=uploaded.name)
    except Exception as exc:  # noqa: BLE001
        st.error(f"JARの読み込みに失敗しました: {exc}")
        return None
    if not bundle.sources:
        st.warning(
            "言語ファイル（assets/*/lang/en_us.json または .lang）が見つかりませんでした。"
        )
    return bundle


def sidebar_settings(disabled: bool = False) -> dict:
    st.sidebar.title("翻訳設定")
    st.sidebar.caption("APIキーはブラウザセッション内のみ保持され、サーバーには保存されません。")
    if disabled:
        st.sidebar.warning("翻訳中は設定を変更できません。")

    provider = st.sidebar.selectbox(
        "翻訳プロバイダ", ALL_PROVIDERS, index=0, disabled=disabled
    )

    api_key = ""
    deepl_use_free = True
    gemini_model = "gemini-2.0-flash"
    openai_model = "gpt-4o-mini"

    if provider != PROVIDER_GOOGLE:
        api_key = st.sidebar.text_input(
            f"{provider} APIキー",
            type="password",
            help="未入力の場合は Google 翻訳（キー不要）にフォールバックします。",
            disabled=disabled,
        )
        if provider == PROVIDER_DEEPL:
            deepl_use_free = st.sidebar.radio(
                "DeepL エンドポイント",
                options=[True, False],
                format_func=lambda x: "DeepL API Free" if x else "DeepL API Pro",
                index=0,
                disabled=disabled,
            )
            st.sidebar.markdown(
                "[APIキーの確認・発行（DeepLアカウント）](https://www.deepl.com/ja/your-account/keys)"
            )
        elif provider == PROVIDER_GEMINI:
            gemini_model = st.sidebar.selectbox(
                "Gemini モデル",
                ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash", "gemini-1.5-pro"],
                disabled=disabled,
            )
            st.sidebar.markdown(
                "[APIキーの確認・発行（Google AI Studio）]"
                "(https://aistudio.google.com/api-keys?hl=ja)"
            )
        elif provider == PROVIDER_OPENAI:
            openai_model = st.sidebar.selectbox(
                "OpenAI モデル",
                ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"],
                disabled=disabled,
            )
            st.sidebar.markdown(
                "[APIキーの確認・発行（OpenAI Platform）]"
                "(https://platform.openai.com/api-keys)"
            )

    effective, used_fallback = resolve_provider(provider, api_key)
    if used_fallback:
        st.sidebar.warning("APIキー未設定のため Google 翻訳を使用します。")
    elif effective == PROVIDER_GOOGLE:
        st.sidebar.info("Google 翻訳（APIキー不要）を使用します。")
    else:
        st.sidebar.success(f"{effective} を使用します。")

    st.sidebar.divider()
    st.sidebar.markdown(
        "**使い方**\n"
        "1. JAR をアップロード\n"
        "2. 翻訳を実行し、表で編集\n"
        "3. 翻訳済み JAR / リソースパック をダウンロード"
    )
    st.sidebar.caption("アップロード上限の目安: 200MB")

    return {
        "provider": provider,
        "api_key": api_key,
        "deepl_use_free": deepl_use_free,
        "gemini_model": gemini_model,
        "openai_model": openai_model,
        "effective": effective,
    }


def collect_entries(
    bundle: ModLangBundle,
    *,
    only_untranslated: bool,
) -> dict[str, dict[str, str]]:
    """Return en_path -> {key: english_source} for entries to translate."""
    todo: dict[str, dict[str, str]] = {}
    for src in bundle.sources:
        trans = bundle.translations.get(src.path, {})
        subset: dict[str, str] = {}
        for key, en_text in src.flat.items():
            current = (trans.get(key) or "").strip()
            if only_untranslated and current:
                continue
            if not (en_text or "").strip():
                continue
            subset[key] = en_text
        if subset:
            todo[src.path] = subset
    return todo


def start_translation(
    bundle: ModLangBundle, settings: dict, only_untranslated: bool
) -> None:
    todo = collect_entries(bundle, only_untranslated=only_untranslated)
    queue: list[tuple[str, str, str]] = []
    for en_path, entries in todo.items():
        for key, text in entries.items():
            queue.append((en_path, key, text))

    if not queue:
        st.info("翻訳対象のエントリがありません。")
        return

    st.session_state.translating = True
    st.session_state.translate_stop = False
    st.session_state.translate_ui_ready = False
    st.session_state.translate_queue = queue
    st.session_state.translate_index = 0
    st.session_state.translate_total = len(queue)
    st.session_state.translate_settings = settings
    st.session_state.translate_errors = []
    st.session_state.translate_warnings = {}
    st.session_state.translate_only_untranslated = only_untranslated
    st.session_state.last_errors = []
    st.session_state.last_warnings = {}
    # Invalidate any previously rendered download/editor widgets.
    st.session_state.preview_gen = int(st.session_state.get("preview_gen", 0)) + 1
    st.rerun()


def finish_translation(*, stopped: bool) -> None:
    total = int(st.session_state.translate_total)
    done = int(st.session_state.translate_index)
    st.session_state.last_errors = list(st.session_state.translate_errors)
    st.session_state.last_warnings = dict(st.session_state.translate_warnings)
    st.session_state.translating = False
    st.session_state.translate_stop = False
    st.session_state.translate_ui_ready = False
    st.session_state.translate_queue = []
    st.session_state.preview_gen = int(st.session_state.get("preview_gen", 0)) + 1
    if stopped:
        st.session_state.flash = (
            "warning",
            f"翻訳を停止しました（{done}/{total} 件まで処理）。",
        )
    else:
        provider = st.session_state.get("provider_used") or "翻訳"
        st.session_state.flash = (
            "success",
            f"翻訳完了（{provider}）: {total} 件処理",
        )
    st.rerun()


def render_translation_progress() -> None:
    total = int(st.session_state.translate_total) or 1
    done = int(st.session_state.translate_index)
    pct = min(done / total, 1.0)
    provider = st.session_state.get("provider_used") or "準備中"
    st.progress(pct, text=f"{done} / {total} 件 ({pct * 100:.0f}%) — {provider}")
    st.info(f"翻訳中 — **{provider}** | {done}/{total} 件 ({pct * 100:.0f}%)")


def inject_busy_lock_css() -> None:
    """Hide leftover download/save controls from a previous render while busy."""
    st.markdown(
        """
        <style>
        div[data-testid="stDownloadButton"],
        div[data-testid="stDownloadButton"] button,
        .stDownloadButton,
        .stDownloadButton button {
            display: none !important;
            visibility: hidden !important;
            pointer-events: none !important;
            height: 0 !important;
            overflow: hidden !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def process_translation_chunk(bundle: ModLangBundle) -> str:
    """
    Translate one chunk.
    Returns: 'stopped' | 'done' | 'continue'
    """
    if st.session_state.translate_stop:
        return "stopped"

    queue: list[tuple[str, str, str]] = st.session_state.translate_queue
    idx = int(st.session_state.translate_index)
    total = int(st.session_state.translate_total)
    settings = st.session_state.translate_settings or {}

    if idx >= total:
        return "done"

    translator = get_translator(
        settings.get("provider", PROVIDER_GOOGLE),
        settings.get("api_key", ""),
        deepl_use_free=settings.get("deepl_use_free", True),
        gemini_model=settings.get("gemini_model", "gemini-2.0-flash"),
        openai_model=settings.get("openai_model", "gpt-4o-mini"),
    )
    st.session_state.provider_used = translator.name

    end = min(idx + _TRANSLATE_CHUNK, total)
    chunk = queue[idx:end]
    by_path: dict[str, dict[str, str]] = {}
    for en_path, key, text in chunk:
        by_path.setdefault(en_path, {})[key] = text

    current_file = chunk[0][0] if chunk else ""
    st.caption(f"処理中ファイル: `{current_file}`（このチャンク {len(chunk)} 件）")

    for en_path, entries in by_path.items():
        result = translator.translate_entries(entries)
        st.session_state.translate_errors.extend(result.errors)
        for key, ja in result.translations.items():
            if ja:
                bundle.translations[en_path][key] = ja
        pairs = [
            (f"{en_path}::{k}", entries[k], result.translations.get(k, ""))
            for k in entries
            if result.translations.get(k)
        ]
        st.session_state.translate_warnings.update(validate_batch(pairs))

    st.session_state.translate_index = end

    if st.session_state.translate_stop:
        return "stopped"
    if end >= total:
        return "done"
    return "continue"


@st.fragment(run_every=timedelta(milliseconds=200))
def translation_worker(bundle: ModLangBundle) -> None:
    """
    First invocation only paints progress so the main script can finish and
    flush a UI without download buttons. Later fragment ticks do the work.
    """
    if not st.session_state.get("translating"):
        return
    if st.session_state.get("translate_stop"):
        finish_translation(stopped=True)
        return

    # Allow the locked main page (no download/save widgets) to commit first.
    if not st.session_state.get("translate_ui_ready"):
        st.session_state.translate_ui_ready = True
        render_translation_progress()
        st.caption("翻訳を開始しています…")
        return

    status = process_translation_chunk(bundle)
    render_translation_progress()
    if status == "stopped":
        finish_translation(stopped=True)
    elif status == "done":
        finish_translation(stopped=False)


def render_file_summary(bundle: ModLangBundle) -> None:
    rows = []
    for src in bundle.sources:
        trans = bundle.translations.get(src.path, {})
        filled = sum(1 for k in src.flat if (trans.get(k) or "").strip())
        rows.append(
            {
                "パス": src.path,
                "modid": src.modid,
                "形式": src.fmt,
                "キー数": len(src.flat),
                "翻訳済み": filled,
                "ja_jp": ja_path_for(src.path),
            }
        )
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def download_section(bundle: ModLangBundle, key_prefix: str, *, disabled: bool) -> None:
    st.subheader("ダウンロード")
    mc = bundle.mc_version
    if mc:
        st.caption(
            f"リソースパック: Minecraft **{mc.version}** → "
            f"`pack_format` **{mc.pack_format}**（検出元: {mc.source}）"
        )
    col1, col2 = st.columns(2)
    try:
        jar_bytes, jar_name = export_jar_bytes(bundle)
        pack_bytes, pack_name = export_resource_pack_bytes(bundle)
    except Exception as exc:  # noqa: BLE001
        st.error(f"出力の生成に失敗しました: {exc}")
        return

    with col1:
        st.download_button(
            label="翻訳済み JAR をダウンロード",
            data=jar_bytes,
            file_name=jar_name,
            mime="application/java-archive",
            use_container_width=True,
            key=f"{key_prefix}_dl_jar",
            disabled=disabled,
        )
    with col2:
        st.download_button(
            label="リソースパック をダウンロード",
            data=pack_bytes,
            file_name=pack_name,
            mime="application/zip",
            use_container_width=True,
            key=f"{key_prefix}_dl_rp",
            disabled=disabled,
        )


def render_upload_area(*, disabled: bool) -> None:
    """Show uploader only when no mod is loaded; otherwise show file + delete."""
    bundle: ModLangBundle | None = st.session_state.bundle

    if bundle is None:
        uploaded = st.file_uploader(
            "Minecraft Mod JAR をアップロード（1ファイルのみ）",
            type=["jar"],
            accept_multiple_files=False,
            key=f"upload_jar_{st.session_state.upload_widget_id}",
            help="1つの JAR のみアップロードできます（Forge / Fabric / NeoForge など）",
            disabled=disabled,
        )
        if uploaded is not None and not disabled:
            if isinstance(uploaded, list):
                uploaded = uploaded[0] if uploaded else None
            if uploaded is not None:
                fingerprint = f"{uploaded.name}:{uploaded.size}"
                if st.session_state.get("_jar_fp") != fingerprint:
                    loaded = load_jar(uploaded)
                    if loaded is not None:
                        st.session_state.bundle = loaded
                        st.session_state._jar_fp = fingerprint
                        st.session_state.last_errors = []
                        st.session_state.last_warnings = {}
                        st.session_state.preview_gen = (
                            int(st.session_state.get("preview_gen", 0)) + 1
                        )
                        st.rerun()
        return

    st.markdown("**アップロード済みファイル**")
    col1, col2 = st.columns([4, 1])
    with col1:
        st.info(f"📦 `{bundle.jar_name}`")
    with col2:
        if st.button(
            "削除",
            key="delete_mod",
            use_container_width=True,
            disabled=disabled,
            help="読み込みを解除し、別の MOD をアップロードできます",
        ):
            clear_mod()
            st.rerun()


def main_workspace(settings: dict) -> None:
    busy = is_busy()
    render_upload_area(disabled=busy)

    bundle: ModLangBundle | None = st.session_state.bundle
    if bundle is None:
        st.info(
            "JAR ファイルを1つアップロードしてください。"
            " APIキーなしでも Google 翻訳で利用できます。"
        )
        return

    st.caption(f"読み込み済み: **{bundle.jar_name}**")
    if bundle.mc_version:
        st.info(
            f"検出バージョン: Minecraft **{bundle.mc_version.version}** / "
            f"リソースパック `pack_format` **{bundle.mc_version.pack_format}**"
            f"（{bundle.mc_version.source}）"
        )
    render_file_summary(bundle)

    # ---- Translation in progress: lock UI (no save / download widgets) ----
    if busy:
        # Hide any stale download buttons still on screen from the previous frame.
        inject_busy_lock_css()
        st.warning("翻訳中です。停止以外の操作はできません。")
        render_translation_progress()
        if st.button("停止", type="secondary", use_container_width=True, key="stop_translate"):
            st.session_state.translate_stop = True
            st.rerun()

        # Main script returns immediately after mounting the worker fragment.
        # This flushes a UI without download/save controls to the browser.
        translation_worker(bundle)
        return

    # ---- Idle: full editing UI ----
    only_untranslated = st.checkbox(
        "未翻訳のみ翻訳する",
        value=True,
        key="only_untranslated_cb",
    )

    if st.button("翻訳を実行", type="primary", use_container_width=True, key="run_translate"):
        start_translation(bundle, settings, only_untranslated=only_untranslated)

    if st.session_state.last_errors:
        with st.expander("エラー", expanded=True):
            for err in st.session_state.last_errors:
                st.error(err)

    if st.session_state.last_warnings:
        with st.expander(f"プレースホルダ警告 ({len(st.session_state.last_warnings)})"):
            for key, warns in st.session_state.last_warnings.items():
                st.warning(f"{key}: {'; '.join(warns)}")

    gen = st.session_state.preview_gen
    if bundle.sources:
        st.markdown("### プレビュー・編集")
        paths = [s.path for s in bundle.sources]
        selected = st.selectbox(
            "言語ファイル",
            paths,
            key=f"auto_preview_file_{gen}",
        )
        src = next(s for s in bundle.sources if s.path == selected)
        trans = bundle.translations[src.path]

        col_f1, col_f2 = st.columns(2)
        with col_f1:
            only_empty = st.checkbox(
                "未翻訳のみ表示",
                value=False,
                key=f"auto_only_empty_{gen}",
            )
        with col_f2:
            query = st.text_input(
                "検索（キー / 原文 / 訳文）",
                "",
                key=f"auto_preview_query_{gen}",
            )

        rows = []
        for key, en in src.flat.items():
            ja = trans.get(key, "")
            if only_empty and (ja or "").strip():
                continue
            if query:
                q = query.lower()
                if q not in f"{key} {en} {ja}".lower():
                    continue
            rows.append({"キー": key, "原文": en, "訳文": ja})

        st.caption(f"{len(rows)} / {len(src.flat)} 件表示（すべて編集可能）")
        if rows:
            edited = st.data_editor(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True,
                disabled=["キー", "原文"],
                column_config={
                    "キー": st.column_config.TextColumn(width="medium"),
                    "原文": st.column_config.TextColumn(width="large"),
                    "訳文": st.column_config.TextColumn(width="large"),
                },
                key=f"auto_editor_{gen}_{selected}",
                num_rows="fixed",
                height=520,
            )
            if st.button(
                "編集内容を保存",
                key=f"auto_save_edits_{gen}",
                type="primary",
            ):
                for _, row in edited.iterrows():
                    trans[str(row["キー"])] = (
                        str(row["訳文"]) if row["訳文"] is not None else ""
                    )
                st.success("保存しました。ダウンロードに反映されます。")
        else:
            st.info("表示するエントリがありません。")

    download_section(bundle, key_prefix=f"auto_{gen}", disabled=False)


def main() -> None:
    init_state()
    st.title("Minecraft Mod 日本語化ツール")
    st.markdown(
        "JAR をアップロードして `en_us` 言語ファイルを日本語（`ja_jp`）へ翻訳します。"
        " APIキーなしでも **Google 翻訳** が使えます。"
    )
    show_flash()

    busy = is_busy()
    settings = sidebar_settings(disabled=busy)
    main_workspace(settings)


main()
