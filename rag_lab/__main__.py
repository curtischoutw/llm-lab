"""命令列入口：`python -m rag_lab {ingest,query,eval}`。

為什麼存在：spec 的唯一測試縫與使用者介面都是 CLI。本檔先把三個子命令註冊好，
並保證任何子命令啟動時都先驗證設定；真正的行為由後續 ticket 接上。

關鍵設計決策：
- 結束碼：0 成功、1 子命令尚未實作／執行失敗、2 命令列用法錯誤（argparse）、
  3 設定錯誤。
- 設定錯誤只輸出欄位名稱與原因類型，絕不輸出欄位值（可能是金鑰）。
- 設定驗證在 import 重量級模組（lightrag、torch）之前完成，錯誤能立即回報。

已知極限：ingest／query／eval 目前只是佔位，通過設定驗證後一律以 1 結束並
印出「尚未實作」。

Dependencies: 僅標準函式庫與 rag_lab.config。
"""

import argparse
import sys
from collections.abc import Sequence

from rag_lab.config import ConfigError, get_settings

# ==============================
# 常數
# ==============================

QUERY_MODES = ("naive", "local", "global", "hybrid", "mix")

EXIT_NOT_IMPLEMENTED = 1
EXIT_CONFIG_ERROR = 3


# ==============================
# 命令列解析
# ==============================


def build_parser() -> argparse.ArgumentParser:
    """建立 CLI 的 argparse 解析器。

    Returns:
        註冊好 ingest、query、eval 三個子命令的 ArgumentParser。
    """
    parser = argparse.ArgumentParser(prog="rag_lab", description="RAG-Anything 本地實驗 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="匯入單一 PDF 或整個資料夾")
    ingest.add_argument("path", help="PDF 檔或資料夾路徑")

    query = sub.add_parser("query", help="以指定檢索模式提問")
    query.add_argument("question", help="問題文字")
    query.add_argument("--mode", choices=QUERY_MODES, default="mix", help="檢索模式（預設 mix）")

    evaluate = sub.add_parser("eval", help="對題目檔批次比較五種檢索模式")
    evaluate.add_argument("questions", help="JSONL 題目檔路徑")

    return parser


# ==============================
# 主程式
# ==============================


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 進入點。

    Args:
        argv: 命令列引數（不含程式名稱）；None 時讀 sys.argv。

    Returns:
        結束碼，見模組 docstring。
    """
    args = build_parser().parse_args(argv)
    try:
        get_settings()
    except ConfigError as exc:
        print(f"設定錯誤：{exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    print(f"{args.command}：尚未實作", file=sys.stderr)
    return EXIT_NOT_IMPLEMENTED


if __name__ == "__main__":
    sys.exit(main())
