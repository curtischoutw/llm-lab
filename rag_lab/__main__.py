"""命令列入口：`python -m rag_lab {ingest,query,eval}`。

為什麼存在：spec 的唯一測試縫與使用者介面都是 CLI。本檔註冊三個子命令，保證任何
子命令啟動時都先驗證設定，並把 ingest／query 接到 rag_lab.pipeline 後格式化輸出。

關鍵設計決策：
- 結束碼：0 成功、1 執行失敗（含 eval 尚未實作）、2 命令列用法或輸入路徑錯誤、
  3 設定錯誤。
- 設定錯誤只輸出欄位名稱與原因類型，絕不輸出欄位值（可能是金鑰）。
- 設定驗證與輸入路徑檢查都在 import 重量級模組（lightrag、torch）之前完成，錯誤能立即回報。
- 執行期失敗（端點錯誤、MinerU 失敗、查詢失敗）在這裡統一轉成「型別：原例外文字」
  印到 stderr 並以 1 結束；這是 CLI 邊界的回報，不是吞掉錯誤。
- 結果（耗時、答案）印 stdout；進度與 LightRAG／RAG-Anything 的 log 在 stderr。

已知極限：eval 目前只是佔位，通過設定驗證後以 1 結束並印出「尚未實作」。

Dependencies: 標準函式庫、rag_lab.config；ingest／query 執行時才載入 rag_lab.pipeline。
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from rag_lab.config import ConfigError, get_settings

# ==============================
# 常數
# ==============================

QUERY_MODES = ("naive", "local", "global", "hybrid", "mix")

EXIT_FAILURE = 1
EXIT_USAGE = 2
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
# 子命令
# ==============================


def _collect_pdfs(raw: str) -> list[Path]:
    """把 ingest 的路徑參數展開成 PDF 清單。

    Args:
        raw: 單一 PDF 檔，或含 PDF 的資料夾（不遞迴；ASSUMPTION：第一批語料是平的資料夾）。

    Returns:
        依檔名排序的 PDF 絕對路徑。

    Raises:
        ValueError: 路徑不存在、不是 PDF、或資料夾內沒有 PDF。
    """
    path = Path(raw).expanduser().resolve()
    if path.is_dir():
        pdfs = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
        if not pdfs:
            raise ValueError(f"資料夾內沒有 PDF：{path}")
        return pdfs
    if not path.is_file():
        raise ValueError(f"路徑不存在：{path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"不是 PDF 檔：{path}")
    return [path]


def _run_ingest(raw_path: str) -> int:
    """執行 ingest 並印出各階段耗時、圖譜與 VLM 統計。"""
    try:
        pdfs = _collect_pdfs(raw_path)
    except ValueError as exc:
        print(f"輸入錯誤：{exc}", file=sys.stderr)
        return EXIT_USAGE

    from rag_lab import pipeline

    summary = pipeline.ingest(pdfs)
    for index, report in enumerate(summary.reports, start=1):
        print(f"[{index}/{len(summary.reports)}] {report.pdf.name}")
        if report.skipped:
            print(f"  已完整處理過，略過（查快取 {report.parse_seconds:.1f} s）")
            continue
        print(f"  MinerU 解析：{report.parse_seconds:.1f} s（backend={pipeline.MINERU_BACKEND}）")
        print(f"  建圖（文字切塊、實體抽取、向量）：{report.graph_seconds:.1f} s")
        print(f"  多模態（圖／表／公式描述）：{report.multimodal_seconds:.1f} s，{report.multimodal_items} 項")
    print(f"VLM 呼叫：成功 {summary.vlm_ok}，失敗 {summary.vlm_failed}")
    if summary.vlm_sample:
        print(f"VLM 圖片描述範例：{summary.vlm_sample}")
    print(
        f"圖譜：實體 {summary.entities}，關係 {summary.relations}"
        f"（其中 RAG-Anything 加的 belongs_to 邊 {summary.belongs_to}，其餘 {summary.relations - summary.belongs_to}）"
    )
    print("文件狀態：" + "，".join(f"{status}={count}" for status, count in sorted(summary.status_counts.items())))
    return 0


def _run_query(question: str, mode: str) -> int:
    """執行 query 並印出答案。"""
    from rag_lab import pipeline

    print(pipeline.query(question, mode))
    return 0


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

    if args.command == "eval":
        print("eval：尚未實作", file=sys.stderr)
        return EXIT_FAILURE
    try:
        if args.command == "ingest":
            return _run_ingest(args.path)
        return _run_query(args.question, args.mode)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
