# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 概要

Python + Streamlit + Gemini API（`google-genai` SDK）で作った、個人用の日本語 AI ライティングツール。UI 文言・プロンプト・コメントはすべて日本語で書かれている。

## コマンド（Windows / PowerShell）

```powershell
# 初回セットアップ（.venv は作成済み）
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # GEMINI_API_KEY を書き込む

# 起動（http://localhost:8501）
streamlit run app.py
# venv を有効化せずに起動する場合
.\.venv\Scripts\streamlit.exe run app.py
```

テスト・リンター・ビルド設定はまだない。

## 設定

- APIキーは `GEMINI_API_KEY`（または `GOOGLE_API_KEY`）→ `st.secrets["GEMINI_API_KEY"]`（`.streamlit/secrets.toml`）の順に探す。どちらにもなければサイドバーの「⚙️ 設定」で入力する。
- モデルは画面から選べない。`GEMINI_MODEL`（未設定なら `gemini-3.8-flash`。Gemini 2.5 系は新規ユーザーには 404 になる）で固定され、`app.py` の冒頭で `model` に読み込まれる。`gemini_client.py` の `list_text_models` / `DEFAULT_MODELS` は現在どこからも使われていない。

## アーキテクチャ

ファイルは3つで、データ駆動の作りになっている。

- **`tools.py`**: ツールを宣言的に定義している。`Tool` は id・名前・アイコン・`fields: list[Field]`・`build_prompt(values: dict) -> str`・`system_instruction`・推奨 `temperature` を持つ。`Field.kind` は `text` / `textarea` / `select` / `slider` のいずれか。`TOOLS` リストの並び順がそのままサイドバーの表示順になる。`TOOLS_BY_ID` で id から引ける。`_opt(label, value)` は任意項目用のヘルパーで、値が空なら空文字を返すのでプロンプトに行が入らない。
- **`app.py`**: `TOOLS` をもとにサイドバーと入力フォームを自動生成する。ツールごとに個別の UI コードはない。
- **`gemini_client.py`**: Gemini SDK を薄く包んだラッパー（`make_client`、`list_text_models`、`stream_generate`）。

**ツールを追加するとき**は、`tools.py` にプロンプトを組み立てる関数を書き、`TOOLS` に `Tool(...)` を足すだけでよい。`build_prompt` には `{field.key: 値}` の dict が渡されるので、各 `Field.key` はプロンプト関数が読むキーと一致させること。

### app.py の Streamlit 状態管理（変更時に注意）

- ウィジェットのキーは `f__{tool.id}__{field.key}` の形式。スクリプト冒頭の `ss[k] = ss[k]` ループは、ツールを切り替えても入力値が消えないようにするための意図的なワークアラウンドなので消さないこと。
- 初期値は `ss.setdefault(key, ...)` で与え、ウィジェットに `value=` は渡さない（両方使うと Streamlit が警告を出す）。
- 入力フォームに `st.form` を使っていないのは意図的（未送信の入力がページ切替で消えるため）。`st.form` は修正指示の欄だけで使っている。
- `ss.results[tool_id]` にはツールごとの最新の `{prompt, output}` を、`ss.history` には生成履歴を新しい順に最大 `MAX_HISTORY` 件保存する（セッション内のみで、再読み込みすると消える）。生成が終わると `st.rerun()` して、結果表示エリアで描画し直す。
- 「🔧 この結果を修正する」は、前回のプロンプト・前回の出力・修正指示をつなげた新しいプロンプトを1回送るだけで、会話履歴を使ったマルチターンではない。
- temperature はツールごとの推奨値（`Tool.temperature`）を使い、サイドバーで「手動」を選んだときだけスライダーの値で上書きする。
