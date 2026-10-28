"""匯入（ingest）、問答（query）、批次比較（evaluate）的流程與 Session：把設定接上 RAG-Anything／LightRAG。

為什麼存在：CLI 與使用者的 Python 程式都需要一層把「設定 → RAGAnything 實例 → 解析、建圖、
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
- eval（evaluate）在同一個 Session（同一個 RAGAnything 實例）上，依題目順序、五種模式順序依序查詢，
  不是每格重新初始化。每格沿用 query 的 _answer（aquery_llm、QUERY_MAX_TOTAL_TOKENS、vlm_enhanced=False、
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
  生成執行緒死掉，正在生成的請求永遠不回應）時，關閉 event loop 的收尾會永遠等不到它，CLI 卡住
  且不印錯誤。finalize_storages 不會呼叫 shutdown。
- Session：同一個 process 依序做多次 ingest／query／evaluate 時只初始化一次知識庫。所有呼叫在同一個
  asyncio.Runner 的 event loop 上執行：LightRAG 的共用鎖（shared_storage，process 層級的全域物件）
  在初始化時綁定當時的 loop，換 loop 就會「Lock is bound to a different event loop」。關閉時才收尾，
  收尾最後呼叫 finalize_share_data() 重置共用狀態，下一個 Session 初始化時會重建並綁到它自己的 loop。
  共用狀態是 process 層級，所以同一時間只允許一個開啟中的 Session（模組層級的鎖），也只能在建立它的
  執行緒、沒有執行中 event loop 的地方使用；誤用拋 SessionError（不繼承 PipelineError：誤用是程式錯誤）。
- 模組函式 ingest／query／evaluate 是「開 Session、呼叫一次、關閉」，CLI 經由它們使用 Session。
  開 Session 之前先檢查端點：端點不可達時不建立 WORKING_DIR、不跑 mineru。
- RAG-Anything 在建構時註冊 atexit(self.close)：實例會被留到 process 結束，結束時又用新的 event loop
  碰綁在舊 loop 上的鎖（錯誤被吞掉）。Session 建立實例後立即取消這個註冊，改註冊自己的收尾：忘了 close
  時在同一個 loop 上完整收尾並在 stderr 警告；正常 close 後取消，實例才能被回收。
- 每次 ingest 開始時把 models 的 VLM 與描述統計清零，報告只計這一次；描述失敗計數的包裝在 Session
  初始化後只包一次（每次 ingest 都包會疊成多層，同一次失敗被計多次）。
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
- Session 讀的是開啟當下的索引：開著的期間另一個 process 匯入的內容，這個 Session 看不到。
- Session 是同步介面，不能直接在 Jupyter 或 async 函式裡使用（例外訊息附 asyncio.to_thread 的替代寫法）。
- 呼叫途中被中斷（KeyboardInterrupt）後不保證 Session 狀態一致；中斷後應關閉 Session 再開新的。

Dependencies: raganything、lightrag-hku（由 raganything 帶入）。
"""

import asyncio
import atexit
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from lightrag import QueryParam
from lightrag.base import DocStatus
from lightrag.constants import DEFAULT_MAX_ENTITY_TOKENS, DEFAULT_MAX_RELATION_TOKENS, DEFAULT_MAX_TOTAL_TOKENS
from lightrag.kg.shared_storage import finalize_share_data
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
    """寫回儲存，關掉 LightRAG 的 LLM 與 embedding 限流 worker，並重置 process 層級的共用鎖。

    Args:
        rag: 要收尾的 RAGAnything（可能尚未完成初始化）。
    """
    try:
        await rag.finalize_storages()
    finally:
        try:
            if rag.lightrag is not None:
                await rag.lightrag.llm_model_func.shutdown()
                await rag.lightrag.embedding_func.func.shutdown()
        finally:
            finalize_share_data()


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


async def _ingest(rag: RAGAnything, pdfs: list[Path], settings: Settings) -> IngestSummary:
    """在已初始化的 RAGAnything 上匯入一批 PDF 並彙整結果。

    Args:
        rag: 已完成 _initialize 的實例。
        pdfs: 要匯入的 PDF 路徑。
        settings: 已驗證的設定。

    Returns:
        IngestSummary；單篇失敗與描述失敗都記在裡面，不拋例外。

    Raises:
        EndpointError: 開始前有端點不可達。
    """
    models.check_reachable("LLM", "VLM", "Embedding")
    models.reset_stats()
    summary = IngestSummary()
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
    """匯入一批 PDF：開一個 Session、匯入一次、關閉。

    Args:
        pdfs: 要匯入的 PDF 路徑。

    Returns:
        IngestSummary；單篇失敗與描述失敗記在裡面（reports[].error、description_error），由呼叫端決定結束碼。

    Raises:
        PipelineError: 初始化失敗等整批層級的可預期失敗。
        EndpointError: 開始前有端點不可達。
        SessionError: 已有開啟中的 Session，或在不允許的環境呼叫（見 Session）。
    """
    # Session 建構時只檢查 LLM 與 embedding；VLM 在開 Session 之前先檢查，不可達時不建立 WORKING_DIR、不跑 mineru
    models.check_reachable("VLM")
    with Session() as session:
        return session.ingest(pdfs)


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


async def _query(rag: RAGAnything, question: str, mode: str, vlm_enhanced: bool, settings: Settings) -> str:
    """在已初始化的 RAGAnything 上以指定模式查詢一次。

    Args:
        rag: 已完成 _initialize 的實例。
        question: 問題文字。
        mode: 檢索模式。
        vlm_enhanced: True 時走 RAG-Anything 的 VLM 增強查詢，並多檢查 VLM 端點。
        settings: 已驗證的設定。

    Returns:
        答案文字（非空字串）。

    Raises:
        EndpointError: 開始前端點不可達，或 VLM 呼叫失敗。
        PipelineError: 查詢失敗（含查詢途中 LLM 失敗），或沒有答案內容。
    """
    models.check_reachable("LLM", "Embedding", *(["VLM"] if vlm_enhanced else []))
    if not vlm_enhanced:
        return await _answer(rag, question, mode, settings)
    # RAG-Anything 的 VLM 增強路徑：先取回檢索 prompt、把圖片路徑換成 base64 圖片再交給 VLM。
    # 它沒有 aquery_llm 的 status 欄位；失敗時回 None（LLM 失敗的訊息 LightRAG 已吞掉），
    # VLM 失敗則拋 EndpointError（含端點與位址）。
    answer = await rag.aquery_vlm_enhanced(question, mode=mode, **query_kwargs(settings.query_max_total_tokens))
    if not answer or not isinstance(answer, str):
        raise PipelineError(f"查詢沒有回傳答案內容（mode={mode}，vlm_enhanced=True）")
    return answer


def query(question: str, mode: str, vlm_enhanced: bool = False) -> str:
    """以指定檢索模式回答問題：開一個 Session、查詢一次、關閉。

    Args:
        question: 問題文字。
        mode: naive、local、global、hybrid、mix 之一。
        vlm_enhanced: True 時檢索到的圖片會交給 VLM 產生答案，並要求 VLM 端點可連。

    Returns:
        答案文字。

    Raises:
        ValueError: mode 不是五種檢索模式之一。
        PipelineError: 初始化失敗、查詢失敗，或沒有答案內容。
        EndpointError: 開始前端點不可達，或 VLM 呼叫失敗。
        SessionError: 已有開啟中的 Session，或在不允許的環境呼叫（見 Session）。
    """
    if vlm_enhanced:
        # Session 建構時只檢查 LLM 與 embedding；VLM 在開 Session 之前先檢查
        models.check_reachable("VLM")
    with Session() as session:
        return session.query(question, mode, vlm_enhanced)


# ==============================
# 批次比較（eval）
# ==============================


async def _evaluate(rag: RAGAnything, questions: list[Question], settings: Settings) -> list[list[Cell]]:
    """在已初始化的 RAGAnything 上依題目、模式順序逐格查詢；單格失敗記在該格。

    Args:
        rag: 已完成 _initialize 的實例。
        questions: 已驗證的題目。
        settings: 已驗證的設定。

    Returns:
        cells[i][j] 是第 i 題在 RETRIEVAL_MODES[j] 的結果。

    Raises:
        EndpointError: LLM 或 embedding 端點在開始前就不可達。
    """
    models.check_reachable("LLM", "Embedding")
    cells: list[list[Cell]] = []
    for question in questions:
        row: list[Cell] = []
        for mode in RETRIEVAL_MODES:
            try:
                row.append(Cell(answer=await _answer(rag, question.question, mode, settings)))
            except Exception as exc:
                # 單格失敗不中斷整批：把原因記在這一格，CLI 據此標示並以非零碼結束
                row.append(Cell(error=f"{type(exc).__name__}: {exc}"))
        cells.append(row)
    return cells


def evaluate(questions: list[Question]) -> list[list[Cell]]:
    """對每一題以五種檢索模式各查詢一次：開一個 Session、跑完全部題目、關閉。

    五個模式與所有題目共用同一個 RAGAnything 實例，依題目順序、模式順序依序執行。
    查詢固定 vlm_enhanced=False、enable_rerank=False，並沿用 query 的 QUERY_MAX_TOTAL_TOKENS。

    Args:
        questions: 已驗證的題目。

    Returns:
        cells[i][j] 是第 i 題在 RETRIEVAL_MODES[j] 的結果；單格失敗記在該格的 error。

    Raises:
        EndpointError: LLM 或 embedding 端點在開始前就不可達。
        PipelineError: 初始化失敗。
        SessionError: 已有開啟中的 Session，或在不允許的環境呼叫（見 Session）。
    """
    with Session() as session:
        return session.evaluate(questions)


# ==============================
# Session
# ==============================


class SessionError(RuntimeError):
    """Session 的誤用（程式錯誤）：同時開第二個、在其他執行緒或已有 running loop 的環境使用。

    刻意不繼承 PipelineError：誤用要修程式，不該被處理匯入／查詢失敗的 `except PipelineError` 接走。
    """


class SessionClosedError(SessionError):
    """在已關閉的 Session 上呼叫。"""


# 同一個 process 同一時間只允許一個開啟中的 Session：LightRAG 的共用狀態是 process 層級的全域物件
_session_lock = threading.Lock()

RUNNING_LOOP_HINT = (
    "Session 是同步介面，不能在已有執行中 event loop 的執行緒使用（例如 Jupyter 或 async 函式）。"
    "替代寫法：把開 Session 與所有呼叫寫成一個同步函式，再以 `await asyncio.to_thread(該函式)` 執行。"
)


def _reject_running_loop() -> None:
    """目前執行緒已有執行中的 event loop 時拋 SessionError。

    Raises:
        SessionError: 目前執行緒已有執行中的 event loop。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise SessionError(RUNNING_LOOP_HINT)


class Session:
    """只初始化一次知識庫、依序執行多次 ingest／query／evaluate 的同步 session。

    用法：`with Session() as session: session.query(...)`。所有呼叫在同一個 asyncio.Runner 的 event loop
    上執行，LightRAG 的共用鎖與 RAGAnything 的實例鎖都綁在這個 loop；關閉時才寫回儲存、關限流 worker、
    重置 LightRAG 的共用狀態。

    規則：
        - 同一個 process 同一時間只能有一個開啟中的 Session。
        - 只能在建立它的執行緒使用；建立它的執行緒已結束時，其他執行緒可以 close()。
        - 不能在已有執行中 event loop 的執行緒建立或呼叫。
        - 讀到的是開啟當下的索引：開著的期間另一個 process 匯入的內容，這個 Session 看不到。
        - 忘了 close 時，process 結束前會在同一個 event loop 上收尾，並在 stderr 印警告。

    Raises（建構時）:
        SessionError: 已有開啟中的 Session，或目前執行緒已有執行中的 event loop。
        ConfigError: 設定缺漏或格式錯誤。
        EndpointError: LLM 或 embedding 端點不可達。
        OSError: 無法建立 WORKING_DIR。
        PipelineError: RAG-Anything 初始化失敗。
        建構失敗時的收尾若也失敗，收尾的錯誤附在原例外的 note，原例外照常拋出。
    """

    def __init__(self) -> None:
        _reject_running_loop()
        if not _session_lock.acquire(blocking=False):
            raise SessionError("已經有一個開啟中的 Session；同一個 process 同一時間只能開一個，請先 close() 它")
        self._owner = threading.current_thread()
        self._closed = False
        self._runner = asyncio.Runner()
        self._rag: RAGAnything | None = None
        try:
            self._settings = get_settings()
            models.check_reachable("LLM", "Embedding")
            # RAG-Anything 建構時先註冊 atexit 才建立 WORKING_DIR；建立失敗時拿不到實例、無法取消註冊，
            # 所以先自己建立，讓這種失敗發生在建構 RAGAnything 之前
            Path(self._settings.working_dir).mkdir(parents=True, exist_ok=True)
            self._rag = build_rag(self._settings)
            # RAG-Anything 在建構時註冊 atexit(self.close)：它會把實例留到 process 結束，結束時又用新的
            # event loop 碰綁在這個 loop 上的鎖（錯誤被吞掉）。改由 Session 自己收尾。
            atexit.unregister(self._rag.close)
            self._runner.run(_initialize(self._rag))
            # 每個實例只包一次：每次 ingest 都包會疊成多層，同一次失敗被計多次
            _count_description_failures(self._rag)
        except BaseException as exc:
            try:
                self._release()
            except Exception as cleanup:
                # 收尾失敗不能蓋掉原本的錯誤（呼叫端依例外類別處理）；收尾的錯誤附在 note 讓使用者看得到
                exc.add_note(f"開 Session 失敗後的收尾也失敗：{type(cleanup).__name__}: {cleanup}")
            raise
        atexit.register(self._close_at_exit)

    def __enter__(self) -> "Session":
        """進入 with 區塊。

        Returns:
            這個 Session。
        """
        return self

    def __exit__(self, *exc_info: object) -> None:
        """離開 with 區塊時關閉；不吞 with 區塊內的例外。

        Args:
            *exc_info: with 區塊內的例外型別、例外與 traceback（沒有例外時皆為 None）。
        """
        self.close()

    @property
    def closed(self) -> bool:
        """Session 是否已關閉。

        Returns:
            已關閉為 True。
        """
        return self._closed

    def ingest(self, pdfs: list[Path]) -> IngestSummary:
        """匯入一批 PDF（見模組函式 ingest）。

        Args:
            pdfs: 要匯入的 PDF 路徑。

        Returns:
            這一次匯入的 IngestSummary；VLM 與描述統計只計這一次。

        Raises:
            SessionError: Session 已關閉，或從不允許的執行緒／環境呼叫。
            EndpointError: 開始前有端點不可達。
        """
        self._check_usable()
        return self._runner.run(_ingest(self._rag, pdfs, self._settings))

    def query(self, question: str, mode: str, vlm_enhanced: bool = False) -> str:
        """以指定檢索模式回答問題（見模組函式 query）。

        Args:
            question: 問題文字。
            mode: naive、local、global、hybrid、mix 之一。
            vlm_enhanced: True 時檢索到的圖片會交給 VLM 產生答案。

        Returns:
            答案文字。

        Raises:
            ValueError: mode 不是五種檢索模式之一。
            SessionError: Session 已關閉，或從不允許的執行緒／環境呼叫。
            EndpointError: 開始前端點不可達，或 VLM 呼叫失敗。
            PipelineError: 查詢失敗，或沒有答案內容。
        """
        self._check_usable()
        # LightRAG 還接受 bypass（不檢索、直接問 LLM），回來的答案看起來像 RAG 的結果；只允許五種檢索模式
        if mode not in RETRIEVAL_MODES:
            raise ValueError(f"mode 必須是 {'、'.join(RETRIEVAL_MODES)} 之一，收到 {mode!r}")
        return self._runner.run(_query(self._rag, question, mode, vlm_enhanced, self._settings))

    def evaluate(self, questions: list[Question]) -> list[list[Cell]]:
        """對每一題以五種檢索模式各查詢一次（見模組函式 evaluate）。

        Args:
            questions: 已驗證的題目。

        Returns:
            cells[i][j] 是第 i 題在 RETRIEVAL_MODES[j] 的結果；單格失敗記在該格的 error。

        Raises:
            SessionError: Session 已關閉，或從不允許的執行緒／環境呼叫。
            EndpointError: LLM 或 embedding 端點在開始前就不可達。
        """
        self._check_usable()
        return self._runner.run(_evaluate(self._rag, questions, self._settings))

    def close(self) -> None:
        """寫回儲存、關閉限流 worker、重置 LightRAG 共用狀態並釋放 event loop；重複呼叫不做事。

        Raises:
            SessionError: 建立它的執行緒還在執行，卻從其他執行緒呼叫。
        """
        if self._closed:
            return
        if threading.current_thread() is not self._owner and self._owner.is_alive():
            raise SessionError("Session 只能在建立它的執行緒使用（建立它的執行緒結束後，其他執行緒才能 close）")
        atexit.unregister(self._close_at_exit)
        self._release()

    def _check_usable(self) -> None:
        """確認可以在目前的執行緒呼叫。

        Raises:
            SessionClosedError: 已關閉。
            SessionError: 不是建立它的執行緒，或目前執行緒已有執行中的 event loop。
        """
        if self._closed:
            raise SessionClosedError("Session 已關閉，請開一個新的 Session")
        if threading.current_thread() is not self._owner:
            raise SessionError("Session 只能在建立它的執行緒使用")
        _reject_running_loop()

    def _close_at_exit(self) -> None:
        """process 結束時收尾忘了關閉的 Session，並在 stderr 警告。"""
        if self._closed:
            return
        print("警告：Session 沒有呼叫 close()，在 process 結束時自動收尾。", file=sys.stderr)
        self._release()

    def _release(self) -> None:
        """在同一個 event loop 上收尾 RAGAnything，再關閉 event loop、釋放 process 層級的鎖。"""
        try:
            if self._rag is not None:
                self._runner.run(_close(self._rag))
        finally:
            self._rag = None
            self._closed = True
            try:
                self._runner.close()
            finally:
                # 關 event loop 時被中斷（Ctrl-C）也要釋放：否則這個 process 再也開不了 Session
                _session_lock.release()
