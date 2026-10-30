"""假的 `libreoffice`／`soffice` 命令列：測試夾具，讓快速測試不必安裝 LibreOffice。

為什麼存在：兩個呼叫端要在沒有 LibreOffice 的環境測試。
- RAG-Anything 把 Office 文件（.ppt .pptx .doc .docx .xls .xlsx）交給 mineru 之前，
  先以 subprocess 呼叫 PATH 上的 LibreOffice 轉成 PDF：
  `<cmd> --headless --convert-to pdf --outdir <dir> <檔案>`，再從 `<dir>` 讀出 `*.pdf`。這個假命令照同一份
  介面在 `<dir>` 寫出 `<主檔名>.pdf`，所以 CLI 的 ingest 能在沒有 LibreOffice 的環境跑完 Office 文件的路徑。
- scripts/fetch_taishin.py 把權益子頁的本機 HTML 轉成 Word：
  `<cmd> -env:UserInstallation=file://<新的 profile 資料夾> --headless --convert-to "docx:MS Word 2007 XML"
  --outdir <dir> <HTML 檔>`，假命令在 `<dir>` 寫出 `<主檔名>.docx`。

關鍵設計決策：
- 測試要同時提供 `libreoffice` 與 `soffice` 兩個名稱（兩個 wrapper 呼叫同一支程式）：RAG-Anything 先找
  `libreoffice`，只放 `soffice` 的話，機器上裝了真的 LibreOffice 時測試會用到真的。
- 引數形式不符 `--headless --convert-to pdf --outdir <dir> <檔案>` 時以非零碼結束並印出收到的引數，
  RAG-Anything 改了呼叫方式時測試會變紅，不會被假命令默默接受。
- 主檔名以 `broken` 開頭時以非零碼結束，模擬轉檔失敗，比照假 mineru 的慣例（兩種目標格式都一樣）。
- 轉 docx 的目標一定要寫成 `docx:MS Word 2007 XML`，只寫 `docx` 會被拒絕：2026-10-30 實測，真的 LibreOffice
  把 HTML 當成 Writer/Web 文件開啟，目標只寫 `docx` 時回報 "no export filter"，要指定濾鏡名稱才能轉。
  這樣腳本改回只寫 `docx` 時測試會變紅。
- 轉 docx 一定要帶第一個引數 `-env:UserInstallation=file://<資料夾>`，而且資料夾不能是已經用過的：2026-10-30 的
  code-review 指出，使用者開著 LibreOffice 時，沒有指定 profile 的 headless 轉檔會結束碼 0 但沒有產出。
  假命令照真的 LibreOffice 的行為在該資料夾建立 `user/registrymodifications.xcu`，所以腳本沒帶這個引數、
  引數不是 file:// 網址、或兩次轉檔共用同一個資料夾時，測試會變紅。轉 PDF 不接受這個引數（維持原本的嚴格檢查）。
- 轉 docx 時，輸出檔 = 假 docx 檔頭（`PK`）+ 收到的 HTML 原文，讓測試能讀出「交給 LibreOffice 的 HTML 內容」，
  比照假 Chrome。轉 PDF 的輸出不變。

已知極限：轉 PDF 時不讀輸入檔的內容，也不驗證它是不是真的 Office 檔；輸出的 PDF 只有檔頭與填充（RAG-Anything 要求
PDF 至少 100 bytes），不是可以顯示的 PDF，只有同樣不讀內容的假 mineru 會接手它。轉 docx 的輸出不是可以開啟的 Word 檔。

Dependencies: 僅標準函式庫。
"""

import sys
from pathlib import Path
from urllib.parse import unquote

# RAG-Anything 把小於 100 bytes 的轉檔結果當成空檔
_PDF_BYTES = b"%PDF-1.4\n" + b"% fake libreoffice output\n" * 8
_DOCX_HEADER = b"PK\x03\x04 fake libreoffice output\n"
_DOCX_TARGET = "docx:MS Word 2007 XML"
_PROFILE_PREFIX = "-env:UserInstallation=file://"


def main(argv: list[str]) -> int:
    """假 libreoffice 的進入點。

    Args:
        argv: 命令列引數（不含程式名稱）。

    Returns:
        結束碼；0 表示成功。
    """
    args = list(argv)
    profile_arg = args.pop(0) if len(args) == 7 and args[0].startswith("-env:") else None
    if len(args) != 6 or args[:2] != ["--headless", "--convert-to"] or args[3] != "--outdir" or args[2] not in ("pdf", _DOCX_TARGET):
        print(f"fake libreoffice: unexpected arguments: {argv}", file=sys.stderr)
        return 2
    target, outdir, source = args[2], Path(args[4]), Path(args[5])
    if (target == "pdf") != (profile_arg is None):
        reason = "pdf takes no user profile" if target == "pdf" else "docx needs -env:UserInstallation=file://<dir>"
        print(f"fake libreoffice: {reason}: {argv}", file=sys.stderr)
        return 2
    if profile_arg is not None and not _create_profile(profile_arg):
        print(f"fake libreoffice: user profile is not a new file:// folder (already in use?): {argv}", file=sys.stderr)
        return 2
    if source.stem.startswith("broken"):
        print(f"fake libreoffice: cannot convert {source.name}", file=sys.stderr)
        return 1
    if target == "pdf":
        (outdir / f"{source.stem}.pdf").write_bytes(_PDF_BYTES)
    else:
        (outdir / f"{source.stem}.docx").write_bytes(_DOCX_HEADER + source.read_bytes())
    return 0


def _create_profile(profile_arg: str) -> bool:
    """照真的 LibreOffice 的行為建立 user profile 資料夾。

    Args:
        profile_arg: `-env:UserInstallation=file://<資料夾>` 引數。

    Returns:
        資料夾建立成功時為 True；引數不是 file:// 網址，或資料夾已經存在（已被使用）時為 False。
    """
    if not profile_arg.startswith(_PROFILE_PREFIX) or not profile_arg.removeprefix(_PROFILE_PREFIX).startswith("/"):
        return False
    profile = Path(unquote(profile_arg.removeprefix(_PROFILE_PREFIX)))
    if profile.exists():
        return False
    (profile / "user").mkdir(parents=True)
    (profile / "user" / "registrymodifications.xcu").write_text("<fake/>")
    return True


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
