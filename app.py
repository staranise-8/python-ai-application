"""AIライティングツール (Streamlit + Gemini API)

起動: streamlit run app.py
"""

from __future__ import annotations

import os
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

from gemini_client import make_client, stream_generate
from tools import TOOLS, TOOLS_BY_ID, Field, Tool

load_dotenv()

# 使用するモデル（画面からは変更しない。変えたいときは .env の GEMINI_MODEL で指定）
model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

st.set_page_config(page_title="AIライティングツール", page_icon="✍️", layout="wide")

HISTORY_PAGE = "__history__"
MAX_HISTORY = 50

# ---------------------------------------------------------------------------
# セッション状態
# ---------------------------------------------------------------------------
ss = st.session_state
ss.setdefault("results", {})   # tool_id -> {"prompt": str, "output": str}
ss.setdefault("history", [])   # 新しい順の生成履歴

# ツールを切り替えても入力値が消えないようにするための定番ワークアラウンド
for k in list(ss.keys()):
    if isinstance(k, str) and k.startswith("f__"):
        ss[k] = ss[k]


def widget_key(tool: Tool, f: Field) -> str:
    return f"f__{tool.id}__{f.key}"


# ---------------------------------------------------------------------------
# サイドバー
# ---------------------------------------------------------------------------
def get_secret_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    if not key:
        try:
            key = st.secrets.get("GEMINI_API_KEY", "")
        except Exception:
            key = ""
    return key


with st.sidebar:
    st.title("✍️ AIライティング")

    page = st.radio(
        "ツール",
        [t.id for t in TOOLS] + [HISTORY_PAGE],
        format_func=lambda i: "🕘 生成履歴" if i == HISTORY_PAGE else f"{TOOLS_BY_ID[i].icon} {TOOLS_BY_ID[i].name}",
        label_visibility="collapsed",
    )

    st.divider()
    with st.expander("⚙️ 設定", expanded=not get_secret_api_key()):
        env_key = get_secret_api_key()
        api_key = st.text_input(
            "Gemini APIキー",
            value=env_key,
            type="password",
            help="`.env` に GEMINI_API_KEY を書いておくと自動で読み込まれます。",
        )
        temp_mode = st.radio("創造性（temperature）", ["ツールごとの推奨値", "手動"], horizontal=True)
        manual_temp = st.slider("temperature", 0.0, 2.0, 0.7, 0.1, disabled=temp_mode != "手動")


def client_or_stop():
    if not api_key:
        st.error("サイドバーの「⚙️ 設定」で Gemini APIキーを入力してください。")
        st.stop()
    return make_client(api_key)


def run_generation(tool: Tool, prompt: str) -> str | None:
    """プロンプトを Gemini に送り、ストリーミング表示して全文を返す。"""
    client = client_or_stop()
    temperature = manual_temp if temp_mode == "手動" else tool.temperature
    try:
        with st.container(border=True):
            output = st.write_stream(
                stream_generate(client, model, prompt, tool.system_instruction, temperature)
            )
    except Exception as e:  # APIキー不正・レート制限など
        st.error(f"生成中にエラーが発生しました: {e}")
        return None
    output = output if isinstance(output, str) else "".join(map(str, output))
    ss.results[tool.id] = {"prompt": prompt, "output": output}
    ss.history.insert(0, {
        "time": datetime.now().strftime("%m/%d %H:%M"),
        "tool_id": tool.id,
        "model": model,
        "prompt": prompt,
        "output": output,
    })
    del ss.history[MAX_HISTORY:]
    return output


def show_output(text: str, key: str) -> None:
    tab_preview, tab_raw = st.tabs(["プレビュー", "テキスト（コピー用）"])
    with tab_preview:
        with st.container(border=True):
            st.markdown(text)
    with tab_raw:
        st.code(text, language="markdown", wrap_lines=True)
    c1, c2 = st.columns([1, 3])
    c1.download_button(
        "⬇️ ダウンロード (.md)",
        data=text.encode("utf-8"),
        file_name=f"{key}_{datetime.now():%Y%m%d_%H%M%S}.md",
        mime="text/markdown",
        key=f"dl_{key}",
    )
    c2.caption(f"文字数: {len(text):,}文字（空白・改行除く: {len(''.join(text.split())):,}文字）")


# ---------------------------------------------------------------------------
# 履歴ページ
# ---------------------------------------------------------------------------
if page == HISTORY_PAGE:
    st.header("🕘 生成履歴")
    st.caption(f"このブラウザセッション中の生成結果（最新{MAX_HISTORY}件）です。ページを再読み込みすると消えます。")
    if not ss.history:
        st.info("まだ生成履歴はありません。")
    else:
        if st.button("🗑️ 履歴をすべて削除"):
            ss.history = []
            st.rerun()
        for i, h in enumerate(ss.history):
            t = TOOLS_BY_ID[h["tool_id"]]
            preview = h["output"].strip().splitlines()[0][:40] if h["output"].strip() else ""
            with st.expander(f"{h['time']}　{t.icon} {t.name}　— {preview}"):
                st.caption(f"モデル: {h['model']}")
                with st.popover("送信したプロンプトを見る"):
                    st.code(h["prompt"], language="markdown", wrap_lines=True)
                show_output(h["output"], key=f"hist_{i}")
    st.stop()

# ---------------------------------------------------------------------------
# ツールページ
# ---------------------------------------------------------------------------
tool = TOOLS_BY_ID[page]
st.header(f"{tool.icon} {tool.name}")
st.caption(tool.description)

col_in, col_out = st.columns([2, 3], gap="large")


def render_field(f: Field):
    key = widget_key(tool, f)
    label = f.label + (" *" if f.required else "")
    # 初期値は Session State 経由で与える（value 引数と併用すると警告が出るため）
    if f.kind == "select":
        ss.setdefault(key, f.default if f.default in f.options else f.options[0])
        return st.selectbox(label, f.options, key=key, help=f.help)
    if f.kind == "slider":
        ss.setdefault(key, f.default if f.default is not None else f.min_value)
        return st.slider(label, f.min_value, f.max_value, step=f.step, key=key, help=f.help)
    ss.setdefault(key, "")
    if f.kind == "textarea":
        return st.text_area(label, key=key, height=f.height, placeholder=f.placeholder, help=f.help)
    return st.text_input(label, key=key, placeholder=f.placeholder, help=f.help)


with col_in:
    # st.form を使うと未送信の入力がページ切替で消えるため、通常のウィジェットで構成
    values = {f.key: render_field(f) for f in tool.fields}
    submitted = st.button("✨ 生成する", type="primary", use_container_width=True, key=f"gen_{tool.id}")

with col_out:
    if submitted:
        missing = [f.label for f in tool.fields if f.required and not str(values[f.key]).strip()]
        if missing:
            st.warning("必須項目を入力してください: " + "、".join(missing))
        else:
            with st.spinner("生成中..."):
                if run_generation(tool, tool.build_prompt(values)) is not None:
                    st.rerun()

    result = ss.results.get(tool.id)
    if result and not submitted:
        show_output(result["output"], key=tool.id)

        # 生成結果への追加指示（ブラッシュアップ）
        st.divider()
        with st.form(f"refine_{tool.id}", clear_on_submit=True, border=False):
            refine = st.text_input(
                "🔧 この結果を修正する",
                placeholder="例: もっと短く / 結論を先に / 具体例を1つ追加して",
            )
            do_refine = st.form_submit_button("修正して再生成")
        if do_refine and refine.strip():
            prompt = (
                f"{result['prompt']}\n\n"
                f"---\n## 前回の出力\n{result['output']}\n\n"
                f"---\n上記の前回の出力に対して、次の修正指示を反映した完成版を出力してください。\n"
                f"修正指示: {refine}"
            )
            with st.spinner("修正中..."):
                if run_generation(tool, prompt) is not None:
                    st.rerun()
    elif not result and not submitted:
        st.info("左のフォームに入力して「✨ 生成する」を押すと、ここに結果が表示されます。")
