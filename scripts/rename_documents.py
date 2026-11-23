"""把台新知識庫的文件改成帶卡片標籤的檔名，並產生 rag_lab 用的標頭檔。

為什麼存在：重匯要讓每份文件的檔名與每個 chunk 的標頭都帶卡片標籤（spec「改檔名」「chunk 標頭與依標題切塊」）。
這支腳本是一次性遷移，也是 fetch_taishin.py 每次下載結束時補新文件檔名的同一段程式（migrate），
所以新下載的文件和遷移的文件用同一套規則（label_cards.py，含人工標籤檔）。

用法：
    python3 scripts/rename_documents.py --dry-run [--data-dir DIR] [--questions FILE] [--manual FILE]
    python3 scripts/rename_documents.py --backup-dir DIR [--data-dir DIR] [--questions FILE] [--manual FILE]
    預設讀 data/taishin_credit_card、eval/questions.taishin.jsonl 與 scripts/label_cards_manual.json。
    --dry-run 只列出會改哪些檔、manifest 筆數、eval 題目，不改任何檔案。
    實際執行一定要給 --backup-dir：改之前把 manifest、eval 題目檔、標籤檔與標頭檔（有的話）複製進去。

做的事（依序）：
1. 標籤：讀 DIR/_meta/document_labels.json（使用者抽查過的標籤）；檔裡沒有的文件，用 label_cards.label_data_dir 現算
   （含人工標籤檔）並補進標籤檔。人工標籤檔裡路徑不在這個資料夾的項目不報錯，只列出來（fetch 時資料夾常常只有一部分文件）。
2. 改名：有標籤（needs_review 為 false）的文件改成 <卡別>_<簡短卡名>_<原檔名>（label_cards.labelled_filename），
   manifest 的 filename 同步改，沒有實體檔的紀錄也照改。沒有標籤的（待人工確認、或 manifest 有紀錄但沒有實體檔而標籤檔沒有它）
   保留原檔名並列出。
3. eval 題目：source 欄裡出現的原檔名換成新檔名（含逗號分隔的多個來源與自由文字裡提到的檔名）；其他欄位與沒變的行原樣保留。
4. 標頭檔：DIR/_meta/document_headers.json，key 是新檔名、值是標頭文字；沒有標籤的文件不在裡面。
改名之前先檢查：兩份文件的新檔名相同、新檔名在資料夾裡已有檔案、卡別或簡短卡名含不安全字元，任何一項成立就整個中止，什麼都不改。

關鍵設計決策：
- 可以重跑：已經是新檔名的不再改。eval 題目與標頭檔每次都由 manifest 目前的檔名推出「原檔名到現在檔名」的對照，
  所以上次做到一半中斷（檔案改了、題目還沒改）重跑會補完。檔案已改成新檔名、manifest 還寫原檔名時（改檔名與寫 manifest 之間中斷），
  label_cards.read_docs 認得資料夾裡改過名的檔案，重跑以資料夾裡的檔名更新 manifest，並補回標籤檔與標頭檔。
- 頁面快照（_meta/html、_meta/print）、標籤檔與人工標籤檔仍然用原檔名當 key，所以不改快照檔名；
  fetch_taishin.py 的快照名稱本來就由網址決定，不依賴文件檔名。
- 已經有新檔名的文件不重新評估標籤：標籤之後變了要改名，由使用者手動處理（檔名穩定比跟著標籤變動重要）。

已知極限：
- 磁碟上有、但 manifest 沒有紀錄的檔案（fetch 某個類別的列表失敗時，那個類別這次沒有 manifest 紀錄）不改名、不現算標籤；
  標籤檔已有可用標籤的會留在標頭檔裡。卡片頁資料夾有這樣的檔案時，卡名清單不完整，這次不現算任何新標籤，缺標籤的文件下次再試。
- 待人工確認的文件每次都會重新現算（label_data_dir 一次算整個資料夾，約 1.5 秒）：標籤檔不記錄待人工確認的結果，
  官網新增卡片頁後它們才有機會比對到卡名。沒有文件缺標籤時不會重算。
- 標籤檔裡有條目但 needs_review 仍是 true 的文件，要使用者先改標籤檔才會改名。

Dependencies: label_cards（同資料夾；它用 tiktoken，LightRAG 已依賴，不是新增依賴）。
"""

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import label_cards  # noqa: E402
from rag_lab.formats import NOT_A_DOCUMENT_PREFIXES  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVAL_FILE = REPO_ROOT / "eval" / "questions.taishin.jsonl"
LABELS_NAME = "document_labels.json"
HEADERS_NAME = "document_headers.json"


@dataclass
class Report:
    """一次遷移（或 dry-run）的結果。

    Attributes:
        renamed: 要改名的實體檔：原檔名路徑（資料夾／原檔名）對新檔名。
        manifest_rows: manifest 裡要改 filename 的筆數（含沒有實體檔的紀錄）。
        kept: 保留原檔名的 manifest 紀錄：（原檔名路徑，原因）。
        eval_changes: 有改 source 的題目：id 對（舊 source，新 source）。
        headers: 標頭檔的筆數。
        labels_added: 補進標籤檔的筆數。
        unused_manual: 人工標籤檔裡、路徑不在這個資料夾的項目。
    """

    renamed: dict[str, str] = field(default_factory=dict)
    manifest_rows: int = 0
    kept: list[tuple[str, str]] = field(default_factory=list)
    eval_changes: dict[str, tuple[str, str]] = field(default_factory=dict)
    headers: int = 0
    labels_added: int = 0
    unused_manual: list[str] = field(default_factory=list)


# ==============================
# 標籤
# ==============================


def read_labels_file(data_dir: Path) -> dict[str, dict]:
    """標籤檔（DIR/_meta/document_labels.json）的內容。

    Args:
        data_dir: 資料根目錄。

    Returns:
        文件原檔名路徑對標籤紀錄；檔案不存在時為空字典。
    """
    path = data_dir / "_meta" / LABELS_NAME
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def unlisted_files(data_dir: Path, docs: list[label_cards.Doc]) -> dict[str, str]:
    """類別資料夾裡有檔案、但 manifest 沒有紀錄的文件（fetch 某個類別的列表失敗時，那個類別這次沒有 manifest 紀錄）。

    Args:
        data_dir: 資料根目錄。
        docs: manifest 裡有實體檔的文件（label_cards.read_docs）。

    Returns:
        原檔名路徑對現在的檔名；隱藏檔與 Office 鎖定檔（NOT_A_DOCUMENT_PREFIXES）不算；
        原檔名路徑和 manifest 裡某份文件相同的檔案（同一份文件的另一個檔名）也不算。
    """
    listed = {doc.path for doc in docs}
    unlisted: dict[str, str] = {}
    for folder in sorted(set(label_cards.CATEGORY_FOLDERS.values())):
        if not (data_dir / folder).is_dir():
            continue
        for file in sorted((data_dir / folder).iterdir()):
            path = f"{folder}/{label_cards.original_filename(file.name)}"
            if file.is_file() and not file.name.startswith(NOT_A_DOCUMENT_PREFIXES) and path not in listed:
                unlisted[path] = file.name
    return unlisted


def resolve_labels(data_dir: Path, manual: dict[str, dict]) -> tuple[dict[str, dict], dict[str, dict], list[str]]:
    """每份有實體檔的文件的標籤：標籤檔優先，檔裡沒有的現算。

    ASSUMPTION：現算要用全部卡片頁建卡名清單。卡片頁資料夾（cards、debit_cards）裡有檔案不在 manifest（fetch 那個類別失敗）時，
    清單不完整，這次不現算新標籤（缺標籤的文件保留原檔名，下次 fetch 再試），免得用殘缺的清單算出錯的「全部」或漏掉的卡。
    label_data_dir 一次算整個資料夾（卡名清單與連結頁面都要看全部文件），所以沒有「只算缺的」；
    沒有文件缺標籤時不呼叫它。

    Args:
        data_dir: 資料根目錄。
        manual: 人工標籤（文件原檔名路徑對 {kind, cards, decision}）。

    Returns:
        (全部標籤, 這次現算、而且能用（不是待人工確認）而要補進標籤檔的標籤, 人工標籤檔裡路徑不在這個資料夾的項目)。
        待人工確認的現算結果不寫進標籤檔，每次重算：標籤檔是「下游可以用的標籤」，待確認的留給 label_cards.py 的抽查報告。

    Raises:
        ValueError: 人工標籤格式不合法（見 label_cards.make_manual_label）。
    """
    docs = label_cards.read_docs(data_dir)
    labels = read_labels_file(data_dir)
    present = {doc.path for doc in docs}
    unused = sorted(set(manual) - present)
    card_page_folders = {label_cards.CATEGORY_FOLDERS[category] for category in label_cards.CARD_PAGE_KINDS}
    card_pages_incomplete = any(path.split("/")[0] in card_page_folders for path in unlisted_files(data_dir, docs))
    missing = [doc.path for doc in docs if doc.path not in labels]
    if not missing or card_pages_incomplete:
        return labels, {}, unused
    computed = label_cards.label_data_dir(data_dir, {path: entry for path, entry in manual.items() if path in present})
    added = {path: computed[path] for path in missing if usable(computed[path])}
    return {**labels, **{path: computed[path] for path in missing}}, added, unused


# ==============================
# 計畫
# ==============================


def usable(label: dict | None) -> bool:
    """標籤能不能用來改檔名與產生標頭。

    Args:
        label: 標籤紀錄；沒有時是 None。

    Returns:
        有標籤而且不是待人工確認時為 True。
    """
    return label is not None and not label["needs_review"]


def plan_names(
    data_dir: Path, rows: list[dict], labels: dict[str, dict]
) -> tuple[dict[int, str], dict[str, str], list[tuple[str, str]], dict[str, str]]:
    """逐筆 manifest 紀錄決定新檔名。

    Args:
        data_dir: 資料根目錄。
        rows: manifest 的紀錄。
        labels: 全部標籤。

    Returns:
        (列號對新檔名（要改 filename 的列）, 要改名的實體檔（原檔名路徑對新檔名）, 保留原檔名的（路徑，原因）,
        原檔名對現在檔名（已經是新檔名的與這次要改的都在裡面，題目改寫用）)。

    Raises:
        ValueError: 卡別或簡短卡名含不安全字元（見 label_cards.labelled_filename）。
    """
    row_names: dict[int, str] = {}
    files: dict[str, str] = {}
    kept: list[tuple[str, str]] = []
    current: dict[str, str] = {}
    on_disk = {doc.path: doc.filename for doc in label_cards.read_docs(data_dir)}
    for index, row in enumerate(rows):
        folder = label_cards.CATEGORY_FOLDERS[row["category"]]
        filename = row["filename"]
        original = label_cards.original_filename(filename)
        path = f"{folder}/{original}"
        if original != filename:
            current[original] = filename
            continue
        if on_disk.get(path, filename) != filename:
            # 上次改名做到一半中斷：檔案已經是新檔名、manifest 還沒跟上。以資料夾裡的檔名為準，不重新評估標籤
            row_names[index] = current[original] = on_disk[path]
            continue
        label = labels.get(path)
        if not usable(label):
            reason = "標籤檔沒有它（沒有實體檔，或卡片頁不完整而這次沒有現算）" if label is None else f"待人工確認：{label['reason']}"
            kept.append((path, reason))
            continue
        new = label_cards.labelled_filename(label, original)
        row_names[index] = new
        current[original] = new
        if (data_dir / folder / filename).is_file():
            files[path] = new
    return row_names, files, kept, current


def build_headers(data_dir: Path, labels: dict[str, dict], files: dict[str, str]) -> dict[str, str]:
    """標頭檔內容：新檔名對標頭文字。

    ASSUMPTION：資料夾裡有檔案、但 manifest 沒有紀錄的文件（fetch 某個類別失敗），只要標籤檔已有可用的標籤就留在標頭檔裡，
    用它現在的檔名；它們這次不改名、不現算標籤。

    Args:
        data_dir: 資料根目錄。
        labels: 全部標籤。
        files: 這次要改名的實體檔（原檔名路徑對新檔名）。

    Returns:
        依檔名排序的字典；沒有標籤的文件不在裡面。

    Raises:
        ValueError: 兩份文件的新檔名相同，或要改成的新檔名在資料夾裡已有檔案。
    """
    docs = label_cards.read_docs(data_dir)
    entries = [(doc.path, doc.filename, files.get(doc.path, doc.filename)) for doc in docs]
    entries += [(path, name, name) for path, name in unlisted_files(data_dir, docs).items()]
    headers: dict[str, str] = {}
    owners: dict[str, str] = {}
    for path, filename, name in entries:
        label = labels.get(path)
        if not usable(label):
            continue
        if name in owners:
            raise ValueError(f"{owners[name]} 與 {path} 的新檔名相同（同一個新檔名：{name}），標頭檔的 key 會撞")
        folder = path.split("/")[0]
        if name != filename and (data_dir / folder / name).exists():
            raise ValueError(f"{folder}/{name} 已經有檔案，不能把 {path} 改成這個名字")
        owners[name] = path
        headers[name] = label["header"]
    return dict(sorted(headers.items()))


def rewrite_sources(lines: list[str], current: dict[str, str]) -> tuple[list[str], dict[str, tuple[str, str]]]:
    """eval 題目的 source 欄：原檔名換成現在的檔名。

    只換獨立的檔名：前後不能緊連字母、數字、底線、連字號（「x」加原檔名、新檔名裡的原檔名都不換）。
    沒變的行與其他欄位原樣保留。

    Args:
        lines: 題目檔的各行（含換行）。
        current: 原檔名對現在檔名。

    Returns:
        (新的各行, 有改的題目：id 對（舊 source，新 source）)。
    """
    if not current:
        return lines, {}
    names = "|".join(re.escape(name) for name in sorted(current, key=len, reverse=True))
    pattern = re.compile(rf"(?<![\w.\-])(?:{names})(?![\w\-])")
    out: list[str] = []
    changes: dict[str, tuple[str, str]] = {}
    for line in lines:
        if not line.strip():
            out.append(line)
            continue
        row = json.loads(line)
        new = pattern.sub(lambda match: current[match.group(0)], row["source"])
        if new == row["source"]:
            out.append(line)
            continue
        changes[row["id"]] = (row["source"], new)
        ending = line[len(line.rstrip("\r\n")) :]
        out.append(json.dumps({**row, "source": new}, ensure_ascii=False) + ending)
    return out, changes


# ==============================
# 遷移
# ==============================


def write_json(path: Path, value: dict) -> None:
    """寫 JSON 檔（縮排 2、保留中文、結尾換行）；內容沒變就不寫，保留修改時間。

    Args:
        path: 檔案路徑。
        value: 要寫的字典。
    """
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")


def migrate(
    data_dir: Path,
    manual: dict[str, dict] | None = None,
    eval_file: Path | None = None,
    backup_dir: Path | None = None,
    dry_run: bool = False,
) -> Report:
    """把有標籤的文件改成新檔名，同步改 manifest 與 eval 題目，並產生標頭檔。

    Args:
        data_dir: 資料根目錄（含 _meta/manifest.jsonl 與各類別資料夾）。
        manual: 人工標籤；None 表示沒有。
        eval_file: eval 題目檔；None 表示不改題目。
        backup_dir: 有任何改動時，先把 manifest、題目檔、標籤檔與標頭檔（有的話）複製到這個資料夾；None 表示不備份。
        dry_run: True 時只算出報告，不改任何檔案（也不建立備份）。

    Returns:
        這次的報告（dry_run 時是「如果執行會怎樣」）。

    Raises:
        ValueError: 新檔名不安全、重複或已被佔用，或人工標籤格式不合法；發生時沒有改任何檔案。
    """
    meta = data_dir / "_meta"
    manifest_path = meta / "manifest.jsonl"
    raw_lines = manifest_path.read_text(encoding="utf-8").splitlines(keepends=True)
    rows = [json.loads(line) for line in raw_lines]
    labels, added, unused = resolve_labels(data_dir, manual or {})
    row_names, files, kept, current = plan_names(data_dir, rows, labels)
    headers = build_headers(data_dir, labels, files)
    eval_lines = eval_file.read_text(encoding="utf-8").splitlines(keepends=True) if eval_file else []
    new_eval_lines, eval_changes = rewrite_sources(eval_lines, {o: n for o, n in current.items() if o != n})
    report = Report(files, len(row_names), kept, eval_changes, len(headers), len(added), unused)
    if dry_run:
        return report

    if backup_dir is not None and (files or row_names or eval_changes):
        backup_dir.mkdir(parents=True, exist_ok=False)
        for source in (manifest_path, eval_file, meta / LABELS_NAME, meta / HEADERS_NAME):
            if source is not None and source.is_file():
                shutil.copy2(source, backup_dir / source.name)
    for path, new in files.items():
        folder, filename = path.split("/", 1)
        (data_dir / folder / filename).rename(data_dir / folder / new)
    if row_names:
        manifest_path.write_text(
            "".join(
                json.dumps({**row, "filename": row_names[index]}, ensure_ascii=False) + "\n" if index in row_names else raw_lines[index]
                for index, row in enumerate(rows)
            ),
            encoding="utf-8",
        )
    if eval_changes and eval_file is not None:
        eval_file.write_text("".join(new_eval_lines), encoding="utf-8")
    if added:
        write_json(meta / LABELS_NAME, {**read_labels_file(data_dir), **added})
    if headers or (meta / HEADERS_NAME).is_file():
        write_json(meta / HEADERS_NAME, headers)
    return report


# ==============================
# 命令列
# ==============================


def format_report(report: Report, dry_run: bool) -> str:
    """報告轉成給人看的文字。

    Args:
        report: migrate 的結果。
        dry_run: 是不是 dry-run（決定開頭那一行）。

    Returns:
        多行文字。
    """
    lines = ["dry-run：只列出會做的事，沒有改任何檔案" if dry_run else "已完成"]
    lines.append(f"改名 {len(report.renamed)} 份（manifest {report.manifest_rows} 筆）")
    lines.extend(f"  {path} -> {new}" for path, new in sorted(report.renamed.items()))
    lines.append(f"保留原檔名 {len(report.kept)} 份（沒有可用的標籤）")
    lines.extend(f"  {path}：{reason}" for path, reason in sorted(report.kept))
    changed = "、".join(report.eval_changes)
    lines.append(f"eval 題目 {len(report.eval_changes)} 題{'：' + changed if changed else ''}")
    lines.extend(f"  {qid}：{old} -> {new}" for qid, (old, new) in report.eval_changes.items())
    lines.append(f"標頭檔 {report.headers} 筆；補進標籤檔 {report.labels_added} 筆")
    if report.unused_manual:
        lines.append(f"人工標籤檔有 {len(report.unused_manual)} 筆路徑不在這個資料夾：{'、'.join(report.unused_manual)}")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析命令列參數；沒有 --dry-run 又沒給 --backup-dir 時結束並說明。

    Args:
        argv: 不含程式名稱的參數。

    Returns:
        解析結果：data_dir、questions、manual、backup_dir、dry_run。
    """
    parser = argparse.ArgumentParser(description="把台新知識庫的文件改成帶卡片標籤的檔名，並產生標頭檔。")
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data" / "taishin_credit_card", help="資料根目錄")
    parser.add_argument("--questions", type=Path, default=DEFAULT_EVAL_FILE, help="eval 題目檔（source 欄會改）")
    parser.add_argument("--manual", type=Path, default=label_cards.MANUAL_LABELS_PATH, help="人工標籤檔")
    parser.add_argument("--backup-dir", type=Path, help="備份資料夾（必須不存在）；實際執行時必填")
    parser.add_argument("--dry-run", action="store_true", help="只列出會改什麼，不改任何檔案")
    args = parser.parse_args(argv)
    if not args.dry_run and args.backup_dir is None:
        parser.error("實際執行必須給 --backup-dir（改之前備份 manifest 與題目檔）；只想看會改什麼請用 --dry-run")
    return args


def main(argv: list[str]) -> int:
    """執行遷移並印出報告。

    Args:
        argv: 不含程式名稱的命令列參數。

    Returns:
        結束碼，0 表示成功。
    """
    args = parse_args(argv)
    manual = json.loads(args.manual.read_text(encoding="utf-8"))
    report = migrate(args.data_dir, manual, args.questions, args.backup_dir, args.dry_run)
    print(format_report(report, args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
