# Minecraft Mod 日本語化ツール

[Streamlit Cloud](https://streamlit.io/cloud) 向けの、Minecraft Java 版 mod（JAR）日本語化 Web アプリです。

- JAR をアップロードして `assets/*/lang/en_us.json`（または `.lang`）を検出し、`ja_jp` を生成
- 翻訳結果の手動確認・編集
- **APIキーなし** → Google 翻訳（キー不要）
- APIキーあり → DeepL / Gemini / OpenAI
- 出力: **翻訳済み JAR** と **リソースパック（pack_format 自動設定）** の両方

## ローカル実行

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

ブラウザで `http://localhost:8501` が開きます。

## Streamlit Cloud へのデプロイ

1. このリポジトリを GitHub にプッシュする
2. [streamlit.io/cloud](https://streamlit.io/cloud) にログインし、GitHub リポジトリを連携
3. デプロイ設定:
   - **Main file path**: `app.py`
   - **Python version**: 3.11 推奨
4. Deploy 後、公開 URL から利用可能

APIキーは利用者自身がサイドバーで入力します。Streamlit Secrets への登録は不要です。

## 使い方

1. サイドバーで翻訳プロバイダを選択  
   - キー未入力、または「Google翻訳」選択時は無料の Google 翻訳を使用
2. mod の `.jar` をアップロード
3. 翻訳を実行し、プレビュー表で訳文を確認・編集して保存
4. **翻訳済み JAR** または **リソースパック** をダウンロード

### 出力について

| 出力 | 内容 |
|------|------|
| `*-ja.jar` | 元 JAR に `ja_jp` 言語ファイルを追加/上書きしたもの |
| `*-ja_jp-RP-mc<ver>.zip` | `pack.mcmeta` + `assets/.../lang/ja_jp.*` のリソースパック |

リソースパックの `pack_format` は、JAR 内の `fabric.mod.json` / `mods.toml` 等から検出した Minecraft バージョンに合わせて自動設定されます。  
`resourcepacks` フォルダへ入れて有効化し、ゲーム言語を「日本語」にしてください。

## 対応フォーマット

- `assets/<modid>/lang/en_us.json`（1.13+ 一般的）
- `assets/<modid>/lang/en_us.lang`（レガシー）
- 既存の `ja_jp` がある場合は初期値として読み込みます

## API プロバイダ

| プロバイダ | APIキー | 備考 |
|-----------|---------|------|
| Google翻訳 | 不要 | デフォルト / フォールバック |
| DeepL | 必要 | Free / Pro エンドポイント切替可 |
| Gemini | 必要 | モデル選択可 |
| OpenAI | 必要 | モデル選択可 |

キーはセッション内のみ保持され、アプリ側には永続保存されません。

## 注意事項

- アップロード目安: 200MB 以下（Streamlit Cloud の設定に依存）
- Google 翻訳はキー不要の無料経路です。制限時は MyMemory へ自動フォールバックします。大量キーでは時間がかかることがあります
- `%s` / `%d` / `%1$s` や `§` 書式コードが欠落した場合は警告を表示します
- 翻訳品質はプロバイダ次第です。公開配布前に手動確認を推奨します
