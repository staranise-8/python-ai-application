"""ライティングツールの定義。

ツールを追加したいときは `Tool(...)` を TOOLS リストに足すだけでよい。
- fields: 画面に表示する入力欄
- build_prompt: 入力値の dict を受け取り、Gemini に渡すプロンプト文字列を返す
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

FieldKind = Literal["text", "textarea", "select", "slider"]


@dataclass
class Field:
    key: str
    label: str
    kind: FieldKind = "text"
    required: bool = False
    placeholder: str = ""
    options: list[str] = field(default_factory=list)
    default: Any = None
    min_value: int = 0
    max_value: int = 100
    step: int = 1
    height: int = 150
    help: str | None = None


@dataclass
class Tool:
    id: str
    name: str
    icon: str
    description: str
    fields: list[Field]
    build_prompt: Callable[[dict[str, Any]], str]
    system_instruction: str = (
        "あなたは日本語のプロのライター兼編集者です。"
        "読みやすく自然な日本語で、依頼に忠実に出力してください。"
        "前置きや「承知しました」などの返事は書かず、成果物のみを出力してください。"
    )
    temperature: float = 0.7


def _opt(label: str, value: Any) -> str:
    """値が空でない場合だけ「- ラベル: 値」の行を返す。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return ""
    return f"- {label}: {value}\n"


TONES = ["丁寧・フォーマル", "親しみやすい", "カジュアル", "論理的・ビジネス", "熱量高め", "落ち着いた"]


# ---------------------------------------------------------------------------
# 各ツールのプロンプト生成
# ---------------------------------------------------------------------------

def _blog(v: dict) -> str:
    return (
        "以下の条件でブログ記事を Markdown で執筆してください。\n\n"
        f"- テーマ: {v['topic']}\n"
        + _opt("想定読者", v["audience"])
        + _opt("含めたいキーワード", v["keywords"])
        + f"- 文体・トーン: {v['tone']}\n"
        + f"- 目安の文字数: 約{v['length']}文字\n"
        + _opt("構成・補足の指示", v["notes"])
        + "\n# 出力形式\n"
        "1. 1行目に `# 記事タイトル`\n"
        "2. 導入文（読者の悩みや興味に触れる）\n"
        "3. `##` / `###` 見出しで構造化した本文（必要に応じて箇条書き）\n"
        "4. まとめ\n"
        "最後に `---` で区切り、SEO向けのメタディスクリプション案（120文字以内）を1つ添えてください。"
    )


def _email(v: dict) -> str:
    return (
        "以下の受信メールに対する返信メールを作成してください。\n\n"
        f"## 受信メール\n{v['received']}\n\n"
        "## 返信の条件\n"
        + _opt("返信で伝えたい要点", v["points"])
        + f"- 相手との関係: {v['relation']}\n"
        + f"- トーン: {v['tone']}\n"
        + _opt("差出人（自分）の名前", v["sender"])
        + "\n件名（`件名: Re: ...` の形式）と本文を出力してください。"
        "要点が指定されていない部分は、無難で失礼のない内容で補ってください。"
        "日付や固有名詞など不明な情報は【　】で空欄にしてください。"
    )


def _email_new(v: dict) -> str:
    return (
        "以下の条件で新規メールを作成してください。\n\n"
        f"- 目的・用件: {v['purpose']}\n"
        + _opt("宛先", v["to"])
        + f"- 相手との関係: {v['relation']}\n"
        + f"- トーン: {v['tone']}\n"
        + _opt("盛り込みたい内容", v["details"])
        + _opt("差出人（自分）の名前", v["sender"])
        + "\n件名（`件名: ...` の形式）と本文を出力してください。"
        "不明な情報は【　】で空欄にしてください。"
    )


def _summary(v: dict) -> str:
    styles = {
        "箇条書き": "重要なポイントを箇条書きで",
        "短い文章": "自然な文章で",
        "3行要約": "ちょうど3行で",
        "見出し付きレポート": "見出しを付けたレポート形式（Markdown）で",
        "TL;DR + 詳細": "冒頭に1文のTL;DR、その後に箇条書きの詳細という形で",
    }
    return (
        f"次の文章を{styles[v['style']]}要約してください。\n"
        f"- 目安の長さ: 約{v['length']}文字\n"
        + _opt("特に重視する観点", v["focus"])
        + "原文にない情報は加えないでください。\n\n"
        f"## 原文\n{v['source']}"
    )


def _proofread(v: dict) -> str:
    return (
        "次の文章を校正してください。\n"
        f"- 修正レベル: {v['level']}\n\n"
        "# 出力形式\n"
        "## 修正後の文章\n（修正後の全文）\n\n"
        "## 主な修正点\n"
        "| 修正前 | 修正後 | 理由 |\n|---|---|---|\n"
        "（誤字脱字・文法・表記ゆれ・読みやすさの観点で、主な修正を表にまとめる）\n\n"
        f"## 原文\n{v['source']}"
    )


def _rewrite(v: dict) -> str:
    return (
        "次の文章をリライトしてください。\n"
        f"- 変換後のトーン: {v['tone']}\n"
        f"- 長さ: {v['length']}\n"
        + _opt("想定読者", v["audience"])
        + _opt("その他の指示", v["notes"])
        + "元の意味や事実関係は変えないでください。リライト後の文章のみを出力してください。\n\n"
        f"## 原文\n{v['source']}"
    )


def _translate(v: dict) -> str:
    return (
        f"次の文章を{v['target']}に翻訳してください。\n"
        f"- スタイル: {v['style']}\n"
        + ("- 翻訳文の後に、訳し方の補足や注意点があれば簡潔に添えてください。\n" if v["explain"] == "あり" else
           "- 翻訳文のみを出力してください。\n")
        + f"\n## 原文\n{v['source']}"
    )


def _sns(v: dict) -> str:
    return (
        f"{v['platform']} 向けの投稿文を {v['count']} パターン作成してください。\n\n"
        f"- 内容・伝えたいこと: {v['content']}\n"
        + f"- トーン: {v['tone']}\n"
        + _opt("ターゲット", v["audience"])
        + f"- ハッシュタグ: {v['hashtags']}\n"
        + f"- 絵文字: {v['emoji']}\n"
        + "\nプラットフォームの文字数制限や慣習（X なら140字目安、Instagram なら改行多め等）に合わせてください。"
        "各パターンは `### パターン1` のように見出しで区切ってください。"
    )


def _title(v: dict) -> str:
    return (
        f"次の内容に対する「{v['kind']}」の案を {v['count']} 個出してください。\n\n"
        f"- 内容: {v['content']}\n"
        + _opt("ターゲット", v["audience"])
        + _opt("入れたいキーワード", v["keywords"])
        + f"- 方向性: {v['style']}\n"
        + "\n番号付きリストで出力し、各案の後ろに（ねらい: ...）を短く添えてください。"
        "最後に、おすすめの1案とその理由を書いてください。"
    )


def _outline(v: dict) -> str:
    return (
        f"「{v['topic']}」について{v['format']}を書くための構成案を作ってください。\n\n"
        + _opt("想定読者", v["audience"])
        + _opt("ゴール（読後に読者にどうなってほしいか）", v["goal"])
        + "\n# 出力形式\n"
        "- タイトル案を3つ\n"
        "- 見出し構成（Markdown の見出しで階層化し、各見出しの下に書くべき要点を箇条書き）\n"
        "- 読者の検索意図・悩みの想定\n"
        "- 差別化のためのアイデア"
    )


def _ideas(v: dict) -> str:
    return (
        f"次のテーマについて、ネタ・アイデアを {v['count']} 個ブレインストーミングしてください。\n\n"
        f"- テーマ: {v['theme']}\n"
        + _opt("用途", v["purpose"])
        + _opt("条件・制約", v["constraints"])
        + "\n定番のものだけでなく、意外性のある切り口も混ぜてください。"
        "各アイデアは「**タイトル**: 一言説明」の形式の番号付きリストで出力してください。"
    )


def _expand(v: dict) -> str:
    return (
        "次の箇条書き・メモを、自然につながる文章に仕上げてください。\n"
        f"- 文章の種類: {v['kind']}\n"
        f"- トーン: {v['tone']}\n"
        f"- 目安の文字数: 約{v['length']}文字\n"
        "メモにない事実は勝手に作らず、つなぎの表現で補う程度にしてください。\n\n"
        f"## メモ\n{v['memo']}"
    )


def _free(v: dict) -> str:
    return v["instruction"] + (f"\n\n## 参考テキスト\n{v['context']}" if v["context"].strip() else "")


# ---------------------------------------------------------------------------
# ツール一覧
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        id="blog",
        name="ブログ記事作成",
        icon="📝",
        description="テーマを入力するだけで、見出し付きのブログ記事を生成します。",
        fields=[
            Field("topic", "記事のテーマ", required=True, placeholder="例: 初心者向け Python 学習ロードマップ"),
            Field("audience", "想定読者", placeholder="例: プログラミング未経験の社会人"),
            Field("keywords", "含めたいキーワード（カンマ区切り）", placeholder="例: Python, 独学, おすすめ教材"),
            Field("tone", "文体・トーン", kind="select", options=["です・ます調（親しみやすい）", "です・ます調（専門的）", "だ・である調", "カジュアル"]),
            Field("length", "目安の文字数", kind="slider", min_value=500, max_value=6000, step=500, default=2000),
            Field("notes", "構成・補足の指示（任意）", kind="textarea", height=100, placeholder="例: 体験談を入れる / 最後に教材比較表を入れる"),
        ],
        build_prompt=_blog,
        temperature=0.8,
    ),
    Tool(
        id="email_reply",
        name="メール返信作成",
        icon="✉️",
        description="受け取ったメールを貼り付けると、適切な返信文を作成します。",
        fields=[
            Field("received", "受信したメール", kind="textarea", required=True, height=200, placeholder="返信したいメールの本文を貼り付けてください"),
            Field("points", "返信で伝えたい要点（任意）", kind="textarea", height=100, placeholder="例: 日程は来週火曜なら可能 / 見積もりは金曜までに送る"),
            Field("relation", "相手との関係", kind="select", options=["社外（取引先・顧客）", "社内（上司）", "社内（同僚・部下）", "友人・知人", "その他"]),
            Field("tone", "トーン", kind="select", options=["丁寧・フォーマル", "やや丁寧", "カジュアル", "お詫び", "お断り（角を立てずに）"]),
            Field("sender", "自分の名前（署名用・任意）", placeholder="例: 山田"),
        ],
        build_prompt=_email,
        temperature=0.6,
    ),
    Tool(
        id="email_new",
        name="新規メール作成",
        icon="📨",
        description="用件を伝えるだけで、新しく送るメールの文面を作成します。",
        fields=[
            Field("purpose", "目的・用件", required=True, placeholder="例: 打ち合わせ日程の調整をお願いしたい"),
            Field("to", "宛先（任意）", placeholder="例: 株式会社〇〇 佐藤様"),
            Field("relation", "相手との関係", kind="select", options=["社外（取引先・顧客）", "社内（上司）", "社内（同僚・部下）", "友人・知人", "その他"]),
            Field("tone", "トーン", kind="select", options=["丁寧・フォーマル", "やや丁寧", "カジュアル", "お詫び", "お願い"]),
            Field("details", "盛り込みたい内容（任意）", kind="textarea", height=120),
            Field("sender", "自分の名前（署名用・任意）"),
        ],
        build_prompt=_email_new,
        temperature=0.6,
    ),
    Tool(
        id="summary",
        name="文章要約",
        icon="📋",
        description="長い文章を、指定した形式と長さで要約します。",
        fields=[
            Field("source", "要約したい文章", kind="textarea", required=True, height=280),
            Field("style", "要約の形式", kind="select", options=["箇条書き", "短い文章", "3行要約", "見出し付きレポート", "TL;DR + 詳細"]),
            Field("length", "目安の文字数", kind="slider", min_value=50, max_value=1500, step=50, default=300),
            Field("focus", "特に重視する観点（任意）", placeholder="例: 結論と今後のアクション"),
        ],
        build_prompt=_summary,
        temperature=0.3,
    ),
    Tool(
        id="proofread",
        name="文章校正",
        icon="🔍",
        description="誤字脱字・文法・表記ゆれをチェックし、修正点を一覧で示します。",
        fields=[
            Field("source", "校正したい文章", kind="textarea", required=True, height=280),
            Field("level", "修正レベル", kind="select", options=[
                "誤字脱字・文法の誤りのみ（最小限）",
                "標準（誤り＋読みにくい箇所）",
                "しっかり（より伝わる表現に積極的に改善）",
            ], default="標準（誤り＋読みにくい箇所）"),
        ],
        build_prompt=_proofread,
        temperature=0.2,
    ),
    Tool(
        id="rewrite",
        name="リライト・トーン変換",
        icon="🔄",
        description="文章の意味を保ったまま、トーンや長さを変えて書き直します。",
        fields=[
            Field("source", "元の文章", kind="textarea", required=True, height=250),
            Field("tone", "変換後のトーン", kind="select", options=TONES + ["子どもにもわかるやさしい表現", "プレゼン・スピーチ向け"]),
            Field("length", "長さ", kind="select", options=["ほぼ同じ", "短く簡潔に", "より詳しく"]),
            Field("audience", "想定読者（任意）"),
            Field("notes", "その他の指示（任意）", placeholder="例: 専門用語を減らす"),
        ],
        build_prompt=_rewrite,
        temperature=0.7,
    ),
    Tool(
        id="translate",
        name="翻訳",
        icon="🌐",
        description="自然な表現で多言語に翻訳します。",
        fields=[
            Field("source", "翻訳したい文章", kind="textarea", required=True, height=250),
            Field("target", "翻訳先の言語", kind="select", options=["英語", "日本語", "中国語（簡体字）", "中国語（繁体字）", "韓国語", "スペイン語", "フランス語", "ドイツ語"]),
            Field("style", "スタイル", kind="select", options=["自然な意訳", "原文に忠実な直訳寄り", "ビジネス向け", "カジュアル"]),
            Field("explain", "訳の補足説明", kind="select", options=["なし", "あり"]),
        ],
        build_prompt=_translate,
        temperature=0.3,
    ),
    Tool(
        id="sns",
        name="SNS投稿作成",
        icon="📣",
        description="X・Instagram などに合わせた投稿文を複数パターン生成します。",
        fields=[
            Field("content", "投稿で伝えたいこと", kind="textarea", required=True, height=120, placeholder="例: 新しいブログ記事『Python学習ロードマップ』を公開した"),
            Field("platform", "プラットフォーム", kind="select", options=["X（Twitter）", "Instagram", "Threads", "Facebook", "LinkedIn", "note"]),
            Field("tone", "トーン", kind="select", options=TONES),
            Field("audience", "ターゲット（任意）"),
            Field("hashtags", "ハッシュタグ", kind="select", options=["適度に付ける", "多めに付ける", "付けない"]),
            Field("emoji", "絵文字", kind="select", options=["適度に使う", "多めに使う", "使わない"]),
            Field("count", "パターン数", kind="slider", min_value=1, max_value=5, default=3),
        ],
        build_prompt=_sns,
        temperature=0.9,
    ),
    Tool(
        id="title",
        name="タイトル・キャッチコピー",
        icon="💡",
        description="記事タイトル、キャッチコピー、メール件名などの案を量産します。",
        fields=[
            Field("content", "対象の内容", kind="textarea", required=True, height=120, placeholder="例: 30代から始める筋トレ習慣についての記事"),
            Field("kind", "種類", kind="select", options=["ブログ記事タイトル", "キャッチコピー", "メール件名", "YouTube動画タイトル", "商品名・サービス名", "見出し"]),
            Field("style", "方向性", kind="select", options=["バランスよく色々", "クリックされやすい（煽りすぎない）", "シンプル・端的", "エモーショナル", "数字や具体性を使う"]),
            Field("audience", "ターゲット（任意）"),
            Field("keywords", "入れたいキーワード（任意）"),
            Field("count", "案の数", kind="slider", min_value=3, max_value=20, default=10),
        ],
        build_prompt=_title,
        temperature=1.0,
    ),
    Tool(
        id="outline",
        name="構成案作成",
        icon="🗂️",
        description="記事・資料・プレゼンなどの見出し構成を設計します。",
        fields=[
            Field("topic", "テーマ", required=True),
            Field("format", "作るもの", kind="select", options=["ブログ記事", "プレゼン資料", "レポート", "YouTube台本", "企画書", "書籍・電子書籍"]),
            Field("audience", "想定読者（任意）"),
            Field("goal", "ゴール（任意）", placeholder="例: 読者が今日から学習を始められる状態になる"),
        ],
        build_prompt=_outline,
        temperature=0.7,
    ),
    Tool(
        id="ideas",
        name="アイデア出し",
        icon="🧠",
        description="ブログのネタ、企画、切り口などをブレインストーミングします。",
        fields=[
            Field("theme", "テーマ", required=True, placeholder="例: 在宅ワークの生産性"),
            Field("purpose", "用途（任意）", placeholder="例: ブログのネタ / 社内イベント企画"),
            Field("constraints", "条件・制約（任意）"),
            Field("count", "アイデア数", kind="slider", min_value=5, max_value=30, step=5, default=10),
        ],
        build_prompt=_ideas,
        temperature=1.0,
    ),
    Tool(
        id="expand",
        name="メモから文章化",
        icon="✍️",
        description="箇条書きや走り書きのメモを、読みやすい文章に仕上げます。",
        fields=[
            Field("memo", "メモ・箇条書き", kind="textarea", required=True, height=220, placeholder="- 今日の会議\n- 新機能リリースは12月\n- テスト担当を募集"),
            Field("kind", "文章の種類", kind="select", options=["一般的な文章", "日報・報告書", "議事録", "ブログの段落", "自己紹介文", "スピーチ原稿"]),
            Field("tone", "トーン", kind="select", options=TONES),
            Field("length", "目安の文字数", kind="slider", min_value=100, max_value=3000, step=100, default=500),
        ],
        build_prompt=_expand,
        temperature=0.6,
    ),
    Tool(
        id="free",
        name="フリー指示",
        icon="🪄",
        description="上記にない文章作成を、自由な指示で依頼できます。",
        fields=[
            Field("instruction", "指示", kind="textarea", required=True, height=150, placeholder="例: 退職の挨拶文を、お世話になった部署向けに200字程度で書いて"),
            Field("context", "参考テキスト（任意）", kind="textarea", height=180),
        ],
        build_prompt=_free,
        temperature=0.7,
    ),
]

TOOLS_BY_ID: dict[str, Tool] = {t.id: t for t in TOOLS}
