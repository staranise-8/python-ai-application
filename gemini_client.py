"""Gemini API との通信をまとめたモジュール。"""

from __future__ import annotations

from collections.abc import Iterator

from google import genai
from google.genai import types

DEFAULT_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash-lite",
]


def make_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


def list_text_models(client: genai.Client) -> list[str]:
    """テキスト生成に使える Gemini モデル名の一覧を返す。取得に失敗したら既定リスト。"""
    try:
        names = []
        for m in client.models.list():
            actions = getattr(m, "supported_actions", None) or []
            name = (m.name or "").removeprefix("models/")
            if "generateContent" in actions and name.startswith("gemini"):
                names.append(name)
        return sorted(set(names), reverse=True) or DEFAULT_MODELS
    except Exception:
        return DEFAULT_MODELS


def stream_generate(
    client: genai.Client,
    model: str,
    prompt: str,
    system_instruction: str,
    temperature: float,
) -> Iterator[str]:
    """生成結果をチャンクごとに yield する。"""
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=temperature,
    )
    for chunk in client.models.generate_content_stream(
        model=model, contents=prompt, config=config
    ):
        if chunk.text:
            yield chunk.text
