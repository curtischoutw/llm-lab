"""測試夾具：讓 LightRAG 的第 N 次 `adelete_by_doc_id` 回報刪除失敗。

為什麼存在：替換時「清除新版本寫了一半的部分失敗」與「刪除舊版本失敗」需要 LightRAG 的刪除失敗，但假 OpenAI server 碰不到
刪除：刪除只讀寫本機儲存，重建圖譜只呼叫 embedding，而且重建的文字與匯入時的文字相同，server 沒辦法只讓刪除階段出錯。
所以在子行程啟動時包住 `LightRAG.adelete_by_doc_id`，第 N 次呼叫不真的刪，直接回 status="fail"。

使用方式：把這個資料夾放進子行程的 `PYTHONPATH`，並設環境變數 `FAIL_NTH_DELETE`（從 1 算起的呼叫次數）；Python 啟動時自動載入
`sitecustomize`。沒設 `FAIL_NTH_DELETE` 就什麼都不做。包裝在 `lightrag.lightrag` 被 import 之後才安裝（import hook），
所以不會提早 import lightrag：rag_lab 必須先檢查環境變數才能 import 它。

已知極限：只換 `adelete_by_doc_id`，其他刪除路徑（例如 LightRAG 的批次刪除）不受影響；計數只在這個行程內。

Dependencies: 僅標準函式庫（執行時才用到 lightrag）。
"""

import importlib.abc
import importlib.util
import os
import sys

_nth = os.environ.get("FAIL_NTH_DELETE")


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


class _InstallAfterImport(importlib.abc.MetaPathFinder):
    """lightrag.lightrag 執行完畢後安裝包裝。"""

    def find_spec(self, fullname, path, target=None):
        if fullname != "lightrag.lightrag":
            return None
        sys.meta_path.remove(self)
        spec = importlib.util.find_spec(fullname)
        run = spec.loader.exec_module

        def exec_module(module):
            run(module)
            _install(module)

        spec.loader.exec_module = exec_module
        return spec


if _nth:
    sys.meta_path.insert(0, _InstallAfterImport())
