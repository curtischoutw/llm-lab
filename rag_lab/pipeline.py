"""匯入（ingest）與問答（query）的流程：把設定接上 RAG-Anything／LightRAG。

為什麼存在：CLI 的 ingest／query 需要一層把「設定 → RAGAnything 實例 → 解析、建圖、
檢索」串起來的程式，並把 RAG-Anything／LightRAG 會吞掉的錯誤改成可偵測的失敗。
CLI 只負責參數與輸出格式，這裡負責行為。

關鍵設計決策：
- 重複匯入：先 parse_document 取得內容雜湊的文件 ID（走 parse cache，不重跑 MinerU），
  已完整處理就不再呼叫 process_document_complete。這避開 RAG-Anything 單檔路徑的兩個
  副作用（LightRAG 留下 status=failed 的 dup 紀錄、原文件卡在 handling 使
  get_status_counts() 拋 KeyError）。
- 重試未完成的文件（上次失敗、被中斷而卡在 processing，或文字完成但多模態沒做完）：先用
  LightRAG 的 adelete_by_doc_id 刪掉舊紀錄與部分結果，再重新匯入。LightRAG 遇到已存在的
  doc ID 不會重新排入，只會另寫一筆 status=failed 的 dup- 紀錄；刪除時保留 LLM 快取，
  上次已成功的 chunk 重跑時直接命中快取。
- 開始處理前先確認要用的端點連得上（models.check_reachable），不可達就指出名稱與位址並立即
  失敗，不要等到解析完才發現。圖／表／公式的描述失敗不會讓 RAG-Anything 報錯（processor 吞掉
  後寫入 fallback 實體），所以匯入時把每個 modal processor 的 caption 函式包上計數
  （models.count_description_failures），匯入後依 models.description_stats 判斷。有失敗時不拋例外
  （拋了就看不到逐篇報告與其他篇的錯誤），而是記在 IngestSummary.description_error（含端點與
  位址），由 CLI 印完報告後以非零碼結束。
- 查詢走 LightRAG 的 aquery_llm（回 status 與 message），不用 aquery：後者在 LLM 失敗
  時回 None、非法模式也回 None。status 不是 success 或沒有答案內容一律當失敗。
- 查詢預設 vlm_enhanced=False（只走 LLM、不讓 VLM 改寫答案；與 spec 一致，五種模式的答案才由
  同一個模型產生、可比較），並固定 enable_rerank=False（spec 不用 reranker，預設值會讓每次
  查詢都警告）。vlm_enhanced=True 時改走 RAGAnything.aquery_vlm_enhanced，並多檢查 VLM 端點。
- eval（evaluate）在同一個 RAGAnything 實例上，依題目順序、五種模式順序依序查詢，不是每格重新
  初始化。每格沿用 query 的 _answer（aquery_llm、QUERY_MAX_TOTAL_TOKENS、vlm_enhanced=False、
  enable_rerank=False）；單格失敗（含沒有答案內容）記在該格的 Cell.error，不中斷其餘格。
  開始前只檢查 LLM 與 Embedding 端點可達（eval 不走 VLM）。
- 多篇匯入時單篇失敗不中斷整批：失敗記在該篇的 IngestReport.error，其餘照常處理並保留，
  由 CLI 印出是哪一篇並以非零碼結束。重新執行時已完整處理的篇略過、失敗的篇重試。
- 查詢 context 的 token 上限由 QUERY_MAX_TOTAL_TOKENS 決定：LightRAG 預設 30000，在 32 GB
  的機器上 mlx_lm.server 處理 29.7k token 的 prompt 會 GPU 記憶體不足。LightRAG 的總上限不是
  硬上限：chunk 預算＝總上限 − KG context，而 KG context 另受 entity／relation 上限（預設
  6000／8000）限制。只降總上限時 chunk 預算可能變成負數、prompt 仍超過總上限，所以
  entity／relation 上限照 LightRAG 預設對總上限的比例一起縮放（ASSUMPTION：沿用預設比例）。
- embedding 並行數由 EMBED_MAX_ASYNC 經 lightrag_kwargs 明確傳入，不依賴 LightRAG 自己讀的
  EMBEDDING_FUNC_MAX_ASYNC 環境變數：那個預設值在 import lightrag 時就決定，晚於 import 才載入的
  .env 不會生效。
- 收尾（_close）除了 finalize_storages，還要呼叫 LightRAG 兩個限流器（LLM、embedding）的
  shutdown()：限流 worker 在執行呼叫時被取消會把 CancelledError 吞掉、回到等待迴圈，
  只有 shutdown 設定的旗標能讓它結束。不呼叫的話，端點在請求進行中失敗（例如 mlx_lm.server
  生成執行緒死掉，正在生成的請求永遠不回應）時，asyncio.run 收尾會永遠等不到它，CLI 卡住
  且不印錯誤。finalize_storages 不會呼叫 shutdown。
- 計時用 RAG-Anything 的 ProcessingCallback：解析＝第一次 parse_document（之後 process
  內的 parse 是快取命中）；建圖＝文字插入（含 LightRAG 實體抽取）；多模態＝圖表公式描述。
- mineru 以 subprocess 依 PATH 尋找：PATH 上找不到時，把目前 Python 所在的 bin 目錄
  （專案 venv）附加到 PATH 尾端，使用者不需先 activate。已在 PATH 上的 mineru 優先，
  所以測試能以假 mineru 取代。這一步放在初始化：RAG-Anything 初始化時會先跑
  `mineru --version` 檢查 parser，查詢不解析文件也一樣要通過。

已知極限：
- 使用 RAGAnything 的私有方法 _ensure_lightrag_initialized：官方沒有公開的等價 API，
  但不先初始化就查詢會直接拋 ValueError。
- VLM 增強查詢（aquery_vlm_enhanced）沒有 aquery_llm 的 status／message：LLM 失敗時只回 None，
  這裡只能報「沒有回傳答案內容」，看不到原例外文字（VLM 失敗則有端點與位址）。
- 描述失敗不會讓 RAG-Anything 匯入失敗（圖片描述退成原始 dict 文字、表格與公式退成原始內容）；
  這裡只能事後依 models.description_stats 計數判斷並回報，已寫入索引的退化描述不會自動修復，
  文件也已被標為完整處理（重跑會略過，要刪索引重來）。

Dependencies: raganything、lightrag-hku（由 raganything 帶入）。
"""

import asyncio
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from lightrag import QueryParam
from lightrag.base import DocStatus
from lightrag.constants import DEFAULT_MAX_ENTITY_TOKENS, DEFAULT_MAX_RELATION_TOKENS, DEFAULT_MAX_TOTAL_TOKENS
from raganything import RAGAnything, RAGAnythingConfig
from raganything.callbacks import ProcessingCallback

from rag_lab import models
from rag_lab.config import Settings, get_settings
from rag_lab.evaluation import RETRIEVAL_MODES, Cell, Question

# ==============================
# 常數與例外
# ==============================

# MinerU 解析後端。在 Mac（無 CUDA）上實測挑選，理由見 ticket 03 回報。
MINERU_BACKEND = "pipeline"

# 統計文件狀態時每頁讀幾筆（LightRAG 的上限是 200）
STATUS_PAGE_SIZE = 200


class PipelineError(RuntimeError):
    """匯入或查詢流程的可預期失敗；訊息直接給使用者看。"""


# ==============================
# 環境與實例
# ==============================


def ensure_mineru_on_path() -> None:
    """確保 PATH 上找得到 `mineru`。

    RAG-Anything 以 subprocess 依 PATH 呼叫 mineru。PATH 上已有就不動；沒有時把目前
    Python 所在的 bin 目錄（專案 venv）附加到 PATH 尾端，使用者不需要先 activate venv。
    """
    if shutil.which("mineru") is None:
        # 只有既有 PATH 非空才串接：PATH 沒設定時，開頭的空項目代表目前目錄，cwd 裡的 mineru 會比 venv 的先被執行
        entries = [entry for entry in (os.environ.get("PATH"), str(Path(sys.executable).parent)) if entry]
        os.environ["PATH"] = os.pathsep.join(entries)


def build_rag(settings: Settings) -> RAGAnything:
    """依設定建立 RAGAnything 實例（尚未初始化儲存）。

    Args:
        settings: 已驗證的設定。

    Returns:
        接好 LLM、VLM、embedding 三個模型函式的 RAGAnything。
    """
    config = RAGAnythingConfig(
        working_dir=settings.working_dir,
        parser_output_dir=settings.parser_output_dir,
        parser="mineru",
        parse_method="auto",
    )
    return RAGAnything(
        config=config,
        llm_model_func=models.llm_model_func,
        vision_model_func=models.vision_model_func,
        embedding_func=models.build_embedding_func(),
        lightrag_kwargs={
            "llm_model_max_async": settings.llm_max_async,
            # ASSUMPTION：圖片／表格／公式描述的並行度（max_parallel_insert）不受 llm_model_max_async
            # 限制，沿用同一個設定值，避免本地 server 被打爆。
            "max_parallel_insert": settings.llm_max_async,
            "embedding_func_max_async": settings.embed_max_async,
        },
    )


async def _close(rag: RAGAnything) -> None:
    """寫回儲存，並關掉 LightRAG 的 LLM 與 embedding 限流 worker。

    Args:
        rag: 要收尾的 RAGAnything（可能尚未完成初始化）。
    """
    try:
        await rag.finalize_storages()
    finally:
        if rag.lightrag is not None:
            await rag.lightrag.llm_model_func.shutdown()
            await rag.lightrag.embedding_func.func.shutdown()


async def _initialize(rag: RAGAnything) -> None:
    """初始化 LightRAG 與儲存。

    Args:
        rag: 尚未初始化的 RAGAnything。

    Raises:
        PipelineError: RAG-Anything 回報初始化失敗。
    """
    ensure_mineru_on_path()
    result = await rag._ensure_lightrag_initialized()
    if not result or not result.get("success"):
        raise PipelineError(f"RAG-Anything 初始化失敗：{(result or {}).get('error', '未知錯誤')}")


# ==============================
# 匯入
# ==============================


class StageTimer(ProcessingCallback):
    """收集單一文件各階段耗時的 callback。"""

    def __init__(self) -> None:
        self.parse_seconds: float | None = None
        self.text_insert_seconds = 0.0
        self.multimodal_seconds = 0.0
        self.multimodal_items = 0

    def on_parse_complete(self, file_path: str, duration_seconds: float = 0.0, **kwargs) -> None:
        """只記第一次：之後 process_document_complete 內的 parse 是快取命中。"""
        if self.parse_seconds is None:
            self.parse_seconds = duration_seconds

    def on_text_insert_complete(self, file_path: str, duration_seconds: float = 0.0, **kwargs) -> None:
        self.text_insert_seconds += duration_seconds

    def on_multimodal_complete(
        self, file_path: str, processed_count: int = 0, duration_seconds: float = 0.0, **kwargs
    ) -> None:
        self.multimodal_items += processed_count
        self.multimodal_seconds += duration_seconds


@dataclass
class IngestReport:
    """單篇 PDF 匯入結果。

    Attributes:
        pdf: PDF 路徑。
        skipped: True 表示已完整處理過，沒有重新匯入。
        parse_seconds: MinerU 解析耗時（skipped 時為快取查詢時間）。
        graph_seconds: 文字建圖耗時（含 LLM 實體抽取）。
        multimodal_seconds: 圖／表／公式描述耗時。
        multimodal_items: 處理的圖／表／公式數。
        total_seconds: 這一篇從開始到結束的總耗時。
        error: 失敗時的「型別：訊息」；None 表示成功。
        description_failed: 這一篇的圖／表／公式描述失敗次數。
    """

    pdf: Path
    skipped: bool
    parse_seconds: float
    graph_seconds: float = 0.0
    multimodal_seconds: float = 0.0
    multimodal_items: int = 0
    total_seconds: float = 0.0
    error: str | None = None
    description_failed: int = 0


@dataclass
class IngestSummary:
    """一次 ingest 的整體結果。

    Attributes:
        reports: 每篇 PDF 的報告。
        entities: 圖譜實體（節點）數。
        relations: 圖譜關係（邊）數，含 belongs_to。
        belongs_to: 其中 RAG-Anything 加的 belongs_to 邊數。
        status_counts: 文件狀態統計。
        vlm_ok: VLM 成功呼叫次數。
        vlm_failed: VLM 失敗呼叫次數。
        vlm_sample: 第一則 VLM 圖片描述（供人工判斷與原圖是否相符）。
        description_error: 有圖／表／公式描述失敗時的完整說明（含端點與位址）；None 表示沒有。
    """

    reports: list[IngestReport] = field(default_factory=list)
    entities: int = 0
    relations: int = 0
    belongs_to: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    vlm_ok: int = 0
    vlm_failed: int = 0
    vlm_sample: str | None = None
    description_error: str | None = None


async def _ingest_one(rag: RAGAnything, pdf: Path) -> IngestReport:
    """匯入單篇 PDF；已完整處理就略過，先前未完成的先清掉舊紀錄再重匯。

    Args:
        rag: 已初始化的 RAGAnything。
        pdf: PDF 路徑。

    Returns:
        這一篇的 IngestReport（total_seconds 與 description_failed 由呼叫端填入）。

    Raises:
        PipelineError: 解析不出內容，或清除舊紀錄失敗。
        Exception: MinerU、LLM 等匯入過程的失敗（由 _ingest 轉成該篇的 report.error）。
    """
    timer = StageTimer()
    rag.callback_manager.register(timer)
    try:
        parse_kwargs = {"backend": MINERU_BACKEND}
        content_list, doc_id = await rag.parse_document(str(pdf), **parse_kwargs)
        if not content_list:
            raise PipelineError(f"MinerU 沒有從 {pdf.name} 解析出任何內容（輸出資料夾：{rag.config.parser_output_dir}）")
        if await rag.is_document_fully_processed(doc_id):
            return IngestReport(pdf, skipped=True, parse_seconds=timer.parse_seconds or 0.0)
        if await rag.lightrag.doc_status.get_by_id(doc_id) is not None:
            deletion = await rag.lightrag.adelete_by_doc_id(doc_id)
            if deletion.status != "success":
                raise PipelineError(
                    f"{pdf.name} 先前的匯入沒有完成，清除舊紀錄 {doc_id} 失敗（{deletion.status}）：{deletion.message}"
                )
        await rag.process_document_complete(str(pdf), **parse_kwargs)
    finally:
        rag.callback_manager.unregister(timer)
    return IngestReport(
        pdf,
        skipped=False,
        parse_seconds=timer.parse_seconds or 0.0,
        graph_seconds=timer.text_insert_seconds,
        multimodal_seconds=timer.multimodal_seconds,
        multimodal_items=timer.multimodal_items,
    )


async def _graph_stats(rag: RAGAnything) -> tuple[int, int, int]:
    """讀取圖譜的實體數、關係數與其中的 belongs_to 邊數。

    Args:
        rag: 已初始化的 RAGAnything。

    Returns:
        (實體數, 關係數（含 belongs_to）, 其中的 belongs_to 邊數)。
    """
    graph = rag.lightrag.chunk_entity_relation_graph
    nodes = await graph.get_all_nodes()
    edges = await graph.get_all_edges()
    belongs_to = sum(1 for edge in edges if "belongs_to" in str(edge.get("keywords", "")))
    return len(nodes), len(edges), belongs_to


async def _status_counts(rag: RAGAnything) -> dict[str, int]:
    """統計文件狀態，包含 RAG-Anything 自己加的狀態（例如 handling）。

    不用 doc_status.get_status_counts()：LightRAG 的 JsonDocStatusStorage 只認自己的
    DocStatus，store 裡有 RAG-Anything 的 handling 紀錄（前一次匯入在多模態階段被中斷）
    就會拋 KeyError。get_docs_paginated 不過濾狀態，回傳原始狀態字串。

    Args:
        rag: 已初始化的 RAGAnything。

    Returns:
        {狀態名稱: 文件數}：LightRAG 的各狀態一律列出（沒有就是 0），其他狀態（例如 handling）只在實際出現時列出。
    """
    counts = {status.value: 0 for status in DocStatus}
    page = 1
    while True:
        docs, total = await rag.lightrag.doc_status.get_docs_paginated(
            page=page, page_size=STATUS_PAGE_SIZE, sort_field="id"
        )
        for _, doc in docs:
            status = str(getattr(doc.status, "value", doc.status))
            counts[status] = counts.get(status, 0) + 1
        if page * STATUS_PAGE_SIZE >= total:
            return counts
        page += 1


def _count_description_failures(rag: RAGAnything) -> None:
    """把每個 modal processor 的 caption 函式包上失敗計數（見 models.count_description_failures）。

    Args:
        rag: 已初始化的 RAGAnything（modal_processors 已建立）。
    """
    for processor in rag.modal_processors.values():
        processor.modal_caption_func = models.count_description_failures(processor.modal_caption_func)


async def _ingest(pdfs: list[Path], settings: Settings) -> IngestSummary:
    """匯入一批 PDF 並彙整結果。

    Args:
        pdfs: 要匯入的 PDF 路徑。
        settings: 已驗證的設定。

    Returns:
        IngestSummary；單篇失敗與描述失敗都記在裡面，不拋例外。

    Raises:
        EndpointError: 開始前有端點不可達。
        PipelineError: 初始化失敗。
    """
    models.check_reachable("LLM", "VLM", "Embedding")
    rag = build_rag(settings)
    summary = IngestSummary()
    try:
        await _initialize(rag)
        _count_description_failures(rag)
        for pdf in pdfs:
            failed_before = models.description_stats.failed
            started = time.perf_counter()
            try:
                report = await _ingest_one(rag, pdf)
            except Exception as exc:
                # 單篇失敗不中斷整批：記下是哪一篇、為什麼，CLI 據此印出並以非零碼結束
                report = IngestReport(pdf, skipped=False, parse_seconds=0.0, error=f"{type(exc).__name__}: {exc}")
            report.total_seconds = time.perf_counter() - started
            report.description_failed = models.description_stats.failed - failed_before
            summary.reports.append(report)
        summary.entities, summary.relations, summary.belongs_to = await _graph_stats(rag)
        summary.status_counts = await _status_counts(rag)
    finally:
        await _close(rag)
    stats = models.vision_stats
    summary.vlm_ok, summary.vlm_failed, summary.vlm_sample = stats.ok, stats.failed, stats.sample
    described = models.description_stats
    if described.failed:
        summary.description_error = (
            f"匯入完成，但有 {described.failed} 次圖／表／公式描述呼叫失敗；RAG-Anything 不會因此報錯，"
            f"受影響項目的描述已退化成原始內容並寫入索引，文件仍標為完整處理（重新執行會略過）。"
            f"最近錯誤：{described.last_error}。"
            f"請修好端點後刪除 {settings.working_dir} 與 {settings.parser_output_dir} 再重新匯入。"
        )
    return summary


def ingest(pdfs: list[Path]) -> IngestSummary:
    """匯入一批 PDF。

    Args:
        pdfs: 要匯入的 PDF 路徑。

    Returns:
        IngestSummary；單篇失敗與描述失敗記在裡面（reports[].error、description_error），由呼叫端決定結束碼。

    Raises:
        PipelineError: 初始化失敗等整批層級的可預期失敗。
        EndpointError: 開始前有端點不可達。
    """
    return asyncio.run(_ingest(pdfs, get_settings()))


# ==============================
# 查詢
# ==============================


def query_kwargs(max_total_tokens: int) -> dict[str, object]:
    """組出 QueryParam 的共用參數，entity／relation 的 token 上限依 LightRAG 預設比例隨總上限縮放。

    Args:
        max_total_tokens: 查詢 context 的總 token 上限（QUERY_MAX_TOTAL_TOKENS）。

    Returns:
        可展開給 QueryParam（或 RAGAnything.aquery_vlm_enhanced）的參數 dict，不含 mode。
    """
    return {
        "enable_rerank": False,
        "max_total_tokens": max_total_tokens,
        "max_entity_tokens": max_total_tokens * DEFAULT_MAX_ENTITY_TOKENS // DEFAULT_MAX_TOTAL_TOKENS,
        "max_relation_tokens": max_total_tokens * DEFAULT_MAX_RELATION_TOKENS // DEFAULT_MAX_TOTAL_TOKENS,
    }


def query_param(mode: str, max_total_tokens: int) -> QueryParam:
    """組出查詢參數（見 query_kwargs）。

    Args:
        mode: 檢索模式。
        max_total_tokens: 查詢 context 的總 token 上限（QUERY_MAX_TOTAL_TOKENS）。

    Returns:
        QueryParam。
    """
    return QueryParam(mode=mode, **query_kwargs(max_total_tokens))


async def _answer(rag: RAGAnything, question: str, mode: str, settings: Settings) -> str:
    """在已初始化的 RAGAnything 上以 aquery_llm 查詢（不啟用 VLM 增強）。

    Args:
        rag: 已完成 _initialize 的實例。
        question: 問題文字。
        mode: 檢索模式。
        settings: 已驗證的設定（取 QUERY_MAX_TOTAL_TOKENS）。

    Returns:
        答案文字（非空字串）。

    Raises:
        PipelineError: LightRAG 回報查詢失敗（訊息含原例外文字），或成功但沒有答案內容。
    """
    result = await rag.lightrag.aquery_llm(question, query_param(mode, settings.query_max_total_tokens))
    if result.get("status") != "success":
        raise PipelineError(f"查詢失敗（mode={mode}）：{result.get('message')}")
    answer = (result.get("llm_response") or {}).get("content")
    if not answer or not isinstance(answer, str):
        raise PipelineError(f"查詢沒有回傳答案內容（mode={mode}）")
    return answer


async def _query(question: str, mode: str, vlm_enhanced: bool, settings: Settings) -> str:
    """初始化後以指定模式查詢一次，收尾後回傳答案。

    Args:
        question: 問題文字。
        mode: 檢索模式。
        vlm_enhanced: True 時走 RAG-Anything 的 VLM 增強查詢，並多檢查 VLM 端點。
        settings: 已驗證的設定。

    Returns:
        答案文字（非空字串）。

    Raises:
        EndpointError: 端點不可達或呼叫失敗。
        PipelineError: 初始化失敗、查詢失敗，或沒有答案內容。
    """
    models.check_reachable("LLM", "Embedding", *(["VLM"] if vlm_enhanced else []))
    rag = build_rag(settings)
    try:
        await _initialize(rag)
        if vlm_enhanced:
            # RAG-Anything 的 VLM 增強路徑：先取回檢索 prompt、把圖片路徑換成 base64 圖片再交給 VLM。
            # 它沒有 aquery_llm 的 status 欄位；失敗時回 None（LLM 失敗的訊息 LightRAG 已吞掉），
            # VLM 失敗則拋 EndpointError（含端點與位址）。
            answer = await rag.aquery_vlm_enhanced(
                question, mode=mode, **query_kwargs(settings.query_max_total_tokens)
            )
            if not answer or not isinstance(answer, str):
                raise PipelineError(f"查詢沒有回傳答案內容（mode={mode}，vlm_enhanced=True）")
        else:
            answer = await _answer(rag, question, mode, settings)
    finally:
        await _close(rag)
    return answer


def query(question: str, mode: str, vlm_enhanced: bool = False) -> str:
    """以指定檢索模式回答問題。

    Args:
        question: 問題文字。
        mode: naive、local、global、hybrid、mix 之一（由 CLI 驗證）。
        vlm_enhanced: True 時檢索到的圖片會交給 VLM 產生答案，並要求 VLM 端點可連。

    Returns:
        答案文字。

    Raises:
        PipelineError: 查詢失敗，或沒有答案內容。
        EndpointError: 端點不可達或呼叫失敗。
    """
    return asyncio.run(_query(question, mode, vlm_enhanced, get_settings()))


# ==============================
# 批次比較（eval）
# ==============================


async def _evaluate(questions: list[Question], settings: Settings) -> list[list[Cell]]:
    """在同一個 RAGAnything 實例上依題目、模式順序逐格查詢；單格失敗記在該格。

    Args:
        questions: 已驗證的題目。
        settings: 已驗證的設定。

    Returns:
        cells[i][j] 是第 i 題在 RETRIEVAL_MODES[j] 的結果。

    Raises:
        EndpointError: LLM 或 embedding 端點在開始前就不可達。
        PipelineError: 初始化失敗。
    """
    models.check_reachable("LLM", "Embedding")
    rag = build_rag(settings)
    cells: list[list[Cell]] = []
    try:
        await _initialize(rag)
        for question in questions:
            row: list[Cell] = []
            for mode in RETRIEVAL_MODES:
                try:
                    row.append(Cell(answer=await _answer(rag, question.question, mode, settings)))
                except Exception as exc:
                    # 單格失敗不中斷整批：把原因記在這一格，CLI 據此標示並以非零碼結束
                    row.append(Cell(error=f"{type(exc).__name__}: {exc}"))
            cells.append(row)
    finally:
        await _close(rag)
    return cells


def evaluate(questions: list[Question]) -> list[list[Cell]]:
    """對每一題以五種檢索模式各查詢一次。

    五個模式與所有題目共用同一個 RAGAnything 實例，依題目順序、模式順序依序執行。
    查詢固定 vlm_enhanced=False、enable_rerank=False，並沿用 query 的 QUERY_MAX_TOTAL_TOKENS。

    Args:
        questions: 已驗證的題目。

    Returns:
        cells[i][j] 是第 i 題在 RETRIEVAL_MODES[j] 的結果；單格失敗記在該格的 error。

    Raises:
        EndpointError: LLM 或 embedding 端點在開始前就不可達。
        PipelineError: 初始化失敗。
    """
    return asyncio.run(_evaluate(questions, get_settings()))
