"""假的 `libreoffice`／`soffice` 命令列：測試夾具，讓快速測試不必安裝 LibreOffice。

為什麼存在：RAG-Anything 把 Office 文件（.ppt .pptx .doc .docx .xls .xlsx）交給 mineru 之前，
先以 subprocess 呼叫 PATH 上的 LibreOffice 轉成 PDF：
`<cmd> --headless --convert-to pdf --outdir <dir> <檔案>`，再從 `<dir>` 讀出 `*.pdf`。這個假命令照同一份
介面在 `<dir>` 寫出 `<主檔名>.pdf`，所以 CLI 的 ingest 能在沒有 LibreOffice 的環境跑完 Office 文件的路徑。

關鍵設計決策：
- 測試要同時提供 `libreoffice` 與 `soffice` 兩個名稱（兩個 wrapper 呼叫同一支程式）：RAG-Anything 先找
  `libreoffice`，只放 `soffice` 的話，機器上裝了真的 LibreOffice 時測試會用到真的。
- 引數形式不符 `--headless --convert-to pdf --outdir <dir> <檔案>` 時以非零碼結束並印出收到的引數，
  RAG-Anything 改了呼叫方式時測試會變紅，不會被假命令默默接受。
- 主檔名以 `broken` 開頭時以非零碼結束，模擬轉檔失敗，比照假 mineru 的慣例。

已知極限：不讀輸入檔的內容，也不驗證它是不是真的 Office 檔；輸出的 PDF 只有檔頭與填充（RAG-Anything 要求
PDF 至少 100 bytes），不是可以顯示的 PDF，只有同樣不讀內容的假 mineru 會接手它。

Dependencies: 僅標準函式庫。
"""

import sys
from pathlib import Path

# RAG-Anything 把小於 100 bytes 的轉檔結果當成空檔
_PDF_BYTES = b"%PDF-1.4\n" + b"% fake libreoffice output\n" * 8


def main(argv: list[str]) -> int:
    """假 libreoffice 的進入點。

    Args:
        argv: 命令列引數（不含程式名稱）。

    Returns:
        結束碼；0 表示成功。
    """
    if len(argv) != 6 or argv[:3] != ["--headless", "--convert-to", "pdf"] or argv[3] != "--outdir":
        print(f"fake libreoffice: unexpected arguments: {argv}", file=sys.stderr)
        return 2
    outdir, source = Path(argv[4]), Path(argv[5])
    if source.stem.startswith("broken"):
        print(f"fake libreoffice: cannot convert {source.name}", file=sys.stderr)
        return 1
    (outdir / f"{source.stem}.pdf").write_bytes(_PDF_BYTES)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
