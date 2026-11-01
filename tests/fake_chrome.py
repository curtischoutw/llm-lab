"""假的 headless Chrome 命令列：測試夾具，讓下載腳本的測試不必安裝 Chrome。

為什麼存在：scripts/fetch_taishin.py 以子行程呼叫 Chrome，把本機 HTML 檔列印成 PDF：
`<chrome> --headless --disable-gpu --no-pdf-header-footer --user-data-dir=<資料夾>
--print-to-pdf=<輸出 PDF> file://<HTML 檔>`，另外 `--user-data-dir` 資料夾裡要有
`Default/Preferences`，把 JavaScript 設成封鎖。這個假命令照同一份介面寫出小 PDF，
測試可以在沒有 Chrome 的環境檢查腳本交給 Chrome 的內容。

關鍵設計決策：
- 輸出檔 = 假 PDF 檔頭 + 收到的 HTML 原文，讓測試能讀出「交給 Chrome 的 HTML 內容」。
- 引數形式不符上面的格式時（缺少、多出、順序以外的差異、輸入不是存在的本機 HTML 檔）以非零碼結束
  並印出收到的引數，腳本改了呼叫方式時測試會變紅，不會被假命令默默接受。
- 輸入的 HTML 含 `FAKE-CHROME-FAIL` 時以非零碼結束，模擬列印失敗。
- 停用 JavaScript 用的是 profile 的 Preferences（`profile.default_content_setting_values.javascript` = 2），不是命令列參數：
  2026-10-30 用真的 Chrome 對本機 HTML 實測，`--disable-javascript` 沒有效果（inline script 與 onload 照常執行），
  `--blink-settings=scriptEnabled=false` 會讓 `--print-to-pdf` 結束碼 0 但沒有產出 PDF，只有 Preferences 有效。
  profile 沒有這個設定時假命令以非零碼結束，腳本沒有封鎖 JavaScript 時測試會變紅。

已知極限：不載入 `<base href>` 指向的圖片，不驗證 HTML 是否可以顯示；輸出不是可以開啟的 PDF。

Dependencies: 僅標準函式庫。
"""

import json
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

_FIXED_FLAGS = ["--headless", "--disable-gpu", "--no-pdf-header-footer"]
_PDF_HEADER = b"%PDF-1.4\n% fake chrome output\n"


def main(argv: list[str]) -> int:
    """假 Chrome 的進入點。

    Args:
        argv: 命令列引數（不含程式名稱）。

    Returns:
        結束碼；0 表示成功。
    """
    if len(argv) != 6 or argv[:3] != _FIXED_FLAGS:
        return _reject(argv)
    profile_arg, output_arg, url = argv[3:]
    if not profile_arg.startswith("--user-data-dir=") or not profile_arg.removeprefix("--user-data-dir="):
        return _reject(argv)
    if not output_arg.startswith("--print-to-pdf=") or not output_arg.removeprefix("--print-to-pdf=").endswith(".pdf"):
        return _reject(argv)
    parsed = urlparse(url)
    source = Path(unquote(parsed.path))
    if parsed.scheme != "file" or source.suffix != ".html" or not source.is_file():
        return _reject(argv)
    if not _blocks_javascript(Path(profile_arg.removeprefix("--user-data-dir="))):
        print(f"fake chrome: profile does not block javascript (Default/Preferences): {argv}", file=sys.stderr)
        return 2
    html = source.read_bytes()
    if b"FAKE-CHROME-FAIL" in html:
        print(f"fake chrome: cannot print {source.name}", file=sys.stderr)
        return 1
    Path(output_arg.removeprefix("--print-to-pdf=")).write_bytes(_PDF_HEADER + html)
    return 0


def _blocks_javascript(profile: Path) -> bool:
    """profile 的 Default/Preferences 是否把 JavaScript 設成封鎖。

    Args:
        profile: `--user-data-dir` 指定的資料夾。

    Returns:
        content setting `javascript` 為 2（封鎖）時為 True；檔案不存在、不是 JSON 或設定不同時為 False。
    """
    try:
        preferences = json.loads((profile / "Default" / "Preferences").read_text())
        return preferences["profile"]["default_content_setting_values"]["javascript"] == 2
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _reject(argv: list[str]) -> int:
    """印出收到的引數並回傳非零碼。

    Args:
        argv: 命令列引數。

    Returns:
        固定回傳 2。
    """
    print(f"fake chrome: unexpected arguments: {argv}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
