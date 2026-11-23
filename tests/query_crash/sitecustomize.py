"""測試夾具：讓 `rag_lab.pipeline.Session.query` 對指定的問題拋出 rag_lab 預期之外的例外（RuntimeError）。

為什麼存在：知識庫工具要分辨「預期的失敗」（EndpointError、PipelineError，回帶原因的工具錯誤）與「預期之外的例外」
（留紀錄後照樣拋出）。假 OpenAI server 造得出的故障，rag_lab 都會轉成 EndpointError 或 PipelineError，
從 HTTP 邊界造不出預期之外的例外，所以在子行程裡包住 `Session.query`。

使用方式：把這個資料夾放進子行程的 `PYTHONPATH`，並設環境變數 `CRASH_QUERY_CONTAINING`；問題文字含這個字串時，
`Session.query` 拋出 RuntimeError，其餘問題照常查詢。沒設就什麼都不做。包裝在 `rag_lab.pipeline` 被 import 之後才安裝
（import hook），不會提早 import rag_lab 或 lightrag。

Dependencies: 僅標準函式庫。
"""

import importlib.abc
import importlib.util
import os
import sys

_marker = os.environ.get("CRASH_QUERY_CONTAINING")


def _install(module) -> None:
    """包住 Session.query：問題含指定字串時拋 RuntimeError，其餘照常。

    Args:
        module: 剛執行完的 rag_lab.pipeline 模組。
    """
    original = module.Session.query

    def query(self, question, mode, vlm_enhanced=False):
        if _marker in question:
            raise RuntimeError("injected unexpected failure")
        return original(self, question, mode, vlm_enhanced)

    module.Session.query = query


class _InstallAfterImport(importlib.abc.MetaPathFinder):
    """rag_lab.pipeline 執行完畢後安裝包裝（與 tests/delete_failure/sitecustomize.py 相同的做法）。"""

    def find_spec(self, fullname, path, target=None):
        """輪到 rag_lab.pipeline 時換掉它的載入函式，執行完再安裝包裝。

        Args:
            fullname: 正要 import 的模組全名。
            path: 套件的 `__path__`；這裡用不到。
            target: 重新載入時的既有模組；這裡用不到。

        Returns:
            rag_lab.pipeline 回傳載入函式已被換掉的 ModuleSpec（並把自己從 sys.meta_path 移除）；其他模組回傳 None。
        """
        if fullname != "rag_lab.pipeline":
            return None
        sys.meta_path.remove(self)
        spec = importlib.util.find_spec(fullname)
        run = spec.loader.exec_module

        def exec_module(module):
            run(module)
            _install(module)

        spec.loader.exec_module = exec_module
        return spec


if _marker:
    sys.meta_path.insert(0, _InstallAfterImport())
