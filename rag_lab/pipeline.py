"""匯入（ingest）、問答（query）、批次比較（evaluate）的流程與 Session：把設定接上 RAG-Anything／LightRAG。

為什麼存在：CLI 與使用者的 Python 程式都需要一層把「設定 → RAGAnything 實例 → 解析、建圖、
檢索」串起來的程式，並把 RAG-Anything／LightRAG 會吞掉的錯誤改成可偵測的失敗。
CLI 只負責參數與輸出格式，這裡負責行為。

關鍵設計決策：
- 重複匯入：先 parse_document 取得內容雜湊的文件 ID（走 parse cache，不重跑 MinerU），
  已完整處理就不再呼叫 process_document_complete。這避開 RAG-Anything 單檔路徑的兩個
  副作用（LightRAG 留下 status=failed 的 dup 紀錄、原文件卡在 handling 使
  get_status_counts() 拋 KeyError）。
- 對照表（rag_lab.registry，`WORKING_DIR/rag_lab_documents.json`）：每份文件處理成功後記下它的實體路徑、文件 ID、
  匯入時間與來源資料夾，並在報告分類（IngestReport.outcome、IngestSummary.added／replaced／unchanged）。分類依解析出的
  文件 ID 與對照表決定：沒完整匯入過的一律照一般匯入、成功記「新增」；已完整匯入的，對照表記著同一個 ID 或對照表沒有這個路徑
  也沒有別的路徑用這個 ID 時記「沒變」，新路徑與別的路徑共用同一個版本時記「新增」（知識庫不寫入），這個路徑記著另一個 ID 時
  是上次替換中斷（見 _classify_fully_processed）。對照表在處理任何文件之前載入，壞掉就拋 PipelineError（不當成空表）；
  每份成功的文件處理完立刻寫回，寫入失敗時不再處理後面的文件，前面文件的收尾（_mark_swallowed_failures）做完才拋
  PipelineError。失敗的文件不分類、不寫入。
- 替換（_ingest_one，spec「匯入端：替換與移除」）：對照表記的 ID 不等於這次的 ID 時，先匯入新版本、成功後刪舊版本
  （_remove_superseded_version → _remove_version，保留 LLM 抽取快取）、再更新對照表，記「替換」。新版本已完整匯入而對照表
  仍指向舊 ID（上次中斷）直接補刪舊版本；記的舊 ID 已不在知識庫則照一般匯入、記「新增」、不刪任何東西。新版本匯入失敗
  （例外，或描述／寫入失敗而文字已寫入）時 _discard_new_version 用 adelete_by_doc_id 刪掉它寫進知識庫的部分，不留失敗
  紀錄，所以 IngestReport.mark_failed 不設（整批結束後的 _mark_swallowed_failures 只改記 mark_failed 的新文件）；舊版本與
  對照表不變。清除本身失敗或舊版本刪不掉時，錯誤訊息寫出新舊兩個文件 ID。_remove_version 刪除前先查對照表：別的路徑
  還指向同一個文件 ID 時不刪，也不改對照表（呼叫端改寫或移除該路徑那一筆）；`--prune` 直接重用它。
- 用檔名遷移（_find_legacy_version，spec「匯入端：對照表」規則 3）：對照表沒有這個路徑、這次的 ID 也沒完整匯入時，用檔名
  到文件狀態找已完整處理、而且沒對照到任何路徑的文件：剛好一份當作舊版本替換，0 份記「新增」，多份拋 PipelineError 列出候選
  （該篇記成失敗，不替換也不新增，知識庫與對照表都沒動）。文件狀態只記檔名，同名的別份文件也會對到，所以對照表的排除是這條規則的
  安全網。已處理文件的狀態每批 _ingest 只載入一次、依檔名建索引（_ProcessedByFileName），不是每份新文件載入一次；索引是批次開始時的
  狀態，候選仍逐一用 is_document_fully_processed 查現況，所以批次途中被刪掉的舊版本不會被選中。
- 答案快取（_clear_answer_cache，spec「匯入端：答案快取」）：每份文件處理完（成功或失敗），只要那份文件的處理對 LightRAG
  的儲存做了寫入或刪除，就立刻清掉 LLM 快取裡 cache_type 為 query 的項目，保留 keywords（查詢關鍵字）與 extract／summary
  （匯入用的抽取快取），之後同一題用新的知識庫重新回答；不等整批結束，行程中途被停掉時已經改動的部分也已經清過。「有改動」
  由 _KnowledgeBaseChange 在呼叫 LightRAG 的寫入或刪除之前標記：開始 process_document_complete（解析完成、開始寫入；之後
  不論哪一步失敗都算）、清掉先前失敗的舊紀錄與呼叫 adelete_by_doc_id（刪除失敗也算呼叫過）；解析階段就失敗的、沒變、
  與別的路徑共用版本而沒有寫入或刪除的不標記，所以不清。不用 LightRAG 的 aclear_cache：它 drop 整個 LLM 快取。
  清掉的筆數累計在 IngestSummary.answer_cache_cleared。
  每份文件先寫對照表再清答案快取，整個逐份處理的迴圈包在 try/finally 裡：清快取（或迴圈裡其他步驟）丟出例外時，例外照樣往上拋，
  但這份與前面文件的 _mark_swallowed_failures 一定會做，描述失敗的文件才不會留在 processed。
- 來源已不在與 prune（_ingest 的 source_folder、prune 參數，spec「匯入端：替換與移除」）：對照表的來源資料夾記 `ingest <資料夾>`
  的那個資料夾（resolve() 後；Python API 指定了就記指定的，沒指定記檔案實體路徑所在的資料夾），所以資料夾裡指向別處的 symlink
  檔，對照表的路徑可以不在來源資料夾底下。指定了來源資料夾才在匯入之後檢查：對照表裡來源資料夾等於它、路徑在檔案系統上已不存在的
  文件，沒給 prune 只列在 IngestSummary.missing；給了 prune 就逐一刪（_prune_missing → _remove_version，保留抽取快取，別的路徑
  還用同一個版本時只移除這一筆）記在 removed，刪除失敗記在 remove_failed（知識庫與對照表那一筆都不動），每份文件只歸一類。
  來源資料夾不存在或沒有支援的文件、沒有來源資料夾卻給 prune，在做任何事之前拋 PipelineError（_require_valid_sync，
  防止路徑打錯時刪光一個資料夾的文件）。
- 重試未完成的文件（上次失敗、被中斷而卡在 processing，或文字完成但多模態沒做完）：先用
  LightRAG 的 adelete_by_doc_id 刪掉舊紀錄與部分結果，再重新匯入。LightRAG 遇到已存在的
  doc ID 不會重新排入，只會另寫一筆 status=failed 的 dup- 紀錄；刪除時保留 LLM 快取，
  上次已成功的 chunk 重跑時直接命中快取。
- 開始處理前先確認要用的端點連得上（models.check_reachable；匯入檢查 LLM、VLM、Embedding，查詢另加 Rerank），不可達就指出名稱與位址並立即
  失敗，不要等到解析完才發現。圖／表／公式的描述失敗不會讓 RAG-Anything 報錯（processor 吞掉
  後寫入 fallback 實體），描述後的內容寫入索引（儲存、embedding、實體抽取、合併）失敗也一樣：批次處理的例外被吞掉，
  改走逐項處理的備援流程，最後文件仍標成 processed 且 multimodal_processed=True。所以匯入時把每個 modal processor
  的 caption 函式包上計數（models.count_description_failures），LabRAGAnything 覆寫批次處理的方法計寫入失敗
  （models.record_write_failure），匯入後依 models.description_stats 判斷。有失敗的文件在整批結束後改記成 failed
  （_mark_swallowed_failures；批次途中改會被後面文件的插入蓋掉：LightRAG 插入新文件時會順便重跑索引裡 failed 的文件），
  報告的 error 寫出原因，重新執行時不會被略過、會先清掉舊紀錄再重匯。有失敗時不拋例外（拋了就看不到逐篇報告與其他篇的
  錯誤），而是記在該篇的 IngestReport.error 與 IngestSummary.description_error（含端點與位址），由 CLI 印完報告後
  以非零碼結束。
- 太大的表格（LabRAGAnything.parse_document，演算法見 rag_lab.tables）：RAG-Anything 把整張表放進同一個描述 prompt
  與同一個 chunk，80 列 × 21 欄的表格讓 mlx_lm.server 記憶體不足而停掉。掛勾點選在 parse_document 的回傳值：
  RAG-Anything 先依原始 content list 算好文件 ID、存好解析快取，LabRAGAnything 只改回傳給呼叫端的那一份，
  所以文件 ID、快取 key 與快取內容都不變，已匯入的文件照常被略過；process_document_complete 與 _ingest_one 都經由
  它取得 content list，每張小表因此是一個獨立的 table 項目，各自描述、各自成為一個 chunk。
- 查詢走 LightRAG 的 aquery_llm（回 status 與 message），不用 aquery：後者在 LLM 失敗
  時回 None、非法模式也回 None。status 不是 success 或沒有答案內容一律當失敗。
- 查詢預設 vlm_enhanced=False（只走 LLM、不讓 VLM 改寫答案；與 spec 一致，五種模式的答案才由
  同一個模型產生、可比較）。vlm_enhanced=True 時改走 RAGAnything.aquery_vlm_enhanced，並多檢查 VLM 端點。
- 所有查詢一律 enable_rerank=True（沒有開關）：LightRAG 在依 token 上限截斷之前，先把候選 chunk 送到本機
  reranker 重新排序（models.rerank_model_func）。rerank 函式必須在 build_rag 建立 LightRAG 時傳入：mix 等圖譜模式
  處理 chunk 時讀的是儲存層初始化時拿到的設定副本，初始化之後才設不會生效（LightRAG 1.4.16）。匯入不用 rerank。
  chunk_top_k 固定 20、min_rerank_score 固定 0.0（等於 LightRAG 的預設值，但明確傳入：LightRAG 會讀行程環境的
  CHUNK_TOP_K 與 MIN_RERANK_SCORE，不指定的話使用者 shell 裡的環境變數會悄悄改變查詢與 eval 的結果）。
- rerank 失敗讓該次查詢在產生答案之前中止：LightRAG 在 rerank 例外、空結果、index 超出範圍時都會改用原本的排序、查詢照常成功，
  還會把沒經過 rerank 的答案寫進 LLM 快取（key 不含 rerank 結果），之後同一題 rerank 成功時命中這筆舊答案。做法：
  models.rerank_model_func 判定失敗後拋出繼承 BaseException 的 models.RerankFailure，穿過 LightRAG（它只攔 Exception），
  _answer 與 VLM 增強路徑攔下並轉成 PipelineError（訊息含端點位址與端點回報的錯誤，不含 API key）。因為 rerank 發生在答案
  LLM 與 VLM 呼叫之前，中止時不會送出答案請求，也不會寫入答案快取。失敗只屬於那一次查詢：eval 的某一格失敗記在該格的
  Cell.error，下一格重新開始。rerank 與 LightRAG 自己同時會失敗時只報 rerank（查詢在 rerank 就中止，後面的階段不會執行）。
- eval（evaluate）在同一個 Session（同一個 RAGAnything 實例）上，依題目順序、五種模式順序依序查詢，
  不是每格重新初始化。每格沿用 query 的 _answer（aquery_llm、三個查詢 token 上限、vlm_enhanced=False、
  enable_rerank=True）；單格失敗（含沒有答案內容）記在該格的 Cell.error，不中斷其餘格。
  開始前檢查 LLM、Embedding 與 Rerank 端點可達（eval 不走 VLM）。
- 多篇匯入時單篇失敗不中斷整批：失敗記在該篇的 IngestReport.error，其餘照常處理並保留，
  由 CLI 印出是哪一篇並以非零碼結束。重新執行時已完整處理的篇略過、失敗的篇重試。
- 查詢 context 的 token 分配由三個設定決定：QUERY_MAX_TOTAL_TOKENS（總上限）、QUERY_MAX_ENTITY_TOKENS 與
  QUERY_MAX_RELATION_TOKENS（圖譜 context 裡 entity 與 relation 各自的上限）。LightRAG 預設總上限 30000，
  在 32 GB 的機器上 mlx_lm.server 處理 29.7k token 的 prompt 會 GPU 記憶體不足，所以總上限用 12000。
  LightRAG 的總上限不是硬上限：chunk 預算＝總上限 − KG context，KG context 另受 entity／relation 上限
  （預設 6000／8000）限制，所以三者直接取自設定、不依比例推算（ticket 13：依預設比例縮放時 mix 模式
  在 12000 下只剩 3–8 個 chunk 的空間）。設定檢查保證 entity ＋ relation 小於總上限。
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
- ingest 只接受 rag_lab.formats 列出的格式：整批先檢查，有任何一份不支援就拋 PipelineError、整批都不匯入。
  CLI 自己的檢查只負責資料夾裡「略過」與單檔的使用錯誤（結束碼 2）；Python API 沒有 CLI 擋在前面，
  不檢查的話 `.md`、`.mp3` 會直接進 RAG-Anything 的 parse_document，錯誤要到很深處才出現。
- 模組函式 ingest／query／evaluate 是「開 Session、呼叫一次、關閉」，CLI 經由它們使用 Session。
  開 Session 之前先檢查端點：端點不可達時不建立 WORKING_DIR、不跑 mineru。
- RAG-Anything 在建構時註冊 atexit(self.close)：實例會被留到 process 結束，結束時又用新的 event loop
  碰綁在舊 loop 上的鎖（錯誤被吞掉）。Session 建立實例後立即取消這個註冊，改註冊自己的收尾：忘了 close
  時在同一個 loop 上完整收尾並在 stderr 警告；正常 close 後取消，實例才能被回收。
- 每次 ingest 開始時把 models 的 VLM 與描述統計清零，報告只計這一次；描述失敗計數的包裝在 Session
  初始化後只包一次（每次 ingest 都包會疊成多層，同一次失敗被計多次）。
- Office 文件解析輸出的路徑含原檔路徑雜湊（_office_output_dir）：RAG-Anything 把 Office 轉成
  `<輸出資料夾>/<主檔名>.pdf`，主檔名相同的文件會互相覆蓋。只對 Office 文件另給 output_dir；PDF 與圖片的
  解析路徑（RAG-Anything 自己加 `<主檔名>_<雜湊>`）與解析快取 key 都不變，已匯入的文件重匯仍被略過。
- 計時用 RAG-Anything 的 ProcessingCallback：解析＝第一次 parse_document（之後 process
  內的 parse 是快取命中）；建圖＝文字插入（含 LightRAG 實體抽取）；多模態＝圖表公式描述。
- mineru 以 subprocess 依 PATH 尋找：PATH 上找不到時，把目前 Python 所在的 bin 目錄
  （專案 venv）附加到 PATH 尾端，使用者不需先 activate。已在 PATH 上的 mineru 優先，
  所以測試能以假 mineru 取代。這一步放在初始化：RAG-Anything 初始化時會先跑
  `mineru --version` 檢查 parser，查詢不解析文件也一樣要通過。

已知極限：
- 列舉查詢答案快取用 JsonKVStorage 的私有欄位 `_data` 與 `_storage_lock`：LightRAG 1.4.16 的 BaseKVStorage 沒有列出所有 key 的
  公開方法，而 aclear_cache 會連關鍵字與抽取快取一起清。刪除與寫檔（index_done_callback）走公開方法。
- rerank 失敗的偵測在 models.rerank_model_func：只涵蓋回應的格式與內容（請求例外、HTTP 錯誤、空結果、筆數、index、分數是否合法）。
  格式正確但排序品質差，這裡看不出來。
- 使用 RAGAnything 的私有方法 _ensure_lightrag_initialized：官方沒有公開的等價 API，
  但不先初始化就查詢會直接拋 ValueError。
- VLM 增強查詢（aquery_vlm_enhanced）沒有 aquery_llm 的 status／message：LLM 失敗時只回 None，
  這裡只能報「沒有回傳答案內容」，看不到原例外文字（VLM 失敗則有端點與位址）。
- 描述失敗不會讓 RAG-Anything 匯入失敗（圖片描述退成原始 dict 文字、表格與公式退成原始內容）；
  這裡只能事後依 models.description_stats 計數判斷並回報。文件改記成 failed，重新執行時先清掉舊紀錄再重匯
  （已寫入索引的退化描述一併清掉）；批次途中程序被中斷時，還沒改記的文件仍是 processed（重跑會略過）。
- 寫入失敗的計數在 RAGAnything 的私有方法 _process_multimodal_content_batch_type_aware 上：批次處理失敗後
  RAG-Anything 會用逐項處理的備援流程重做一次，備援成功時文件也照樣記成失敗（保守，重跑時 LLM 快取讓重做很便宜）；
  逐項處理本身的單項失敗不另外計數。改記狀態用私有方法 _upsert_doc_status。
- Session 讀的是開啟當下的索引：開著的期間另一個 process 匯入的內容，這個 Session 看不到。
- Session 是同步介面，不能直接在 Jupyter 或 async 函式裡使用（例外訊息附 asyncio.to_thread 的替代寫法）。
- 呼叫途中被中斷（KeyboardInterrupt）後不保證 Session 狀態一致；中斷後應關閉 Session 再開新的。

Dependencies: raganything、lightrag-hku（由 raganything 帶入）。
"""

import asyncio
import atexit
import hashlib
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from rag_lab.config import Settings, get_settings, reject_unmanaged_library_env
from rag_lab.evaluation import RETRIEVAL_MODES, Cell, Question
from rag_lab.formats import describe_supported, is_office, is_supported, list_folder

# 必須在 import lightrag 與 raganything 之前：它們在 import 時就讀環境變數當預設值（見 rag_lab.config）
reject_unmanaged_library_env()

from lightrag import QueryParam  # noqa: E402
from lightrag.base import DocStatus  # noqa: E402
from lightrag.kg.shared_storage import finalize_share_data  # noqa: E402
from raganything import RAGAnything, RAGAnythingConfig  # noqa: E402
from raganything.callbacks import ProcessingCallback  # noqa: E402

from rag_lab import models, registry, tables  # noqa: E402

# ==============================
# 常數與例外
# ==============================

# MinerU 解析後端。在 Mac（無 CUDA）上實測挑選，理由見 ticket 03 回報。
MINERU_BACKEND = "pipeline"

# 統計文件狀態時每頁讀幾筆（LightRAG 的上限是 200）
STATUS_PAGE_SIZE = 200

# 報告對每份成功的文件的分類（失敗的文件沒有分類）
OUTCOME_ADDED = "added"
OUTCOME_REPLACED = "replaced"
OUTCOME_UNCHANGED = "unchanged"

# LightRAG 的 LLM 快取項目的 cache_type：查詢答案。其餘有 keywords（查詢關鍵字）、extract（匯入的實體抽取）、summary
QUERY_CACHE_TYPE = "query"

# rerank 之後保留的 chunk 數與分數門檻。數值等於 LightRAG 的預設值，但 LightRAG 會讀行程環境的 CHUNK_TOP_K 與
# MIN_RERANK_SCORE（import 時決定預設），所以明確傳入，查詢行為才不受使用者 shell 裡的環境變數影響。
CHUNK_TOP_K = 20
MIN_RERANK_SCORE = 0.0


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


class LabRAGAnything(RAGAnything):
    """parse_document 之後把太大的表格縮短、切成小表的 RAGAnything（見 rag_lab.tables）。"""

    async def parse_document(self, *args, **kwargs):
        """解析文件（走解析快取），回傳的 content list 裡太大的表格已縮短或切成小表。

        文件 ID 與解析快取都是 RAG-Anything 依原始 content list 算好、存好的：這裡只改回傳給呼叫端的那一份，
        所以 ID、快取 key 與快取內容不變。

        Args:
            *args: 轉給 RAGAnything.parse_document。
            **kwargs: 轉給 RAGAnything.parse_document。

        Returns:
            (content_list, doc_id)；doc_id 是原始 content list 的內容雜湊。
        """
        content_list, doc_id = await super().parse_document(*args, **kwargs)

        def count_tokens(text: str) -> int:
            return len(self.lightrag.tokenizer.encode(text))

        return tables.limit_table_sizes(content_list, count_tokens), doc_id

    async def _process_multimodal_content_batch_type_aware(self, *args, **kwargs):
        """多模態內容的批次處理（描述完的 chunk 寫入索引）；失敗時先計數再照常重拋。

        RAG-Anything 會吞掉這裡的例外、改走逐項處理的備援流程，最後仍把文件標成已完成，所以失敗要在這裡記下來。

        Args:
            *args: 轉給 RAGAnything 的同名方法。
            **kwargs: 轉給 RAGAnything 的同名方法。

        Raises:
            Exception: 原本的例外，原樣往外拋（由 RAG-Anything 自己處理）。
        """
        try:
            return await super()._process_multimodal_content_batch_type_aware(*args, **kwargs)
        except Exception as exc:
            models.record_write_failure(exc)
            raise


def build_rag(settings: Settings) -> RAGAnything:
    """依設定建立 RAGAnything 實例（尚未初始化儲存）。

    Args:
        settings: 已驗證的設定。

    Returns:
        接好 LLM、VLM、embedding 三個模型函式與 rerank 函式的 RAGAnything。
    """
    config = RAGAnythingConfig(
        working_dir=settings.working_dir,
        parser_output_dir=settings.parser_output_dir,
        parser="mineru",
        parse_method="auto",
    )
    return LabRAGAnything(
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
            # rerank 函式必須在建立 LightRAG 時傳入：mix 等圖譜模式處理 chunk 時讀的是儲存層初始化時拿到的
            # 設定副本，初始化之後才設不會生效（LightRAG 1.4.16）。匯入不會用到它。
            "rerank_model_func": models.rerank_model_func,
            "min_rerank_score": MIN_RERANK_SCORE,
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
    """收集單一文件各階段耗時的 callback。

    階段時間由開始與完成兩個 callback 各取一次 `time.perf_counter` 相減，和 `_ingest` 量文件耗時用同一個時鐘，
    所以兩者可以互相比較，電腦睡眠的時間兩邊都不算。不用 callback 傳來的 `duration_seconds`：RAG-Anything 用
    `time.time` 算它，牆上時鐘在睡眠期間繼續走，階段時間會比文件耗時還長。
    """

    def __init__(self) -> None:
        self.parse_seconds: float | None = None
        self.text_insert_seconds = 0.0
        self.multimodal_seconds = 0.0
        self.multimodal_items = 0
        self._parse_started = 0.0
        self._text_insert_started = 0.0
        self._multimodal_started = 0.0

    def on_parse_start(self, file_path: str, **kwargs) -> None:
        """第一次解析才記開始時刻：之後 process_document_complete 內的 parse 是快取命中。"""
        if self.parse_seconds is None:
            self._parse_started = time.perf_counter()

    def on_parse_complete(self, file_path: str, **kwargs) -> None:
        """只記第一次：之後 process_document_complete 內的 parse 是快取命中。"""
        if self.parse_seconds is None:
            self.parse_seconds = time.perf_counter() - self._parse_started

    def on_text_insert_start(self, file_path: str, **kwargs) -> None:
        self._text_insert_started = time.perf_counter()

    def on_text_insert_complete(self, file_path: str, **kwargs) -> None:
        self.text_insert_seconds += time.perf_counter() - self._text_insert_started

    def on_multimodal_start(self, file_path: str, **kwargs) -> None:
        self._multimodal_started = time.perf_counter()

    def on_multimodal_complete(self, file_path: str, processed_count: int = 0, **kwargs) -> None:
        self.multimodal_items += processed_count
        self.multimodal_seconds += time.perf_counter() - self._multimodal_started


@dataclass
class IngestReport:
    """單篇文件匯入結果。

    Attributes:
        document: 文件路徑。
        skipped: True 表示已完整處理過，沒有重新匯入。
        parse_seconds: 解析耗時，Office 文件含 LibreOffice 轉 PDF（skipped 時為快取查詢時間）。
        graph_seconds: 文字建圖耗時（含 LLM 實體抽取）。
        multimodal_seconds: 圖／表／公式描述耗時。三個階段時間和 total_seconds 同樣用 time.perf_counter 量，
            不含電腦睡眠，同一篇的三者加總不超過 total_seconds。
        multimodal_items: 處理的圖／表／公式數。
        total_seconds: 這一篇從開始到結束的總耗時。
        error: 失敗時的「型別：訊息」；None 表示成功。
        description_failed: 這一篇的圖／表／公式描述失敗次數。
        write_failed: 這一篇的多模態內容寫入索引失敗次數。
        doc_id: 內容雜湊的文件 ID（RAG-Anything 的 doc- 開頭）；解析前就失敗的文件為 None。
        mark_failed: True 表示整批結束後要把這份文件在索引裡改記成 failed（新文件的圖／表／公式描述或寫入失敗）。
        outcome: 分類，OUTCOME_ADDED（新增）、OUTCOME_REPLACED（替換）或 OUTCOME_UNCHANGED（沒變）；失敗的文件為 None。
    """

    document: Path
    skipped: bool
    parse_seconds: float
    graph_seconds: float = 0.0
    multimodal_seconds: float = 0.0
    multimodal_items: int = 0
    total_seconds: float = 0.0
    error: str | None = None
    description_failed: int = 0
    write_failed: int = 0
    doc_id: str | None = None
    mark_failed: bool = False
    outcome: str | None = None


@dataclass
class IngestSummary:
    """一次 ingest 的整體結果。

    Attributes:
        reports: 每篇文件的報告。
        entities: 圖譜實體（節點）數。
        relations: 圖譜關係（邊）數，含 belongs_to。
        belongs_to: 其中 RAG-Anything 加的 belongs_to 邊數。
        status_counts: 文件狀態統計。
        vlm_ok: VLM 成功呼叫次數。
        vlm_failed: VLM 失敗呼叫次數。
        vlm_sample: 第一則 VLM 圖片描述（供人工判斷與原圖是否相符）。
        description_error: 有圖／表／公式描述或多模態內容寫入失敗時的完整說明（含端點與位址）；None 表示沒有。
        added: 分類為新增的文件（取 resolve() 後的絕對路徑，即對照表的鍵）。
        replaced: 分類為替換的文件（同上）。
        unchanged: 分類為沒變的文件（同上）。
        missing: 來源已不在（未刪）的文件：對照表記著來源資料夾等於這次的來源資料夾、檔案已不在檔案系統上，而且沒給 prune。
            沒指定來源資料夾時不檢查；給了 prune 時每份來源已不在的文件不是刪除成功就是刪除失敗，所以永遠是空的
            （每份文件只歸一類）。
        removed: prune 刪除成功的文件（對照表的鍵）；別的路徑還對照到同一個文件 ID 而沒有刪知識庫內容的也算。
        remove_failed: prune 刪除失敗的文件：對照表的鍵 → 「型別：訊息」。這些文件的知識庫內容與對照表那一筆都沒動。
        answer_cache_cleared: 這次 ingest 清掉的查詢答案快取筆數（每份有改動的文件處理完各清一次，加總）。
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
    added: list[Path] = field(default_factory=list)
    replaced: list[Path] = field(default_factory=list)
    unchanged: list[Path] = field(default_factory=list)
    missing: list[Path] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)
    remove_failed: dict[Path, str] = field(default_factory=dict)
    answer_cache_cleared: int = 0


@dataclass
class _KnowledgeBaseChange:
    """一份文件的處理有沒有對 LightRAG 的儲存做過寫入或刪除（spec「詞彙」的「知識庫有改動」）。

    在呼叫寫入或刪除之前就標記：呼叫中途失敗時，寫了一半的內容也算有改動。

    Attributes:
        changed: True 表示做過（或開始做）寫入或刪除。
    """

    changed: bool = False


async def _clear_answer_cache(rag: RAGAnything) -> int:
    """清掉 LLM 快取裡所有查詢答案的項目，保留查詢關鍵字與匯入用的抽取快取，並立刻寫回檔案。

    Args:
        rag: 已初始化的 RAGAnything。

    Returns:
        清掉的筆數。
    """
    cache = rag.lightrag.llm_response_cache
    async with cache._storage_lock:
        keys = [key for key, entry in cache._data.items() if entry.get("cache_type") == QUERY_CACHE_TYPE]
    if keys:
        await cache.delete(keys)
        await cache.index_done_callback()
    return len(keys)


def _office_output_dir(parser_output_dir: str, document: Path) -> Path:
    """Office 文件專屬的解析輸出資料夾，讓主檔名相同的文件不共用轉檔 PDF 與解析結果。

    RAG-Anything 把 Office 文件轉成 `<輸出資料夾>/<主檔名>.pdf`，MinerU 的解析資料夾再依這個 PDF 的路徑命名，
    所以 `a.docx` 與 `a.pptx`（或兩份 `a.docx`）會共用同一個 PDF 與解析資料夾。資料夾名稱含原檔絕對路徑的
    雜湊（與 RAG-Anything 對 PDF 與圖片的 `<主檔名>_<雜湊>` 做法相同），同一份文件每次都落在同一個資料夾。

    Args:
        parser_output_dir: PARSER_OUTPUT_DIR。
        document: Office 文件路徑。

    Returns:
        `<parser_output_dir>/office/<主檔名>_<原檔絕對路徑 md5 的前 8 碼>`。
    """
    digest = hashlib.md5(str(document.resolve()).encode()).hexdigest()[:8]
    return Path(parser_output_dir) / "office" / f"{document.stem}_{digest}"


def _classify_fully_processed(known: dict[str, dict[str, str]], key: str, doc_id: str) -> str:
    """已完整匯入的文件依對照表分類。

    Args:
        known: 對照表（路徑 → 紀錄）。
        key: 這份文件的對照表鍵（resolve() 後的絕對路徑）。
        doc_id: 這次解析出的文件 ID。

    Returns:
        OUTCOME_UNCHANGED：對照表記的就是這個 ID，或對照表沒有這個路徑而且沒有別的路徑對照到這個 ID
        （建立對照表之前就匯入的文件）。OUTCOME_REPLACED：這個路徑記的是另一個 ID（上次替換中斷：新版本已匯入、
        舊版本沒刪，呼叫端要補刪舊版本）。OUTCOME_ADDED：新的路徑和已對照的另一個路徑內容相同（共用版本）。
    """
    entry = known.get(key)
    if entry is not None:
        return OUTCOME_UNCHANGED if entry["doc_id"] == doc_id else OUTCOME_REPLACED
    shared = any(other["doc_id"] == doc_id for other in known.values())
    return OUTCOME_ADDED if shared else OUTCOME_UNCHANGED


async def _remove_version(
    rag: RAGAnything, known: dict[str, dict[str, str]], key: str, doc_id: str, change: _KnowledgeBaseChange
) -> None:
    """從知識庫刪掉一個版本，保留它的 LLM 抽取快取；還有別的路徑對照到它時不刪。

    替換的舊版本與 `--prune` 共用這個步驟（spec「匯入端：替換與移除」）：兩者都是「這個路徑不再使用這個版本」。
    這個函式不改對照表：呼叫端依情境改寫或移除 `key` 那一筆。

    Args:
        rag: 已初始化的 RAGAnything。
        known: 對照表（路徑 → 紀錄），只讀。
        key: 不再使用這個版本的路徑（對照表的鍵）。
        doc_id: 要刪的版本的文件 ID。
        change: 呼叫刪除之前標記「知識庫有改動」；別的路徑還對照到這個版本而沒有刪除時不標記。

    Raises:
        PipelineError: LightRAG 回報刪除失敗（訊息含狀態與原因）。
    """
    if any(other != key and entry["doc_id"] == doc_id for other, entry in known.items()):
        return
    change.changed = True
    deletion = await rag.lightrag.adelete_by_doc_id(doc_id, delete_llm_cache=False)
    # not_found：知識庫已經沒有它（例如上次刪到一半被中斷），目標狀態已達成
    if deletion.status not in ("success", "not_found"):
        raise PipelineError(f"刪除 {doc_id} 失敗（{deletion.status}）：{deletion.message}")


async def _remove_superseded_version(
    rag: RAGAnything,
    known: dict[str, dict[str, str]],
    document: Path,
    old_id: str,
    new_id: str,
    change: _KnowledgeBaseChange,
) -> None:
    """新版本已完整匯入後刪掉舊版本；失敗時訊息寫出新舊兩個文件 ID。

    Args:
        rag: 已初始化的 RAGAnything。
        known: 對照表（路徑 → 紀錄），只讀。
        document: 被替換的文件。
        old_id: 對照表記的舊版本文件 ID。
        new_id: 已完整匯入的新版本文件 ID。
        change: 見 _remove_version。

    Raises:
        PipelineError: 刪除舊版本失敗。對照表沒有改，下次 ingest 會依「這次的 ID 已完整匯入」補刪舊版本。
    """
    try:
        await _remove_version(rag, known, _registry_key(document), old_id, change)
    except Exception as exc:
        raise PipelineError(
            f"{document.name} 的新版本 {new_id} 已匯入，但刪除舊版本 {old_id} 失敗：{exc}。"
            f"知識庫現在可能同時有新舊兩個版本，對照表仍指向舊版本；修好後重新執行 ingest 會補刪舊版本"
        ) from exc


async def _discard_new_version(
    rag: RAGAnything, document: Path, new_id: str, old_id: str, reason: str
) -> PipelineError:
    """替換時新版本匯入失敗：刪掉它已寫進知識庫的部分，舊版本不動。

    不為新版本留下失敗紀錄：文件狀態裡的紀錄一併刪掉（見 _mark_swallowed_failures，替換失敗的新版本要排除在外）。

    Args:
        rag: 已初始化的 RAGAnything。
        document: 被替換的文件。
        new_id: 新版本的文件 ID。
        old_id: 舊版本的文件 ID（仍在知識庫）。
        reason: 新版本匯入失敗的原因。

    Returns:
        要呈現給使用者的 PipelineError：清除成功時說明舊版本仍在；清除本身失敗時寫出兩個文件 ID 與原因。
    """
    try:
        if await rag.lightrag.doc_status.get_by_id(new_id) is not None:
            deletion = await rag.lightrag.adelete_by_doc_id(new_id, delete_llm_cache=False)
            if deletion.status != "success":
                raise PipelineError(f"清除新版本 {new_id} 失敗（{deletion.status}）：{deletion.message}")
    except Exception as exc:
        return PipelineError(
            f"{document.name} 的新版本 {new_id} 匯入失敗：{reason}。清除它寫了一半的部分也失敗：{exc}。"
            f"舊版本 {old_id} 仍在知識庫，但新版本的殘留內容可能還在；重新執行 ingest 會重試"
        )
    return PipelineError(
        f"{document.name} 的新版本 {new_id} 匯入失敗：{reason}。已清除新版本寫了一半的部分，"
        f"舊版本 {old_id} 仍在知識庫、對照表不變；修好後重新執行 ingest 會重試替換"
    )


class _ProcessedByFileName:
    """已處理（PROCESSED）文件的文件 ID，依檔名建的索引；每批 _ingest 第一次需要時載入一次，不是每份文件載入一次。

    每份新文件都重新載入全部已處理文件的狀態，整批的工作量是 O(N²)；索引只在批次開始時的狀態上建立。批次途中被刪掉的
    舊版本仍在索引裡，但 `_find_legacy_version` 對每個候選都再用 `is_document_fully_processed` 查現況，已不在知識庫的會被排除。
    """

    def __init__(self) -> None:
        """_ProcessedByFileName 的建構；還沒有載入。"""
        self._ids_by_name: dict[str, list[str]] | None = None

    async def doc_ids(self, rag: RAGAnything, file_name: str) -> list[str]:
        """檔名相同的已處理文件的文件 ID。

        Args:
            rag: 已初始化的 RAGAnything。
            file_name: 檔名（文件狀態記的 file_path）。

        Returns:
            依文件 ID 排序的清單；沒有同名文件時為空。第一次呼叫時載入全部已處理文件的狀態。
        """
        if self._ids_by_name is None:
            processed = await rag.lightrag.doc_status.get_docs_by_status(DocStatus.PROCESSED)
            self._ids_by_name = {}
            for doc_id, status in sorted(processed.items()):
                self._ids_by_name.setdefault(status.file_path, []).append(doc_id)
        return self._ids_by_name.get(file_name, [])


async def _find_legacy_version(
    rag: RAGAnything, document: Path, known: dict[str, dict[str, str]], processed: _ProcessedByFileName
) -> str | None:
    """對照表沒有這個路徑時，用檔名到文件狀態找已完成的舊版本（spec「匯入端：對照表」規則 3 的最後一步）。

    文件狀態只記檔名（RAG-Anything 預設不記完整路徑），所以同名的別份文件也會對到；已經對照到別的路徑的文件 ID
    不是候選。ASSUMPTION：「已完成」以 `is_document_fully_processed` 判斷（文字與多模態都處理完）。

    Args:
        rag: 已初始化的 RAGAnything。
        document: 要匯入的文件（比對它的檔名）。
        known: 對照表（路徑 → 紀錄），只讀。
        processed: 這批的已處理文件索引（依檔名）。

    Returns:
        剛好一份候選時是它的文件 ID（當作舊版本）；沒有候選時是 None（新增）。

    Raises:
        PipelineError: 對到多份候選；訊息列出候選的文件 ID。不替換也不新增，知識庫與對照表都沒動。
    """
    registered = {entry["doc_id"] for entry in known.values()}
    candidates = []
    for doc_id in await processed.doc_ids(rag, document.name):
        if doc_id not in registered and await rag.is_document_fully_processed(doc_id):
            candidates.append(doc_id)
    if len(candidates) > 1:
        raise PipelineError(
            f"{document.name} 不在對照表裡，檔名在知識庫對到 {len(candidates)} 份文件（{', '.join(candidates)}），"
            f"無法判斷哪一份是舊版本，所以不替換也不新增；請確認後手動處理這些文件"
        )
    return candidates[0] if candidates else None


async def _ingest_one(
    rag: RAGAnything,
    document: Path,
    known: dict[str, dict[str, str]],
    change: _KnowledgeBaseChange,
    processed: _ProcessedByFileName,
) -> IngestReport:
    """匯入單篇文件；已完整處理就略過，先前未完成的先清掉舊紀錄再重匯，內容變了的先匯入新版本再刪舊版本。

    Args:
        rag: 已初始化的 RAGAnything。
        document: 文件路徑。
        known: 對照表（路徑 → 紀錄），只讀。
        change: 這份文件的處理對知識庫做過寫入或刪除時，在呼叫之前標記（成功或失敗都保留標記，由呼叫端據此清答案快取）。
        processed: 這批的已處理文件索引（依檔名），用檔名遷移時用；整批共用一份。

    Returns:
        這一篇的 IngestReport（total_seconds、description_failed、write_failed 由呼叫端填入）。成功時 outcome 是分類；
        新文件的圖／表／公式描述或多模態內容寫入失敗時，文件在索引裡改記成 failed（重新執行不會被略過），
        report.error 寫出原因，沒有分類；替換時同樣的失敗改成清掉新版本，舊版本留著，不為新版本留下失敗紀錄。

    Raises:
        PipelineError: 解析不出內容，清除舊紀錄失敗，替換時新版本匯入失敗（含清除寫了一半的部分失敗），
            或新版本已匯入但刪不掉舊版本。
        Exception: MinerU、LLM 等匯入過程的失敗（由 _ingest 轉成該篇的 report.error）。
    """
    timer = StageTimer()
    description_before, write_before = models.failure_counts()
    rag.callback_manager.register(timer)
    key = _registry_key(document)
    try:
        parse_kwargs: dict[str, object] = {"backend": MINERU_BACKEND}
        if is_office(document):
            # output_dir 不在 RAG-Anything 的解析快取 key 裡，所以已匯入的 Office 文件換了輸出資料夾仍認得出來、不重新解析
            parse_kwargs["output_dir"] = str(_office_output_dir(rag.config.parser_output_dir, document))
        content_list, doc_id = await rag.parse_document(str(document), **parse_kwargs)
        if not content_list:
            raise PipelineError(f"MinerU 沒有從 {document.name} 解析出任何內容（輸出資料夾：{rag.config.parser_output_dir}）")
        entry = known.get(key)
        old_id = entry["doc_id"] if entry is not None and entry["doc_id"] != doc_id else None
        if await rag.is_document_fully_processed(doc_id):
            outcome = _classify_fully_processed(known, key, doc_id)
            if outcome == OUTCOME_REPLACED:
                # 上次替換中斷：新版本已完整匯入、舊版本沒刪
                await _remove_superseded_version(rag, known, document, old_id, doc_id, change)
            return IngestReport(
                document, skipped=True, parse_seconds=timer.parse_seconds or 0.0, doc_id=doc_id, outcome=outcome
            )
        if entry is None:
            # 對照表沒有這個路徑（建立對照表之前匯入的文件，或新的路徑）：用檔名找舊版本，可能拋 PipelineError（對到多份）
            old_id = await _find_legacy_version(rag, document, known, processed)
        elif old_id is not None and await rag.lightrag.doc_status.get_by_id(old_id) is None:
            # 對照表記的舊版本已不在知識庫：照一般匯入新版本，不刪任何東西
            old_id = None
        if await rag.lightrag.doc_status.get_by_id(doc_id) is not None:
            change.changed = True
            deletion = await rag.lightrag.adelete_by_doc_id(doc_id)
            if deletion.status != "success":
                raise PipelineError(
                    f"{document.name} 先前的匯入沒有完成，清除舊紀錄 {doc_id} 失敗（{deletion.status}）：{deletion.message}"
                )
        change.changed = True
        try:
            await rag.process_document_complete(str(document), **parse_kwargs)
        except Exception as exc:
            if old_id is None:
                raise
            raise await _discard_new_version(rag, document, doc_id, old_id, f"{type(exc).__name__}: {exc}") from exc
    finally:
        rag.callback_manager.unregister(timer)
    report = IngestReport(
        document,
        skipped=False,
        parse_seconds=timer.parse_seconds or 0.0,
        graph_seconds=timer.text_insert_seconds,
        multimodal_seconds=timer.multimodal_seconds,
        multimodal_items=timer.multimodal_items,
        doc_id=doc_id,
    )
    description_after, write_after = models.failure_counts()
    if description_after > description_before or write_after > write_before:
        # RAG-Anything 吞掉這些失敗，仍把文件標成 processed 且 multimodal_processed=True
        reason = models.describe_failures(description_after - description_before, write_after - write_before)
        if old_id is not None:
            # 替換：清掉新版本、舊版本留著；沒有失敗紀錄，所以不用整批結束後改記
            report.error = str(await _discard_new_version(rag, document, doc_id, old_id, reason))
        else:
            # 新文件：_ingest 在整批結束後把它改記成 failed
            report.error = reason + "。文件已記成失敗，修好端點後重新執行 ingest 會重試這份文件"
            report.mark_failed = True
    elif old_id is None:
        # 沒有完整匯入過（新文件、先前失敗、或對照表記的舊版本已不在知識庫）：照一般匯入，成功就是新增
        report.outcome = OUTCOME_ADDED
    else:
        await _remove_superseded_version(rag, known, document, old_id, doc_id, change)
        report.outcome = OUTCOME_REPLACED
    return report


async def _mark_swallowed_failures(rag: RAGAnything, reports: list[IngestReport]) -> None:
    """把圖／表／公式描述或多模態寫入失敗的文件改記成 failed，下次 ingest 就不會略過它們。

    要等整批結束才改：LightRAG 每次插入新文件時會順便重跑索引裡所有 failed 的文件，並把狀態改回 processed
    （而且不帶 multimodal_processed），在批次途中改記會被後面的文件蓋掉。

    Args:
        rag: 已初始化的 RAGAnything。
        reports: 這一批的報告；只處理 mark_failed 的（新文件的描述或寫入失敗；替換失敗的新版本已被清掉，不記失敗紀錄）。
    """
    for report in reports:
        if report.mark_failed:
            await rag._upsert_doc_status(
                report.doc_id,
                str(report.document),
                status=DocStatus.FAILED,
                error_msg=report.error,
                multimodal_processed=False,
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


def _require_supported(documents: list[Path]) -> None:
    """確認整批文件的格式都支援；有任何一份不支援就拒絕整批。

    Args:
        documents: 要匯入的文件路徑。

    Raises:
        PipelineError: 有文件的格式不支援（只報第一份）；訊息格式與 CLI 的單檔錯誤相同。
    """
    for document in documents:
        if not is_supported(document):
            raise PipelineError(f"不支援的格式：{document.name}（支援的格式：{describe_supported()}）")


def _require_valid_sync(source_folder: Path | None, prune: bool) -> None:
    """確認來源資料夾與 prune 的組合合法；不合法就拒絕整批（和 CLI 的使用錯誤相同）。

    資料夾不存在或沒有任何支援的文件時不做移除（grill Q24：路徑打錯不能刪光一個資料夾的文件），不論有沒有給 prune。

    Args:
        source_folder: 來源資料夾；None 表示不檢查移除。
        prune: 是否要刪除來源已不在的文件。

    Raises:
        PipelineError: 沒有來源資料夾卻給了 prune；來源資料夾不存在、不是資料夾，或裡面沒有支援格式的文件。
    """
    if source_folder is None:
        if prune:
            raise PipelineError("prune 需要指定來源資料夾（source_folder）：沒有來源資料夾就不知道要檢查哪些文件")
        return
    folder = source_folder.resolve()
    if not folder.is_dir():
        raise PipelineError(f"來源資料夾不存在：{folder}")
    if not list_folder(folder)[0]:
        raise PipelineError(f"來源資料夾內沒有支援的文件：{folder}（支援的格式：{describe_supported()}）")


def _registry_key(document: Path) -> str:
    """文件在對照表裡的鍵：和 CLI 取路徑的方式相同，resolve() 成絕對的實體路徑。

    Args:
        document: 文件路徑。

    Returns:
        絕對路徑字串（symlink 已解析）。
    """
    return str(document.resolve())


def _load_registry(settings: Settings) -> dict[str, dict[str, str]]:
    """讀出對照表，壞掉時改拋 PipelineError。

    Args:
        settings: 已驗證的設定（取 WORKING_DIR）。

    Returns:
        路徑 → 紀錄；沒有對照表時是空 dict。

    Raises:
        PipelineError: 對照表讀不了、不是合法的 JSON 或格式不符（訊息含檔案路徑）。
    """
    try:
        return registry.load(settings.working_dir)
    except registry.RegistryError as exc:
        raise PipelineError(str(exc)) from exc


def _record_success(
    settings: Settings, known: dict[str, dict[str, str]], report: IngestReport, source_folder: str | None
) -> None:
    """文件處理成功後更新對照表那一筆並寫回檔案。

    沒變而且對照表已經是這個 ID 與這個來源資料夾時，保留原本那一筆、不寫檔。

    Args:
        settings: 已驗證的設定（取 WORKING_DIR）。
        known: 對照表（路徑 → 紀錄），會被更新。
        report: 成功的報告（outcome 與 doc_id 都有值）。
        source_folder: 這次指定的來源資料夾（resolve() 後的絕對路徑）；None 表示沒指定，記文件所在的資料夾。

    Raises:
        registry.RegistryError: 對照表寫不進去。
    """
    key = _registry_key(report.document)
    entry = known.get(key)
    # ASSUMPTION：來源資料夾記這次指定的資料夾，沒指定時記文件實體路徑所在的資料夾。資料夾裡的 symlink 檔 resolve 後
    # 可能不在該資料夾底下，所以兩者不能假設有上下層關係
    folder = source_folder if source_folder is not None else str(Path(key).parent)
    if report.outcome == OUTCOME_UNCHANGED and entry is not None and entry["doc_id"] == report.doc_id:
        if entry["source_folder"] == folder:
            return
        known[key] = {**entry, "source_folder": folder}
    else:
        known[key] = {
            "doc_id": report.doc_id,
            # ASSUMPTION：對照表建立之前匯入的文件，真正的匯入時間已不可考，記補登的時間
            "ingested_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source_folder": folder,
        }
    registry.save(settings.working_dir, known)


def _missing_sources(known: dict[str, dict[str, str]], source_folder: str) -> list[str]:
    """對照表裡來源資料夾等於指定資料夾、而檔案已不在檔案系統上的路徑。

    只比對表裡記的來源資料夾字串與路徑，不假設路徑在來源資料夾底下（資料夾裡的 symlink 檔 resolve 後可能在別處）。

    Args:
        known: 對照表（路徑 → 紀錄）。
        source_folder: 這次的來源資料夾（resolve() 後的絕對路徑）。

    Returns:
        依路徑排序的對照表鍵。
    """
    return sorted(
        key for key, entry in known.items() if entry["source_folder"] == source_folder and not Path(key).exists()
    )


async def _prune_missing(
    rag: RAGAnything, settings: Settings, known: dict[str, dict[str, str]], missing: list[str], summary: IngestSummary
) -> None:
    """逐一刪除來源已不在的文件：從知識庫刪掉它的版本（保留 LLM 抽取快取），再移除對照表那一筆。

    刪除前先查對照表：別的路徑還指向同一個文件 ID 時只移除這個路徑那一筆（見 _remove_version），仍記「已刪除」。
    單一文件刪除失敗不中斷其餘文件：記在 summary.remove_failed，知識庫內容與對照表那一筆都不動。

    Args:
        rag: 已初始化的 RAGAnything。
        settings: 已驗證的設定（取 WORKING_DIR）。
        known: 對照表（路徑 → 紀錄），刪除成功的那一筆會被移除。
        missing: 要刪除的對照表鍵。
        summary: 刪除結果記在它的 removed 與 remove_failed，清掉的答案快取筆數加進 answer_cache_cleared。

    Raises:
        PipelineError: 對照表寫不進去（這份文件的知識庫內容已刪，後面的文件不再處理）。
    """
    for key in missing:
        change = _KnowledgeBaseChange()
        try:
            await _remove_version(rag, known, key, known[key]["doc_id"], change)
        except Exception as exc:
            summary.remove_failed[Path(key)] = f"{type(exc).__name__}: {exc}"
        if change.changed:
            summary.answer_cache_cleared += await _clear_answer_cache(rag)
        if Path(key) in summary.remove_failed:
            continue
        del known[key]
        try:
            registry.save(settings.working_dir, known)
        except registry.RegistryError as exc:
            raise PipelineError(
                f"{exc}。{key} 已從知識庫刪除但對照表沒有更新，後面的文件沒有處理；修好後重新執行同一個 ingest --prune 即可"
            ) from exc
        summary.removed.append(Path(key))


async def _ingest(
    rag: RAGAnything,
    documents: list[Path],
    settings: Settings,
    source_folder: Path | None = None,
    prune: bool = False,
) -> IngestSummary:
    """在已初始化的 RAGAnything 上匯入一批文件並彙整結果。

    Args:
        rag: 已完成 _initialize 的實例。
        documents: 要匯入的文件路徑。
        settings: 已驗證的設定。
        source_folder: 來源資料夾（resolve() 後的絕對路徑）；給了就記成這批文件的來源資料夾，並在匯入之後檢查
            來源已不在的文件。None 表示不檢查。
        prune: True 時刪除來源已不在的文件（需要 source_folder）；False 時只列出。

    Returns:
        IngestSummary；單篇失敗與描述失敗都記在裡面，不拋例外。

    Raises:
        EndpointError: 開始前有端點不可達。
        PipelineError: 對照表壞掉（在處理任何文件之前）；對照表寫不進去（這份文件已匯入，後面的文件不再處理，
            已處理的收尾照常做完才拋；prune 刪除後寫不進去也拋，同樣不再處理後面的文件）。
    """
    known = _load_registry(settings)
    models.check_reachable("LLM", "VLM", "Embedding")
    models.reset_stats()
    summary = IngestSummary()
    folder = str(source_folder) if source_folder is not None else None
    registry_error: registry.RegistryError | None = None
    processed = _ProcessedByFileName()
    try:
        for document in documents:
            description_before, write_before = models.failure_counts()
            started = time.perf_counter()
            change = _KnowledgeBaseChange()
            try:
                report = await _ingest_one(rag, document, known, change, processed)
            except Exception as exc:
                # 單篇失敗不中斷整批：記下是哪一篇、為什麼，CLI 據此印出並以非零碼結束
                report = IngestReport(document, skipped=False, parse_seconds=0.0, error=f"{type(exc).__name__}: {exc}")
            report.total_seconds = time.perf_counter() - started
            report.description_failed = models.description_stats.failed - description_before
            report.write_failed = models.description_stats.write_failed - write_before
            summary.reports.append(report)
            # 先記對照表再清答案快取：清快取丟出例外時，這份文件已匯入的事實不能漏記
            if report.error is None:
                try:
                    _record_success(settings, known, report, folder)
                except registry.RegistryError as exc:
                    # 對照表寫不進去就不再處理後面的文件（它們也記不進去）；先把這份文件的答案快取清掉、前面文件的收尾做完再拋
                    registry_error = exc
            if change.changed:
                summary.answer_cache_cleared += await _clear_answer_cache(rag)
            if registry_error is not None:
                break
    finally:
        # 清答案快取等步驟丟出的例外照樣往上拋，但已處理的文件（含目前這份）的收尾一定要做：沒做的話，描述失敗的文件會留在 processed
        await _mark_swallowed_failures(rag, summary.reports)
    if registry_error is not None:
        raise PipelineError(
            f"{registry_error}。{summary.reports[-1].document.name} 已匯入知識庫但沒有記進對照表，"
            f"後面的文件沒有處理；修好後重新執行同一個 ingest 即可"
        ) from registry_error
    summary.added = [r.document.resolve() for r in summary.reports if r.outcome == OUTCOME_ADDED]
    summary.replaced = [r.document.resolve() for r in summary.reports if r.outcome == OUTCOME_REPLACED]
    summary.unchanged = [r.document.resolve() for r in summary.reports if r.outcome == OUTCOME_UNCHANGED]
    if folder is not None:
        missing = _missing_sources(known, folder)
        if prune:
            await _prune_missing(rag, settings, known, missing, summary)
        else:
            summary.missing = [Path(key) for key in missing]
    summary.entities, summary.relations, summary.belongs_to = await _graph_stats(rag)
    summary.status_counts = await _status_counts(rag)
    stats = models.vision_stats
    summary.vlm_ok, summary.vlm_failed, summary.vlm_sample = stats.ok, stats.failed, stats.sample
    described = models.description_stats
    if described.failed or described.write_failed:
        affected = sum(1 for report in summary.reports if report.description_failed or report.write_failed)
        summary.description_error = (
            f"有 {affected} 份文件的圖／表／公式描述或多模態內容寫入失敗（{models.describe_failures(described.failed, described.write_failed)}）。"
            f"RAG-Anything 不會因此報錯；這些文件匯入失敗（新文件記成失敗；替換的文件已清掉新版本、舊版本仍在），修好端點後重新執行同一個 ingest 就會重試，"
            f"不需要刪除 {settings.working_dir} 或 {settings.parser_output_dir}。"
        )
    return summary


def ingest(documents: list[Path], *, source_folder: Path | None = None, prune: bool = False) -> IngestSummary:
    """匯入一批文件：開一個 Session、匯入一次、關閉。

    Args:
        documents: 要匯入的文件路徑。
        source_folder: 來源資料夾（ASSUMPTION：參數名稱與型別由實作決定，spec 只規定要有）。給了就把它記成這批文件在
            對照表的來源資料夾（沒給時記文件所在的資料夾），並在匯入之後把對照表裡來源資料夾等於它、檔案已不在的文件列在
            IngestSummary.missing。沒給時不檢查。
        prune: True 時把那些來源已不在的文件從知識庫刪掉（保留 LLM 抽取快取）並移除對照表那一筆，記在
            IngestSummary.removed；只處理來源資料夾等於 source_folder 的紀錄。沒給 source_folder 時不能用。

    Returns:
        IngestSummary；單篇失敗與描述失敗記在裡面（reports[].error、description_error），由呼叫端決定結束碼。

    Raises:
        PipelineError: 有文件的格式不支援（整批都不匯入，且在開 Session 之前檢查），或初始化失敗等整批層級的可預期失敗。
        EndpointError: 開始前有端點不可達。
        SessionError: 已有開啟中的 Session，或在不允許的環境呼叫（見 Session）。
    """
    _require_supported(documents)
    _require_valid_sync(source_folder, prune)
    # Session 建構時只檢查 LLM 與 embedding；VLM 在開 Session 之前先檢查，不可達時不建立 WORKING_DIR、不跑 mineru
    models.check_reachable("VLM")
    with Session() as session:
        return session.ingest(documents, source_folder=source_folder, prune=prune)


# ==============================
# 查詢
# ==============================


def query_kwargs(settings: Settings) -> dict[str, object]:
    """組出 QueryParam 的共用參數，token 上限直接取自設定。

    Args:
        settings: 已驗證的設定（取 QUERY_MAX_TOTAL_TOKENS、QUERY_MAX_ENTITY_TOKENS、QUERY_MAX_RELATION_TOKENS）。

    Returns:
        可展開給 QueryParam（或 RAGAnything.aquery_vlm_enhanced）的參數 dict，不含 mode。
    """
    return {
        "enable_rerank": True,
        "chunk_top_k": CHUNK_TOP_K,
        "max_total_tokens": settings.query_max_total_tokens,
        "max_entity_tokens": settings.query_max_entity_tokens,
        "max_relation_tokens": settings.query_max_relation_tokens,
    }


def query_param(mode: str, settings: Settings) -> QueryParam:
    """組出查詢參數（見 query_kwargs）。

    Args:
        mode: 檢索模式。
        settings: 已驗證的設定。

    Returns:
        QueryParam。
    """
    return QueryParam(mode=mode, **query_kwargs(settings))


def _rerank_failed(failure: models.RerankFailure, mode: str) -> PipelineError:
    """把穿過 LightRAG 的 RerankFailure 轉成查詢失敗的例外。

    Args:
        failure: models.rerank_model_func 拋出的 RerankFailure（訊息已含端點位址與原因，不含 API key）。
        mode: 檢索模式（寫進錯誤訊息）。

    Returns:
        PipelineError：查詢在產生答案之前就中止。
    """
    return PipelineError(f"查詢失敗（mode={mode}）：rerank 失敗：{failure}")


async def _answer(rag: RAGAnything, question: str, mode: str, settings: Settings) -> str:
    """在已初始化的 RAGAnything 上以 aquery_llm 查詢（不啟用 VLM 增強）。

    Args:
        rag: 已完成 _initialize 的實例。
        question: 問題文字。
        mode: 檢索模式。
        settings: 已驗證的設定（取三個查詢 token 上限）。

    Returns:
        答案文字（非空字串）。

    Raises:
        PipelineError: rerank 失敗（LightRAG 已改用原本的排序，這裡不接受），LightRAG 回報查詢失敗
            （訊息含原例外文字），或成功但沒有答案內容。
    """
    try:
        result = await rag.lightrag.aquery_llm(question, query_param(mode, settings))
    except models.RerankFailure as exc:
        raise _rerank_failed(exc, mode) from exc
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
        PipelineError: rerank 失敗，查詢失敗（含查詢途中 LLM 失敗），或沒有答案內容。
    """
    models.check_reachable("LLM", "Embedding", "Rerank", *(["VLM"] if vlm_enhanced else []))
    if not vlm_enhanced:
        return await _answer(rag, question, mode, settings)
    # RAG-Anything 的 VLM 增強路徑：先取回檢索 prompt、把圖片路徑換成 base64 圖片再交給 VLM。
    # 它沒有 aquery_llm 的 status 欄位；失敗時回 None（LLM 失敗的訊息 LightRAG 已吞掉），
    # VLM 失敗則拋 EndpointError（含端點與位址）。
    try:
        answer = await rag.aquery_vlm_enhanced(question, mode=mode, **query_kwargs(settings))
    except models.RerankFailure as exc:
        raise _rerank_failed(exc, mode) from exc
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
        PipelineError: 初始化失敗、查詢失敗（含 rerank 失敗），或沒有答案內容。
        EndpointError: 開始前端點不可達，或 VLM 呼叫失敗。
        SessionError: 已有開啟中的 Session，或在不允許的環境呼叫（見 Session）。
    """
    # Session 建構時只檢查 LLM 與 embedding；rerank（查詢一律用）與 VLM（vlm_enhanced 時）在開 Session 之前先檢查
    models.check_reachable("Rerank", *(["VLM"] if vlm_enhanced else []))
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
        EndpointError: LLM、embedding 或 rerank 端點在開始前就不可達。
    """
    models.check_reachable("LLM", "Embedding", "Rerank")
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
    查詢固定 vlm_enhanced=False、enable_rerank=True，並沿用 query 的三個查詢 token 上限。

    Args:
        questions: 已驗證的題目。

    Returns:
        cells[i][j] 是第 i 題在 RETRIEVAL_MODES[j] 的結果；單格失敗記在該格的 error。

    Raises:
        EndpointError: LLM、embedding 或 rerank 端點在開始前就不可達。
        PipelineError: 初始化失敗。
        SessionError: 已有開啟中的 Session，或在不允許的環境呼叫（見 Session）。
    """
    # Session 建構時只檢查 LLM 與 embedding；rerank 在開 Session 之前先檢查
    models.check_reachable("Rerank")
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

    def ingest(
        self, documents: list[Path], *, source_folder: Path | None = None, prune: bool = False
    ) -> IngestSummary:
        """匯入一批文件（見模組函式 ingest）。

        Args:
            documents: 要匯入的文件路徑。
            source_folder: 來源資料夾；見模組函式 ingest。
            prune: 是否刪除來源已不在的文件；見模組函式 ingest。

        Returns:
            這一次匯入的 IngestSummary；VLM 與描述統計只計這一次。

        Raises:
            PipelineError: 有文件的格式不支援；整批都不匯入。
            SessionError: Session 已關閉，或從不允許的執行緒／環境呼叫。
            EndpointError: 開始前有端點不可達。
        """
        self._check_usable()
        _require_supported(documents)
        _require_valid_sync(source_folder, prune)
        folder = source_folder.resolve() if source_folder is not None else None
        return self._runner.run(_ingest(self._rag, documents, self._settings, folder, prune))

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
            PipelineError: 查詢失敗（含 rerank 失敗），或沒有答案內容。
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
            EndpointError: LLM、embedding 或 rerank 端點在開始前就不可達。
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
