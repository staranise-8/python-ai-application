"""Streamlit + LLM アプリ向けの簡易セキュリティスキャナー（標準ライブラリのみ）。

使い方: python scan.py <対象ディレクトリ>

出力は「調べるべき候補」の一覧であり、確定した脆弱性ではない。
秘密情報の値は必ず伏せ字にして表示する（ログに値を残さないため）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SKIP_DIRS = {
    ".venv", "venv", "env", ".git", "node_modules", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "site-packages", ".claude", ".agents", "dist", "build",
}
TEXT_SUFFIXES = {
    ".py", ".toml", ".env", ".txt", ".cfg", ".ini", ".yaml", ".yml", ".json",
    ".md", ".sh", ".ps1", ".js", ".ts", ".html", ".ipynb",
}
MAX_BYTES = 2_000_000

SECRET_PATTERNS = [
    ("Google/Gemini APIキー", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("Anthropic APIキー", re.compile(r"sk-ant-[0-9A-Za-z_\-]{20,}")),
    ("OpenAI APIキー", re.compile(r"sk-(?:proj-|svcacct-)?(?!ant-)[0-9A-Za-z_\-]{20,}")),
    ("Groq APIキー", re.compile(r"gsk_[0-9A-Za-z]{20,}")),
    ("Hugging Face トークン", re.compile(r"hf_[0-9A-Za-z]{30,}")),
    ("AWS アクセスキー", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("秘密鍵", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("キーらしき代入", re.compile(
        r"""(?i)\b\w*(?:api_?key|secret|token|password)\w*\s*[:=]\s*["']?([0-9A-Za-z_\-]{24,})""")),
]
PLACEHOLDER = re.compile(r"(?i)your|example|xxx|dummy|changeme|placeholder|<|\*\*\*")

RISKY_PATTERNS = [
    ("XSS", r"unsafe_allow_html\s*=\s*True", "LLM出力/ユーザー入力を渡していないか"),
    ("XSS", r"\bst\.html\(|components\.v1\.html|components\.html\(", "信頼できない内容を描画していないか"),
    ("コード実行", r"\beval\(|\bexec\(", "LLM出力・ユーザー入力が届かないか"),
    ("コード実行", r"\bsubprocess\b|os\.system\(|shell\s*=\s*True", "引数にLLM出力・入力が入らないか"),
    ("デシリアライズ", r"pickle\.loads?\(|torch\.load\(|joblib\.load\(|yaml\.load\((?![^)]*SafeLoader)", "アップロードファイルを読んでいないか"),
    ("ユーザー間共有", r"@st\.cache_data|@st\.cache_resource|st\.cache_data\(|st\.cache_resource\(", "ユーザー固有データ/キーを入れていないか"),
    ("キー露出", r"type\s*=\s*[\"']password[\"']", "value= にサーバー側キーを渡していないか（ブラウザに送られる）"),
    ("キー露出", r"st\.(write|json|code|text)\(\s*(os\.environ|st\.secrets)", "環境変数/secretsを画面表示"),
    ("エラー表示", r"st\.exception\(|st\.error\(f?[\"'][^\"']*\{\s*(e|err|ex|exc|error)\s*\}", "例外詳細を利用者に表示"),
    ("SSRF", r"requests\.(get|post)\(|httpx\.|urllib\.request|urlopen\(", "URLがユーザー入力由来でないか"),
    ("入力", r"st\.file_uploader\(", "type=/サイズ/保存先パスを確認"),
    ("ネットワーク", r"0\.0\.0\.0|server\.address", "待受アドレス"),
    ("LLM設定", r"BLOCK_NONE|HarmBlockThreshold\.OFF", "安全フィルター無効化"),
    ("設定", r"enableXsrfProtection\s*=\s*false|enableCORS\s*=\s*false", "CSRF/CORS保護の無効化"),
]
LLM_CALL = re.compile(
    r"generate_content(_stream)?\(|chat\.completions\.create\(|messages\.(create|stream)\(|responses\.create\(|\.invoke\(|\.stream\(")
TOKEN_LIMIT = re.compile(r"max_output_tokens|max_tokens|max_completion_tokens|max_new_tokens")


def mask(s: str) -> str:
    return f"{s[:4]}…({len(s)}文字)"


def iter_files(root: Path):
    for p in root.rglob("*"):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts[:-1]):
            continue
        if not p.is_file():
            continue
        if p.suffix.lower() in TEXT_SUFFIXES or p.name.startswith(".env") or p.name in {"Dockerfile", ".gitignore", ".dockerignore"}:
            try:
                if p.stat().st_size <= MAX_BYTES:
                    yield p
            except OSError:
                pass


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    files = list(iter_files(root))
    rel = lambda p: p.relative_to(root).as_posix()  # noqa: E731

    print(f"# スキャン対象: {root}（{len(files)} ファイル）\n")

    # 1. 秘密情報
    print("## 秘密情報らしき文字列（値は伏せ字）")
    found = 0
    for p in files:
        for i, line in enumerate(read(p).splitlines(), 1):
            hit = None
            for label, pat in SECRET_PATTERNS:
                for m in pat.finditer(line):
                    val = m.group(1) if m.groups() else m.group(0)
                    if PLACEHOLDER.search(val):
                        continue
                    hit = (label, val)
                    break
                if hit:
                    break  # 1行につき最も具体的な1件だけ表示
            if hit:
                found += 1
                print(f"- {rel(p)}:{i}  [{hit[0]}] {mask(hit[1])}")
    if not found:
        print("- 該当なし")

    # 2. 危険パターン
    print("\n## 要確認のコードパターン")
    found = 0
    for p in files:
        if p.suffix not in {".py", ".toml", ".sh", ".ps1"} and p.name != "Dockerfile":
            continue
        for i, line in enumerate(read(p).splitlines(), 1):
            for cat, pat, hint in RISKY_PATTERNS:
                if re.search(pat, line):
                    found += 1
                    print(f"- {rel(p)}:{i}  [{cat}] {hint}  | {line.strip()[:120]}")
    if not found:
        print("- 該当なし")

    # 3. LLM 呼び出しとトークン上限
    print("\n## LLM 呼び出しと出力トークン上限")
    py = [p for p in files if p.suffix == ".py"]
    calls = [(p, i) for p in py for i, l in enumerate(read(p).splitlines(), 1) if LLM_CALL.search(l)]
    has_limit = any(TOKEN_LIMIT.search(read(p)) for p in py)
    if calls:
        for p, i in calls:
            print(f"- 呼び出し: {rel(p)}:{i}")
        print(f"- 出力トークン上限の指定: {'あり' if has_limit else 'なし（プロジェクト内に見当たらない）'}")
    else:
        print("- LLM 呼び出しは検出されなかった（SDK の使い方が独特な可能性あり。手動で確認）")

    # 4. .gitignore / .dockerignore
    print("\n## 無視設定")
    for name, needed in [(".gitignore", [".env", "secrets.toml"]), (".dockerignore", [".env", ".git", "secrets.toml"])]:
        f = root / name
        if not f.exists():
            print(f"- {name}: なし")
            continue
        text = read(f)
        missing = [n for n in needed if n not in text]
        print(f"- {name}: " + ("必要な項目あり" if not missing else f"不足 → {', '.join(missing)}"))
    for name in [".env", ".streamlit/secrets.toml"]:
        print(f"- {name}: {'存在する' if (root / name).exists() else 'なし'}")
    if (root / ".git").exists():
        print("- git リポジトリ: はい（`git ls-files` と履歴の確認を行うこと）")
    else:
        print("- git リポジトリ: いいえ")

    # 5. 依存関係
    print("\n## 依存関係のバージョン指定")
    req = root / "requirements.txt"
    if req.exists():
        for line in read(req).splitlines():
            s = line.split("#")[0].strip()
            if not s or s.startswith("-"):
                continue
            status = "固定" if "==" in s else ("未指定" if not re.search(r"[<>=~!]", s) else "範囲指定（未固定）")
            print(f"- {s}: {status}")
    else:
        print("- requirements.txt なし（pyproject.toml / lock ファイルを手動確認）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
