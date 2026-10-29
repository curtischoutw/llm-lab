"""假的 headless Chrome 命令列：測試夾具，讓下載腳本的測試不必安裝 Chrome。

為什麼存在：scripts/fetch_taishin.py 以子行程呼叫 Chrome，把本機 HTML 檔列印成 PDF：
`<chrome> --headless --disable-gpu --no-pdf-header-footer --user-data-dir=<資料夾>
--print-to-pdf=<輸出 PDF> file://<HTML 檔>`。這個假命令照同一份介面寫出小 PDF，
測試可以在沒有 Chrome 的環境檢查腳本交給 Chrome 的內容。

關鍵設計決策：
- 輸出檔 = 假 PDF 檔頭 + 收到的 HTML 原文，讓測試能讀出「交給 Chrome 的 HTML 內容」。
- 引數形式不符上面的格式時（缺少、多出、順序以外的差異、輸入不是存在的本機 HTML 檔）以非零碼結束
  並印出收到的引數，腳本改了呼叫方式時測試會變紅，不會被假命令默默接受。
- 輸入的 HTML 含 `FAKE-CHROME-FAIL` 時以非零碼結束，模擬列印失敗。

已知極限：不載入 `<base href>` 指向的圖片，不驗證 HTML 是否可以顯示；輸出不是可以開啟的 PDF。

Dependencies: 僅標準函式庫。
"""

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
    html = source.read_bytes()
    if b"FAKE-CHROME-FAIL" in html:
        print(f"fake chrome: cannot print {source.name}", file=sys.stderr)
        return 1
    Path(output_arg.removeprefix("--print-to-pdf=")).write_bytes(_PDF_HEADER + html)
    return 0


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
