"""fetch_papers.py 的離線行為測試：只驗證 ID 驗證階段，不碰網路。

為什麼存在：fetch_papers.py 是獨立腳本、沒有 CLI 縫可接，所以以 subprocess 呼叫腳本，
在公開介面（命令列參數、結束碼、stderr）觀察行為。需要網路的部分（標題比對、下載、
重複執行不重複下載）無法離線驗證，以真實執行的輸出為證據，不在此 mock。

關鍵設計決策：
- 每個案例都把 --out 指向暫存資料夾，並斷言它沒被建立：ID 驗證必須發生在任何
  網路請求與檔案寫入之前，這同時證明「不合法 ID 不會觸發下載」。

執行方式：python3 -m unittest scripts/test_fetch_papers.py

Dependencies: 僅標準函式庫。
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "fetch_papers.py"


# ==============================
# 工具函式
# ==============================


def run_script(*args: str) -> subprocess.CompletedProcess:
    """以 subprocess 執行 fetch_papers.py。

    Args:
        *args: 傳給腳本的命令列參數。

    Returns:
        已完成的行程（含 returncode、stdout、stderr，文字模式）。
    """
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


# ==============================
# 測試案例
# ==============================


class InvalidIdTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name) / "papers"

    def assert_rejected(self, bad_id: str, *other_ids: str) -> None:
        result = run_script("--out", str(self.out), "--ids", *other_ids, bad_id)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(bad_id, result.stderr)
        self.assertFalse(self.out.exists(), "ID 驗證失敗時不應建立輸出資料夾")

    def test_malformed_id_exits_nonzero_and_names_it(self) -> None:
        self.assert_rejected("not-an-id")

    def test_truncated_id_is_rejected(self) -> None:
        self.assert_rejected("2005.1140")

    def test_version_suffix_is_rejected(self) -> None:
        self.assert_rejected("2005.11401v4")

    def test_bad_id_after_valid_ids_is_named_and_nothing_runs(self) -> None:
        self.assert_rejected("20x4.16130", "2005.11401", "2404.16130")

    def test_well_formed_id_outside_the_list_is_rejected(self) -> None:
        # 格式合法但不在清單內：沒有預期標題可比對，不能下載。
        self.assert_rejected("1706.03762")


if __name__ == "__main__":
    unittest.main()
