"""把 .env 裡的三個 OpenAI 相容端點與 rerank 端點包成 RAG-Anything／LightRAG 需要的模型函式。

為什麼存在：RAG-Anything 需要 llm_model_func、vision_model_func、embedding_func，LightRAG 查詢時還要
rerank_model_func。這裡用 lightrag 內建的 OpenAI 相容 helper 與通用 rerank 函式組出來，程式本身不 import mlx，
所以本地 MLX server 與大機器上的 vLLM／雲端 API 可以只靠 .env 互換。

關鍵設計決策：
- 函式寫成模組層級（不用 closure），沿用官方 LM Studio 範例的 pickle-safe 寫法。
- embedding 用非對稱：文件端不加前綴，查詢端加 EMBED_QUERY_PREFIX
  （LightRAG 以 context="document"／"query" 區分）。
- vision 呼叫明確帶 max_tokens，避免 server 的預設值截斷圖表描述。
- 三個函式的失敗都包成 EndpointError，訊息帶端點名稱（LLM／VLM／Embedding）與位址：
  LightRAG 匯入失敗的訊息只含原例外文字，不指出是哪個端點。原例外以 __cause__ 保留，
  訊息內含原例外文字；API 金鑰不會出現在例外文字中，也不會被寫進訊息。
- rerank 函式沿用 lightrag.rerank.generic_rerank_api 送請求（Jina／Cohere 格式，回 index＋relevance_score），
  不自己實作 HTTP；RERANK_BASE_URL 和其他端點一樣含 /v1，請求送到 `{RERANK_BASE_URL}/rerank`。函式必須在建立
  LightRAG 時傳入（pipeline.build_rag），初始化之後才設不會對 mix 生效。
- LightRAG 的 apply_rerank_if_enabled 只攔 Exception：rerank 函式拋例外、回傳空結果或 index 超出範圍時，它都記錄後改用
  原本的排序，查詢繼續跑完並把沒經過 rerank 的答案寫進 LLM 快取（key 不含 rerank 結果），之後同一題 rerank 成功時反而
  命中這筆舊答案。所以 rerank 函式自己判定失敗（請求例外、HTTP 錯誤、空結果，或回應內容不合法：筆數不等於
  min(top_n, 候選數)、index 不是範圍內的 int 或重複、relevance_score 不是有限的數字，見 _rerank_problem），並拋出繼承
  BaseException 的 RerankFailure，穿過 LightRAG 的查詢流程，在它呼叫 LLM 產生答案、寫入快取之前中止；pipeline 的查詢入口
  （_answer、VLM 增強路徑）攔下它並轉成 PipelineError。穿過 LightRAG 安全的依據（lightrag-hku 1.4.16）：從 aquery_llm 到
  apply_rerank_if_enabled 的呼叫鏈全是同一個 task 裡直接 await，沒有 gather／create_task／限流 worker／finally，aquery_llm
  的 except 是 except Exception；Python 3.12 的 asyncio.Task 只對 KeyboardInterrupt、SystemExit 特別處理
  （asyncio/tasks.py 的 __step）。results 不是 list、項目缺 index 或 relevance_score，generic_rerank_api 內就以空結果
  或 KeyError 結束，同樣算失敗。
- RAG-Anything 會吞掉 VLM 的失敗（描述退成原始 dict、匯入仍成功），所以 vision 函式
  自己計數（vision_stats），讓呼叫端能事後判斷「圖片描述是否真的來自 VLM」。
- 表格與公式描述走 llm_model_func，失敗同樣被吞掉。所以另外提供 count_description_failures，
  由 pipeline 包在每個 modal processor 的 caption 函式上，計數（description_stats）涵蓋
  圖／表／公式所有描述失敗；ingest 的成敗以它為準，vision_stats 只用來顯示 VLM 呼叫數。
- 描述完的內容寫入索引（儲存、embedding、實體抽取、合併）失敗，RAG-Anything 也吞掉（改走逐項處理的備援流程）。
  pipeline 覆寫批次處理的方法，失敗時呼叫 record_write_failure 計入 description_stats.write_failed。

- vision_stats、description_stats 是模組層級狀態，由 pipeline 在每次 ingest 開始時以 reset_stats()
  原地清零；同一時間只有一個 Session（見 pipeline.Session），所以不會有兩次 ingest 同時寫入。

已知極限：描述只計數 caption 呼叫本身的例外；呼叫成功但回覆內容解析失敗（RAG-Anything 內部另有 fallback）
不會被計到。寫入只計批次處理的失敗，備援的逐項處理自己的單項失敗不計。

Dependencies: lightrag-hku、raganything（由 raganything 帶入）；tenacity 為 lightrag 的相依。
"""

import base64
import math
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import numpy as np
from tenacity import RetryError

from rag_lab.config import get_settings, reject_unmanaged_library_env

# 必須在 import lightrag 與 raganything 之前：它們在 import 時就讀環境變數當預設值（見 rag_lab.config）
reject_unmanaged_library_env()

from lightrag.llm.openai import openai_complete_if_cache, openai_embed  # noqa: E402
from lightrag.rerank import generic_rerank_api  # noqa: E402
from lightrag.utils import EmbeddingFunc  # noqa: E402
from raganything.image_signature import image_mime_type  # noqa: E402

# ==============================
# 端點錯誤與可達性
# ==============================

REACHABILITY_TIMEOUT_SEC = 5


class EndpointError(RuntimeError):
    """某個模型端點失敗。訊息帶端點名稱與位址，原例外在 __cause__。

    Attributes:
        label: 端點名稱（LLM、VLM、Embedding、Rerank）。
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
        *labels: "LLM"、"VLM"、"Embedding"、"Rerank" 的任意組合。

    Raises:
        EndpointError: 其中一個端點連不上；訊息指出名稱與位址。
    """
    s = get_settings()
    urls = {"LLM": s.llm_base_url, "VLM": s.vlm_base_url, "Embedding": s.embed_base_url, "Rerank": s.rerank_base_url}
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


@dataclass
class DescriptionStats:
    """RAG-Anything 吞掉的多模態失敗計數：圖／表／公式描述（所有 modal processor），與描述後的內容寫入索引。

    Attributes:
        failed: 描述呼叫失敗次數（RAG-Anything 吞掉失敗、改寫入 fallback 實體的次數）。
        last_error: 最近一次描述失敗的訊息（EndpointError 帶端點名稱與位址）。
        write_failed: 多模態內容（描述完的 chunk）寫入索引失敗次數（儲存、embedding、實體抽取、合併任一步失敗；
            RAG-Anything 吞掉失敗後改走逐項處理的備援流程，文件仍被標成已完成）。
        last_write_error: 最近一次寫入失敗的訊息。
    """

    failed: int = 0
    last_error: str | None = None
    write_failed: int = 0
    last_write_error: str | None = None


description_stats = DescriptionStats()


def reset_stats() -> None:
    """把 vision_stats 與 description_stats 原地清零，讓下一次 ingest 只計自己的呼叫。

    原地清零而不是換新物件：其他模組持有的參照（例如 `from rag_lab.models import vision_stats`）
    才不會停在舊物件上。
    """
    vision_stats.ok = vision_stats.failed = 0
    vision_stats.last_error = vision_stats.sample = None
    description_stats.failed = description_stats.write_failed = 0
    description_stats.last_error = description_stats.last_write_error = None


def count_description_failures(caption_func: Any) -> Any:
    """包住 modal processor 的 modal_caption_func，失敗時計數後照常重拋。

    RAG-Anything 的圖／表／公式 processor 在 caption 呼叫失敗時 log 一行錯誤、寫入 fallback
    實體並讓匯入照常成功。表格與公式走 llm_model_func（不是 vision_model_func），所以只在
    vision 層計數會漏掉它們；在 processor 的 caption 函式這一層才涵蓋所有種類。

    Args:
        caption_func: processor 目前的 modal_caption_func。

    Returns:
        同樣簽章的 async 函式；例外照常往外拋（由 processor 自己吞掉），只多記一筆計數。
    """

    async def counted(*args: Any, **kwargs: Any) -> Any:
        try:
            return await caption_func(*args, **kwargs)
        except Exception as exc:
            description_stats.failed += 1
            description_stats.last_error = str(exc) if isinstance(exc, EndpointError) else _describe(exc)
            raise

    return counted


def record_write_failure(exc: Exception) -> None:
    """記一次多模態內容寫入索引的失敗（RAG-Anything 之後會吞掉這個例外）。

    Args:
        exc: 寫入過程拋出的例外。
    """
    description_stats.write_failed += 1
    description_stats.last_write_error = str(exc) if isinstance(exc, EndpointError) else _describe(exc)


def failure_counts() -> tuple[int, int]:
    """目前累計的描述失敗與寫入失敗次數，供呼叫端取前後差。

    Returns:
        (描述失敗次數, 寫入失敗次數)。
    """
    return description_stats.failed, description_stats.write_failed


def describe_failures(description_failed: int, write_failed: int) -> str:
    """把描述失敗與寫入失敗的次數和最近一次的錯誤寫成一句話。

    Args:
        description_failed: 描述失敗次數。
        write_failed: 寫入失敗次數。

    Returns:
        例如「圖／表／公式描述呼叫失敗 2 次（最近錯誤：…）；多模態內容寫入索引失敗 1 次（最近錯誤：…）」。
    """
    parts = []
    if description_failed:
        parts.append(f"圖／表／公式描述呼叫失敗 {description_failed} 次（最近錯誤：{description_stats.last_error}）")
    if write_failed:
        parts.append(f"多模態內容寫入索引失敗 {write_failed} 次（最近錯誤：{description_stats.last_write_error}）")
    return "；".join(parts)


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


# ==============================
# Rerank
# ==============================


class RerankFailure(BaseException):
    """rerank 沒有正常完成。刻意繼承 BaseException（不是 Exception）：LightRAG 的 apply_rerank_if_enabled 只攔 Exception
    並改用原本的排序，繼承 BaseException 才能穿過 LightRAG 的查詢流程，在它呼叫 LLM 產生答案、寫入 LLM 快取之前中止查詢。
    只有 pipeline 的查詢入口（_answer、VLM 增強路徑）會攔它並轉成 PipelineError；其他地方不該攔。

    Attributes:
        error: 失敗的細節（EndpointError，含端點位址與原因）。
    """

    def __init__(self, error: EndpointError):
        super().__init__(str(error))
        self.error = error


def _rerank_problem(results: list[dict[str, Any]], candidates: int, top_n: int | None) -> str | None:
    """檢查 rerank 回應的內容；LightRAG 對不合法的內容靜默略過或沿用原排序，所以這裡先擋下。

    合法的回應：筆數剛好是 min(top_n, 候選數)（top_n 為 None 時是候選數）、每筆的 index 是範圍內的 int（bool 不算）
    且不重複、relevance_score 是有限的數字（int 或 float，bool 不算）。results 不是 list、缺欄位的情況
    在 generic_rerank_api 內就以空結果或例外結束，不會到這裡。

    Args:
        results: generic_rerank_api 標準化後的結果。
        candidates: 送出的候選 chunk 數。
        top_n: 送出的 top_n；None 表示不限。

    Returns:
        第一個發現的問題描述；回應合法時為 None。
    """
    if not results:
        return f"回傳空結果（送出 {candidates} 個候選 chunk）"
    expected = candidates if top_n is None else min(top_n, candidates)
    if len(results) != expected:
        return f"回傳 {len(results)} 筆結果，應為 {expected} 筆（候選 {candidates} 個、top_n={top_n}）"
    seen: set[int] = set()
    for item in results:
        index, score = item["index"], item["relevance_score"]
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < candidates:
            return f"回傳的 index {index!r} 不是候選範圍 0..{candidates - 1} 內的整數"
        if index in seen:
            return f"回傳的 index {index} 重複"
        seen.add(index)
        if isinstance(score, bool) or not isinstance(score, int | float) or not math.isfinite(score):
            return f"index {index} 的 relevance_score {score!r} 不是有限的數字"
    return None


async def rerank_model_func(query: str, documents: list[str], top_n: int | None = None) -> list[dict[str, Any]]:
    """呼叫 rerank 端點，替 LightRAG 重新排序候選 chunk；沒有正常完成時拋出 RerankFailure。

    Args:
        query: 查詢文字。
        documents: 候選 chunk 的內容。
        top_n: 只保留分數最高的幾個（LightRAG 傳入 chunk_top_k）。

    Returns:
        [{"index": 候選的位置, "relevance_score": 分數}, ...]，依分數由高到低；LightRAG 依此順序重排候選。

    Raises:
        RerankFailure: 請求例外、HTTP 錯誤，或回應不合法（見 _rerank_problem）（包著 EndpointError）。它是
            BaseException，會穿過 LightRAG，由 pipeline 的查詢入口轉成 PipelineError，查詢在產生答案之前就中止。
    """
    s = get_settings()
    url = f"{s.rerank_base_url}/rerank"
    try:
        results = await generic_rerank_api(
            query=query,
            documents=documents,
            model=s.rerank_model,
            base_url=url,
            api_key=s.rerank_api_key,
            top_n=top_n,
        )
    except Exception as exc:
        raise RerankFailure(EndpointError("Rerank", url, _describe(exc))) from exc
    problem = _rerank_problem(results, len(documents), top_n)
    if problem:
        raise RerankFailure(EndpointError("Rerank", url, problem))
    return results
