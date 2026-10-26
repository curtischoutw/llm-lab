"""把 .env 裡的三個 OpenAI 相容端點包成 RAG-Anything 需要的模型函式。

為什麼存在：RAG-Anything 需要 llm_model_func、vision_model_func、embedding_func。
這裡用 lightrag 內建的 OpenAI 相容 helper 組出來，程式本身不 import mlx，
所以本地 MLX server 與大機器上的 vLLM／雲端 API 可以只靠 .env 互換。

關鍵設計決策：
- 函式寫成模組層級（不用 closure），沿用官方 LM Studio 範例的 pickle-safe 寫法。
- embedding 用非對稱：文件端不加前綴，查詢端加 EMBED_QUERY_PREFIX
  （LightRAG 以 context="document"／"query" 區分）。
- vision 呼叫明確帶 max_tokens，避免 server 的預設值截斷圖表描述。
- 三個函式的失敗都包成 EndpointError，訊息帶端點名稱（LLM／VLM／Embedding）與位址：
  LightRAG 匯入失敗的訊息只含原例外文字，不指出是哪個端點。原例外以 __cause__ 保留，
  訊息內含原例外文字；API 金鑰不會出現在例外文字中，也不會被寫進訊息。
- RAG-Anything 會吞掉 VLM 的失敗（描述退成原始 dict、匯入仍成功），所以 vision 函式
  自己計數（vision_stats），讓呼叫端能事後判斷「圖片描述是否真的來自 VLM」。

已知極限：vision_stats 是模組層級狀態，同一個 process 內累計；CLI 一次只跑一個命令，
所以不需要重置。

Dependencies: lightrag-hku、raganything（由 raganything 帶入）；tenacity 為 lightrag 的相依。
"""

import base64
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import numpy as np
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from raganything.image_signature import image_mime_type
from tenacity import RetryError

from rag_lab.config import get_settings

# ==============================
# 端點錯誤與可達性
# ==============================

REACHABILITY_TIMEOUT_SEC = 5


class EndpointError(RuntimeError):
    """某個模型端點失敗。訊息帶端點名稱與位址，原例外在 __cause__。

    Attributes:
        label: 端點名稱（LLM、VLM、Embedding）。
        url: 該端點的 base URL。
    """

    def __init__(self, label: str, url: str, detail: str):
        super().__init__(f"{label} 端點 {url} 失敗：{detail}")
        self.label = label
        self.url = url


def _describe(exc: BaseException) -> str:
    """把例外轉成「型別: 文字」；tenacity 的 RetryError 先攤開成最後一次的實際例外。"""
    if isinstance(exc, RetryError):
        exc = exc.last_attempt.exception() or exc
    return f"{type(exc).__name__}: {exc}"


def check_reachable(*labels: str) -> None:
    """確認指定端點的主機與埠連得上（TCP），在長時間處理之前快速失敗。

    Args:
        *labels: "LLM"、"VLM"、"Embedding" 的任意組合。

    Raises:
        EndpointError: 其中一個端點連不上；訊息指出名稱與位址。
    """
    s = get_settings()
    urls = {"LLM": s.llm_base_url, "VLM": s.vlm_base_url, "Embedding": s.embed_base_url}
    for label in labels:
        parsed = urlparse(urls[label])
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            socket.create_connection((parsed.hostname, port), timeout=REACHABILITY_TIMEOUT_SEC).close()
        except OSError as exc:
            raise EndpointError(label, urls[label], f"無法連線（{exc}）") from exc


# ==============================
# VLM 計數
# ==============================


@dataclass
class VisionStats:
    """vision_model_func 處理圖片的成功與失敗計數。

    Attributes:
        ok: 成功呼叫次數。
        failed: 失敗呼叫次數。
        last_error: 最近一次失敗的訊息（含端點名稱與位址）。
        sample: 第一則成功的圖片描述（供人工比對原圖）。
    """

    ok: int = 0
    failed: int = 0
    last_error: str | None = None
    sample: str | None = None


vision_stats = VisionStats()

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
    try:
        return await openai_complete_if_cache(
            s.llm_model,
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages or [],
            base_url=s.llm_base_url,
            api_key=s.llm_api_key,
            **kwargs,
        )
    except Exception as exc:
        raise EndpointError("LLM", s.llm_base_url, _describe(exc)) from exc


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
        return await _vision_call(
            s.vlm_base_url,
            openai_complete_if_cache(
                s.vlm_model, "", system_prompt=None, history_messages=[], messages=messages, **common, **kwargs
            ),
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
        return await _vision_call(
            s.vlm_base_url,
            openai_complete_if_cache(
                s.vlm_model, "", system_prompt=None, history_messages=[], messages=built, **common, **kwargs
            ),
        )

    return await llm_model_func(prompt, system_prompt, history_messages, **kwargs)


async def _vision_call(url: str, call: Any) -> str:
    """執行一次帶圖片的 VLM 呼叫，計數成功／失敗，失敗時包成 EndpointError。

    Args:
        url: VLM 的 base URL（用於錯誤訊息）。
        call: 尚未 await 的 openai_complete_if_cache 協程。

    Returns:
        模型回覆文字。
    """
    try:
        text = await call
    except Exception as exc:
        error = EndpointError("VLM", url, _describe(exc))
        vision_stats.failed += 1
        vision_stats.last_error = str(error)
        raise error from exc
    vision_stats.ok += 1
    if vision_stats.sample is None:
        vision_stats.sample = text
    return text


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
    try:
        return await openai_embed.func(
            texts,
            model=s.embed_model,
            base_url=s.embed_base_url,
            api_key=s.embed_api_key,
            context=context,
            query_prefix=s.embed_query_prefix or None,
        )
    except Exception as exc:
        raise EndpointError("Embedding", s.embed_base_url, _describe(exc)) from exc


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
