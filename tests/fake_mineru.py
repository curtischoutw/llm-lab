"""假的 `mineru` 命令列：測試夾具，讓快速測試不必真的跑 MinerU 模型。

為什麼存在：RAG-Anything 以 subprocess 呼叫 PATH 上的 `mineru -p <檔案> -o <dir> -m <method>`
並讀它寫出的 content list。這個假命令照同一份介面寫出一份小而固定的輸出（文字、
一張圖、一個表格、一條公式），所以 CLI 的 ingest 能在沒有 MinerU 模型的環境跑完整流程。

關鍵設計決策：
- 輸出版面對齊 MinerU 3.x：`<out>/<主檔名>/<method>/<主檔名>_content_list.json`，
  圖片放在同層 `images/`，content list 內用相對路徑，由 RAG-Anything 轉成絕對路徑。
- `--version` 要成功：RAG-Anything 的安裝檢查就是跑它（每個 RAGAnything 實例初始化時一次）。環境變數
  `FAKE_MINERU_VERSION_LOG` 有設定時，每次 `--version` 在該檔附加一行，測試據此數初始化次數。
- 依參數寫入 `argv.json` 旁證，測試可確認 RAG-Anything 實際傳了哪些參數。
- 內容只依輸入檔的主檔名決定，同一個檔案每次輸出相同；唯一的例外：輸入的 PDF 帶有假 LibreOffice 寫的
  `% fake libreoffice source: <文字>` 一行時，多輸出一段文字 `Converted from Office document: <文字>`，
  讓主檔名相同的兩份 Office 文件能分辨；PDF、圖片（method 為 ocr）與假 LibreOffice 轉出的 PDF（tests/fake_libreoffice.py，主檔名與原 Office 文件相同）輸出相同的內容。圖片若不是 png／jpg，
  RAG-Anything 會先轉成 `<主檔名>_converted.png` 再交給 mineru，所以主檔名會多一個 `_converted`。
- 主檔名以 `broken` 開頭時以非零碼結束，模擬解析失敗。主檔名以 `multichunk` 開頭時
  多輸出 8 段長文字，讓 LightRAG 切出多個 chunk，測試能觀察多個 LLM 請求同時進行的情境。
- 主檔名以 `bigtable` 開頭時，把固定的小表格換成 `big_table_html()` 的大表格（MinerU 的寫法：每個儲存格都帶
  `rowspan=1 colspan=1`，一組跨兩列的儲存格），測試用它檢查太大的表格會縮短並拆成小表。主檔名以 `spans` 開頭時，
  小表格的儲存格帶 `rowspan=1 colspan=1`，測試用它確認不大的表格送去描述的內容不變。主檔名以 `bigspan` 開頭時，
  大表格的第 20 列第一格 rowspan 跨到表尾（像道路救援那張表的空儲存格 rowspan=57），測試用它確認被 rowspan 連在一起、
  單獨就超過上限的列也會切開。

已知極限：除了上述標記行，不讀檔案內容，也不驗證它是不是真的 PDF 或圖片；圖片不會真的做 OCR。

Dependencies: 僅標準函式庫。
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

# 1x1 透明 PNG
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


BIG_TABLE_COLUMNS = 6
BIG_TABLE_ROWS = 60


BIG_TABLE_SPAN_START = 20


def big_table_html(span_to_end: bool = False) -> str:
    """MinerU 寫法的大表格：一列表頭加 BIG_TABLE_ROWS 列資料，每個儲存格帶預設的 rowspan／colspan。

    儲存格文字是 `R<列>C<欄>`，表頭是 `H<欄>`。列號是 10 的倍數的那一列，第一格 rowspan=2 跨到下一列，
    下一列就少一格（和 MinerU 輸出合併儲存格的方式相同）。

    Args:
        span_to_end: True 時改成第 BIG_TABLE_SPAN_START 列的第一格 rowspan 跨到表尾，之後每一列都少第一格。

    Returns:
        完整的 `<table>...</table>` 字串。
    """

    def cell(text: str, rowspan: int = 1) -> str:
        return f"<td rowspan={rowspan} colspan=1>{text}</td>"

    rows = ["<tr>" + "".join(cell(f"H{c}") for c in range(BIG_TABLE_COLUMNS)) + "</tr>"]
    for r in range(BIG_TABLE_ROWS):
        cells = []
        for c in range(BIG_TABLE_COLUMNS):
            if span_to_end:
                if c == 0 and r > BIG_TABLE_SPAN_START:
                    continue
                rowspan = BIG_TABLE_ROWS - r if c == 0 and r == BIG_TABLE_SPAN_START else 1
            else:
                if c == 0 and r % 10 == 1:
                    continue
                rowspan = 2 if c == 0 and r % 10 == 0 else 1
            cells.append(cell(f"R{r}C{c}", rowspan=rowspan))
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "<table>" + "".join(rows) + "</table>"


def main(argv: list[str]) -> int:
    """假 mineru 的進入點。

    Args:
        argv: 命令列引數（不含程式名稱）。

    Returns:
        結束碼；0 表示成功。
    """
    if argv == ["--version"]:
        log = os.environ.get("FAKE_MINERU_VERSION_LOG")
        if log:
            with open(log, "a", encoding="utf-8") as handle:
                handle.write("--version\n")
        print("mineru, version fake")
        return 0

    parser = argparse.ArgumentParser(prog="mineru")
    parser.add_argument("-p", "--path", required=True)
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("-m", "--method", required=True)
    parser.add_argument("-b", "--backend")
    args = parser.parse_args(argv)

    stem = Path(args.path).stem
    if stem.startswith("broken"):
        print(f"fake mineru: cannot parse {stem}", file=sys.stderr)
        return 1
    method_dir = Path(args.output) / stem / ("auto" if args.method == "auto" else args.method)
    (method_dir / "images").mkdir(parents=True, exist_ok=True)
    (method_dir / "images" / "fig1.png").write_bytes(_PNG_1X1)

    content = [
        {"type": "text", "text": f"A Study of Fake Entities in {stem}", "text_level": 1, "page_idx": 0},
        {"type": "text", "text": "Fake Entity Alpha works together with Fake Entity Beta.", "page_idx": 0},
        {
            "type": "image",
            "img_path": "images/fig1.png",
            "image_caption": ["Figure 1: a red square"],
            "image_footnote": [],
            "page_idx": 1,
        },
        {
            "type": "table",
            "table_body": "<table><tr><td>a</td><td>b</td></tr><tr><td>1</td><td>2</td></tr></table>",
            "table_caption": ["Table 1: numbers"],
            "table_footnote": [],
            "page_idx": 1,
        },
        {"type": "equation", "text": "E = mc^2", "text_format": "latex", "page_idx": 1},
    ]
    if stem.startswith("bigtable") or stem.startswith("bigspan"):
        content[3]["table_body"] = big_table_html(span_to_end=stem.startswith("bigspan"))
    elif stem.startswith("spans"):
        content[3]["table_body"] = (
            "<table><tr><td rowspan=1 colspan=1>a</td><td rowspan=1 colspan=1>b</td></tr>"
            "<tr><td rowspan=1 colspan=1>1</td><td rowspan=1 colspan=1>2</td></tr></table>"
        )
    marker = b"% fake libreoffice source: "
    pdf_lines = Path(args.path).read_bytes().splitlines() if Path(args.path).suffix.lower() == ".pdf" else []
    for line in pdf_lines:
        if line.startswith(marker):
            source_text = line.removeprefix(marker).decode("utf-8", errors="replace")
            content.append({"type": "text", "text": f"Converted from Office document: {source_text}", "page_idx": 0})
    if stem.startswith("multichunk"):
        for i in range(8):
            text = " ".join(f"Fake Entity {i}-{j} relates to Fake Entity {i}-{j + 1}." for j in range(250))
            content.append({"type": "text", "text": text, "page_idx": 2 + i})
    (method_dir / f"{stem}_content_list.json").write_text(json.dumps(content), encoding="utf-8")
    (method_dir / f"{stem}.md").write_text(f"# {stem}\n", encoding="utf-8")
    (method_dir / "argv.json").write_text(json.dumps(argv), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
