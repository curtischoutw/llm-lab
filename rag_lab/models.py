"""把 .env 裡的三個 OpenAI 相容端點包成 RAG-Anything 需要的模型函式。

為什麼存在：RAG-Anything 需要 llm_model_func、vision_model_func、embedding_func。
這裡用 lightrag 內建的 OpenAI 相容 helper 組出來，程式本身不 import mlx，
所以本地 MLX server 與大機器上的 vLLM／雲端 API 可以只靠 .env 互換。

關鍵設計決策：
- 函式寫成模組層級（不用 closure），沿用官方 LM Studio 範例的 pickle-safe 寫法。
- embedding 用非對稱：文件端不加前綴，查詢端加 EMBED_QUERY_PREFIX
  （LightRAG 以 context="document"／"query" 區分）。
- vision 呼叫明確帶 max_tokens，避免 server 的預設值截斷圖表描述。

Dependencies: lightrag-hku、raganything（由 raganything 帶入）。
"""

import base64
from typing import Any

import numpy as np
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from raganything.image_signature import image_mime_type

from rag_lab.config import get_settings

# ==============================
# LLM
# ==============================


async def llm_model_func(
    prompt: str,
    system_prompt: str | None = None,
    history_messages: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> str:
    """文字 LLM 呼叫（實體抽取、答案生成）。

    Args:
        prompt: 使用者提示。
        system_prompt: 系統提示。
        history_messages: 歷史訊息。
        **kwargs: 轉給 openai_complete_if_cache。

    Returns:
        模型回覆文字。
    """
    s = get_settings()
    kwargs.setdefault("max_tokens", s.llm_max_tokens)
    return await openai_complete_if_cache(
        s.llm_model,
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages or [],
        base_url=s.llm_base_url,
        api_key=s.llm_api_key,
        **kwargs,
    )


# ==============================
# VLM
# ==============================


async def vision_model_func(
    prompt: str,
    system_prompt: str | None = None,
    history_messages: list[dict[str, Any]] | None = None,
    image_data: str | None = None,
    messages: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> str:
    """看圖模型呼叫。三種輸入形式沿用 RAG-Anything 官方範例的分支。

    Args:
        prompt: 提示文字。
        system_prompt: 系統提示。
        history_messages: 歷史訊息（純文字分支才會用到）。
        image_data: 單張圖片的 base64（無 data URI 前綴）。
        messages: 已組好的多模態 messages（VLM 增強查詢使用），有值時直接使用。
        **kwargs: 轉給 openai_complete_if_cache。

    Returns:
        模型回覆文字。
    """
    s = get_settings()
    kwargs.setdefault("max_tokens", s.vlm_max_tokens)
    common = {"base_url": s.vlm_base_url, "api_key": s.vlm_api_key}

    if messages:
        return await openai_complete_if_cache(
            s.vlm_model, "", system_prompt=None, history_messages=[], messages=messages, **common, **kwargs
        )

    if image_data:
        mime = image_mime_type(base64.b64decode(image_data[:24])) or "image/jpeg"
        built: list[dict[str, Any]] = []
        if system_prompt:
            built.append({"role": "system", "content": system_prompt})
        built.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_data}"}},
                ],
            }
        )
        return await openai_complete_if_cache(
            s.vlm_model, "", system_prompt=None, history_messages=[], messages=built, **common, **kwargs
        )

    return await llm_model_func(prompt, system_prompt, history_messages, **kwargs)


# ==============================
# Embedding
# ==============================


async def embed_texts(texts: list[str], context: str = "document") -> np.ndarray:
    """呼叫 embedding 端點。

    Args:
        texts: 待嵌入文字。
        context: "document"（建索引）或 "query"（檢索），由 LightRAG 傳入。

    Returns:
        shape 為 (len(texts), EMBED_DIM) 的 ndarray。
    """
    s = get_settings()
    return await openai_embed.func(
        texts,
        model=s.embed_model,
        base_url=s.embed_base_url,
        api_key=s.embed_api_key,
        context=context,
        query_prefix=s.embed_query_prefix or None,
    )


def build_embedding_func() -> EmbeddingFunc:
    """組出 LightRAG 的 EmbeddingFunc。

    Returns:
        帶維度檢查、非對稱 context 的 EmbeddingFunc。
    """
    s = get_settings()
    return EmbeddingFunc(
        embedding_dim=s.embed_dim,
        max_token_size=s.embed_max_token_size,
        func=embed_texts,
        model_name=s.embed_model,
        supports_asymmetric=True,
    )
