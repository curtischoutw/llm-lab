"""假的 `mineru` 命令列：測試夾具，讓快速測試不必真的跑 MinerU 模型。

為什麼存在：RAG-Anything 以 subprocess 呼叫 PATH 上的 `mineru -p <pdf> -o <dir> -m <method>`
並讀它寫出的 content list。這個假命令照同一份介面寫出一份小而固定的輸出（文字、
一張圖、一個表格、一條公式），所以 CLI 的 ingest 能在沒有 MinerU 模型的環境跑完整流程。

關鍵設計決策：
- 輸出版面對齊 MinerU 3.x：`<out>/<主檔名>/<method>/<主檔名>_content_list.json`，
  圖片放在同層 `images/`，content list 內用相對路徑，由 RAG-Anything 轉成絕對路徑。
- `--version` 要成功：RAG-Anything 的安裝檢查就是跑它。
- 依參數寫入 `argv.json` 旁證，測試可確認 RAG-Anything 實際傳了哪些參數。
- 內容只依 PDF 檔名（主檔名）決定，同一個檔案每次輸出相同。主檔名以 `multichunk` 開頭時
  多輸出 8 段長文字，讓 LightRAG 切出多個 chunk，測試能觀察多個 LLM 請求同時進行的情境。

已知極限：不讀 PDF 內容，也不驗證它是不是真的 PDF。

Dependencies: 僅標準函式庫。
"""

import argparse
import base64
import json
import sys
from pathlib import Path

# 1x1 透明 PNG
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def main(argv: list[str]) -> int:
    """假 mineru 的進入點。

    Args:
        argv: 命令列引數（不含程式名稱）。

    Returns:
        結束碼；0 表示成功。
    """
    if argv == ["--version"]:
        print("mineru, version fake")
        return 0

    parser = argparse.ArgumentParser(prog="mineru")
    parser.add_argument("-p", "--path", required=True)
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("-m", "--method", required=True)
    parser.add_argument("-b", "--backend")
    args = parser.parse_args(argv)

    stem = Path(args.path).stem
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
