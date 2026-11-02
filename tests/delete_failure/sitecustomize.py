"""測試夾具：讓 LightRAG 的第 N 次 `adelete_by_doc_id` 回報刪除失敗、讓第 N 次刪除 LLM 快取的項目拋出例外，或數載入文件狀態的次數。

為什麼存在：替換時「清除新版本寫了一半的部分失敗」與「刪除舊版本失敗」需要 LightRAG 的刪除失敗，但假 OpenAI server 碰不到
刪除：刪除只讀寫本機儲存，重建圖譜只呼叫 embedding，而且重建的文字與匯入時的文字相同，server 沒辦法只讓刪除階段出錯。
所以在子行程啟動時包住 `LightRAG.adelete_by_doc_id`，第 N 次呼叫不真的刪，直接回 status="fail"。

清答案快取失敗（`FAIL_NTH_CACHE_DELETE`）同樣需要夾具：清除只讀寫本機的 LLM 快取儲存，假 OpenAI server 碰不到。所以包住
`JsonKVStorage.delete`，只計 `llm_response_cache` 這個儲存的呼叫，第 N 次呼叫不刪、拋出 OSError。

數載入次數（`COUNT_STATUS_LOADS_FILE`）：載入全部已處理文件的狀態只讀本機儲存，次數不會出現在假 server 的請求裡，所以包住
`JsonDocStatusStorage.get_docs_by_status`，每次呼叫在指定檔案附加一行狀態名稱（例如 `processed`），測試據此數次數。

使用方式：把這個資料夾放進子行程的 `PYTHONPATH`，並設環境變數 `FAIL_NTH_DELETE` 或 `FAIL_NTH_CACHE_DELETE`（從 1 算起的呼叫次數）、
`COUNT_STATUS_LOADS_FILE`（記錄檔路徑）；Python 啟動時自動載入 `sitecustomize`。沒設就什麼都不做。包裝在對應的 lightrag 模組被 import 之後才安裝（import hook），
所以不會提早 import lightrag：rag_lab 必須先檢查環境變數才能 import 它。

已知極限：只換 `adelete_by_doc_id`、`JsonKVStorage.delete`（限 llm_response_cache）與 `JsonDocStatusStorage.get_docs_by_status`，
其他刪除路徑（例如 LightRAG 的批次刪除）與其他讀取方法（例如 `get_docs_by_statuses`）不受影響；失敗計數只在這個行程內。

Dependencies: 僅標準函式庫（執行時才用到 lightrag）。
"""

import importlib.abc
import importlib.util
import os
import sys

_nth = os.environ.get("FAIL_NTH_DELETE")
_nth_cache = os.environ.get("FAIL_NTH_CACHE_DELETE")
_count_file = os.environ.get("COUNT_STATUS_LOADS_FILE")


def _install(module) -> None:
    """包住 LightRAG.adelete_by_doc_id：第 N 次呼叫回 status="fail"，其餘照常。

    Args:
        module: 剛執行完的 lightrag.lightrag 模組。
    """
    target = int(_nth)
    original = module.LightRAG.adelete_by_doc_id
    calls = 0

    async def adelete_by_doc_id(self, doc_id, delete_llm_cache=False):
        nonlocal calls
        calls += 1
        if calls == target:
            return module.DeletionResult(
                status="fail",
                doc_id=doc_id,
                message="injected deletion failure",
                status_code=500,
                file_path=None,
            )
        return await original(self, doc_id, delete_llm_cache)

    module.LightRAG.adelete_by_doc_id = adelete_by_doc_id


def _install_cache_failure(module) -> None:
    """包住 JsonKVStorage.delete：llm_response_cache 的第 N 次呼叫拋出 OSError，其餘照常。

    Args:
        module: 剛執行完的 lightrag.kg.json_kv_impl 模組。
    """
    target = int(_nth_cache)
    original = module.JsonKVStorage.delete
    calls = 0

    async def delete(self, ids):
        nonlocal calls
        if self.namespace.endswith("llm_response_cache"):
            calls += 1
            if calls == target:
                raise OSError("injected cache deletion failure")
        return await original(self, ids)

    module.JsonKVStorage.delete = delete


def _install_status_load_counter(module) -> None:
    """包住 JsonDocStatusStorage.get_docs_by_status：每次呼叫在記錄檔附加一行狀態名稱，結果照常回傳。

    Args:
        module: 剛執行完的 lightrag.kg.json_doc_status_impl 模組。
    """
    original = module.JsonDocStatusStorage.get_docs_by_status

    async def get_docs_by_status(self, status):
        with open(_count_file, "a", encoding="utf-8") as log:
            log.write(f"{status.value}\n")
        return await original(self, status)

    module.JsonDocStatusStorage.get_docs_by_status = get_docs_by_status


class _InstallAfterImport(importlib.abc.MetaPathFinder):
    """指定的模組執行完畢後安裝包裝。"""

    def __init__(self, module_name, install) -> None:
        self.module_name = module_name
        self.install = install

    def find_spec(self, fullname, path, target=None):
        if fullname != self.module_name:
            return None
        sys.meta_path.remove(self)
        spec = importlib.util.find_spec(fullname)
        run = spec.loader.exec_module

        def exec_module(module):
            run(module)
            self.install(module)

        spec.loader.exec_module = exec_module
        return spec


if _nth:
    sys.meta_path.insert(0, _InstallAfterImport("lightrag.lightrag", _install))
if _count_file:
    sys.meta_path.insert(0, _InstallAfterImport("lightrag.kg.json_doc_status_impl", _install_status_load_counter))
if _nth_cache:
    sys.meta_path.insert(0, _InstallAfterImport("lightrag.kg.json_kv_impl", _install_cache_failure))
