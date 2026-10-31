"""把太大的表格縮短、再依列切成幾張小表，讓每張表送去描述與實體抽取的 prompt 都在已驗證過的大小內。

為什麼存在：RAG-Anything 把整張表放進同一個描述 prompt，也把整張表放進同一個 chunk 做實體抽取。道路救援 PDF 的一張
80 列 × 21 欄表格，MinerU 輸出 46,786 字元的 HTML，描述 prompt 達 20,731 token，mlx_lm.server 因此 GPU 記憶體不足而
停止產生（ticket 12）。全量匯入 286 份文件時，其餘文件最大的 prompt 是 7,099 token。

關鍵設計決策：
- 上限 TABLE_BODY_MAX_TOKENS = 800 token，算的是 table_body 字串本身，用 LightRAG 的 tokenizer。理由是兩個 prompt 的大小：
  - 描述 prompt = 範本 228 + 系統提示 15 + 前後文（RAG-Anything 的 max_context_tokens 預設 2000 上限）+ 表格內容，
    表格 800 時最多約 3,100 token。
  - 實體抽取 prompt = 系統提示（含範例）約 3,200 + chunk（範本 39 + 表格內容 + 描述）；有 gleaning 時再加上第一次的
    回覆與 394 token 的續問。文字 chunk 的上限是 LightRAG 預設的 1,200 token，表格 chunk 的「表格內容 + 描述」也抓在
    1,200 token：表格 800，描述約 400（ASSUMPTION：表格描述的 JSON 約 400 token，無法在不呼叫模型的情況下驗證）。
  這樣表格的實體抽取 prompt 和全量匯入時已經成功的文字 chunk 在同一個量級，不超過那次的最大值 7,099 token。
- 只動超過上限的表格。不大的表格連一個字元都不改，所以已經匯入過的文件重新處理時送去描述的內容不變。
- 縮短只拿掉值為 1 的 rowspan／colspan（HTML 的預設值），儲存格文字、合併儲存格的結構都不變。縮短後還超過上限才切。
- 切法：按列切，每張小表都重複表頭列，每張都是完整的 `<table>`。表頭是第一列，若第一列有 rowspan 跨到後面的列，
  就是被它跨到的那幾列（ASSUMPTION：表格第一列是表頭）。貪婪裝填：一張小表塞到再加一列就超過上限為止，每次都用
  完整字串重新計算 token。被 rowspan 連在一起的列盡量留在同一張小表：超過上限時退回到最近的一組列的起點再切。
- 一組列單獨就超過上限時才從中間切開（道路救援那張表的第 24 列有一個空儲存格 rowspan=57，跨到表尾，MinerU 辨識表格的
  結果）。切開處跨過來的儲存格，在下一張小表的第一列補一份（文字相同、rowspan 縮到剩下的列數），欄位位置維持對齊。
- 每張小表是 content list 裡獨立的一個 table 項目，複製原項目的其他欄位，table_caption 多加一句說明這是第幾張、共幾張。
  RAG-Anything 因此對每張小表各做一次描述、各建一個 chunk 與實體。

已知極限：
- 只處理 HTML 的 table_body（MinerU 的格式）。沒有 `<tr>` 的內容（例如 Markdown 或二維陣列）不縮短也不切。
- 表頭本身，或單獨一列，就超過上限時沒辦法再拆：那張小表會超過上限。
- 儲存格內再放表格的巢狀 `<table>` 不處理（以 `</tr>` 為列的結尾）。
- 切開處補的跨列儲存格，會讓那段文字在兩張小表各出現一次（只有一組列單獨超過上限時才會發生）。

Dependencies: 僅標準函式庫。
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# ==============================
# 常數
# ==============================

# table_body 的 token 上限；理由見模組 docstring
TABLE_BODY_MAX_TOKENS = 800

_ROW = re.compile(r"<tr\b[^>]*>.*?</tr\s*>", re.IGNORECASE | re.DOTALL)
_CELL = re.compile(r"(<t[dh]\b[^>]*>)(.*?)(</t[dh]\s*>)", re.IGNORECASE | re.DOTALL)
_CELL_TAG = re.compile(r"<t[dh]\b[^>]*>", re.IGNORECASE)
_ROWSPAN = re.compile(r"(\browspan\s*=\s*[\"']?)(\d+)", re.IGNORECASE)
_COLSPAN = re.compile(r"\bcolspan\s*=\s*[\"']?(\d+)", re.IGNORECASE)
# 值為 1 的 rowspan／colspan（有無引號皆可）；後面要接空白、`/` 或 `>`，才不會把 rowspan=12 的 1 當成預設值
_DEFAULT_SPAN = re.compile(r"\s+(?:rowspan|colspan)\s*=\s*(?:\"1\"|'1'|1)(?=[\s/>])", re.IGNORECASE)

# ==============================
# 縮短
# ==============================


def shorten_table_html(html: str) -> str:
    """拿掉儲存格標籤上值為 1 的 rowspan／colspan，其餘內容原樣保留。

    Args:
        html: table_body 的 HTML。

    Returns:
        縮短後的 HTML；儲存格文字與合併儲存格（值大於 1 的 rowspan／colspan）都不變。
    """
    return _CELL_TAG.sub(lambda tag: _DEFAULT_SPAN.sub("", tag.group(0)), html)


# ==============================
# 切分
# ==============================


@dataclass(frozen=True)
class _Cell:
    """表格的一個儲存格。

    Attributes:
        row: 起始列（從 0 起算）。
        col: 起始欄（從 0 起算，已把上方 rowspan 佔掉的欄位算進去）。
        rowspan: 跨幾列。
        colspan: 跨幾欄。
        open_tag: 開頭標籤（含屬性）。
        text: 儲存格內容（標籤之間的原文）。
        close_tag: 結尾標籤。
    """

    row: int
    col: int
    rowspan: int
    colspan: int
    open_tag: str
    text: str
    close_tag: str

    @property
    def last_row(self) -> int:
        """Returns: 這個儲存格跨到的最後一列。"""
        return self.row + self.rowspan - 1

    def html(self, first: int, last: int) -> str:
        """輸出這個儲存格；rowspan 依小表涵蓋的列縮短。

        Args:
            first: 小表的第一列（原表的列號）；儲存格從更早的列跨過來時，從這一列起算。
            last: 小表的最後一列（原表的列號）。

        Returns:
            儲存格的 HTML；rowspan 變成 1 時拿掉預設值屬性。
        """
        rowspan = min(self.last_row, last) - max(self.row, first) + 1
        if rowspan == self.rowspan:
            return self.open_tag + self.text + self.close_tag
        open_tag = _ROWSPAN.sub(lambda match: f"{match.group(1)}{rowspan}", self.open_tag, count=1)
        return _DEFAULT_SPAN.sub("", open_tag) + self.text + self.close_tag


def _parse_rows(html: str) -> list[list[_Cell]]:
    """把 HTML 表格讀成每列的儲存格，算出每個儲存格實際落在第幾欄（上方 rowspan 佔掉的欄位要跳過）。

    Args:
        html: table_body 的 HTML。

    Returns:
        每列一個依欄位排序的儲存格清單；沒有 `<tr>` 時為空清單。
    """
    rows: list[list[_Cell]] = []
    occupied: dict[int, int] = {}  # 欄 -> 這一欄被上方的 rowspan 佔到的最後一列
    for row_index, row_html in enumerate(_ROW.findall(html)):
        cells: list[_Cell] = []
        col = 0
        for open_tag, text, close_tag in _CELL.findall(row_html):
            while occupied.get(col, -1) >= row_index:
                col += 1
            rowspan = _ROWSPAN.search(open_tag)
            colspan = _COLSPAN.search(open_tag)
            cell = _Cell(
                row=row_index,
                col=col,
                rowspan=int(rowspan.group(2)) if rowspan else 1,
                colspan=int(colspan.group(1)) if colspan else 1,
                open_tag=open_tag,
                text=text,
                close_tag=close_tag,
            )
            for covered in range(cell.col, cell.col + cell.colspan):
                occupied[covered] = max(occupied.get(covered, -1), cell.last_row)
            cells.append(cell)
            col += cell.colspan
        rows.append(cells)
    return rows


def _render(rows: list[list[_Cell]], header_height: int, first: int, last: int, carried: list[_Cell]) -> str:
    """組出一張小表：表頭列加上原表的第 first 到 last 列。

    Args:
        rows: 原表每列的儲存格。
        header_height: 表頭佔幾列（rows 的前幾列）。
        first: 小表第一個資料列（原表的列號）。
        last: 小表最後一個資料列（原表的列號）。
        carried: 從 first 之前的列跨到 first 的儲存格；在第 first 列補一份，欄位位置才對得上。

    Returns:
        完整的 `<table>`。
    """
    html = ["<table>"]
    for index in range(header_height):
        html.append("<tr>" + "".join(cell.html(0, header_height - 1) for cell in rows[index]) + "</tr>")
    for index in range(first, last + 1):
        cells = sorted(rows[index] + carried, key=lambda cell: cell.col) if index == first else rows[index]
        html.append("<tr>" + "".join(cell.html(first, last) for cell in cells) + "</tr>")
    html.append("</table>")
    return "".join(html)


def split_table_html(html: str, count_tokens: Callable[[str], int], max_tokens: int) -> list[str]:
    """把表格依列切成幾張小表，每張都重複表頭列，盡量塞到不超過 max_tokens。

    被 rowspan 連在一起的列盡量留在同一張小表；只有一組列單獨就超過上限時才從中間切開，切開處跨過來的儲存格
    在下一張小表的第一列補一份（文字相同、rowspan 縮到剩下的列數），欄位位置維持對齊。

    Args:
        html: table_body 的 HTML（通常是縮短後的）。
        count_tokens: 計算字串 token 數的函式。
        max_tokens: 每張小表的 token 上限。

    Returns:
        小表的 HTML 清單，原表的每一列都在某一張小表裡。內容沒有 `<tr>`、只有表頭、或本來就不超過上限時，
        回傳只含原 HTML 的清單。
    """
    rows = _parse_rows(html)
    if len(rows) < 2 or count_tokens(html) <= max_tokens:
        return [html]
    # 表頭：第一列，以及第一列的 rowspan 跨到的列（ASSUMPTION：表格第一列是表頭）
    header_height = min(max((cell.last_row for cell in rows[0]), default=0) + 1, len(rows))
    # 一組列的起點：前面沒有 rowspan 跨到這一列
    starts: list[int] = []
    reach = header_height - 1
    for index in range(header_height, len(rows)):
        if index > reach:
            starts.append(index)
        reach = max([reach, index, *(cell.last_row for cell in rows[index])])

    parts: list[str] = []
    first = header_height
    while first < len(rows):
        carried = [cell for earlier in rows[header_height:first] for cell in earlier if cell.last_row >= first]
        last = first
        while last + 1 < len(rows) and count_tokens(_render(rows, header_height, first, last + 1, carried)) <= max_tokens:
            last += 1
        if last + 1 < len(rows) and last + 1 not in starts:
            boundaries = [start for start in starts if first < start <= last]
            if boundaries:
                last = boundaries[-1] - 1
        parts.append(_render(rows, header_height, first, last, carried))
        first = last + 1
    return parts


# ==============================
# content list
# ==============================


def limit_table_sizes(
    content_list: list[dict[str, Any]], count_tokens: Callable[[str], int], max_tokens: int = TABLE_BODY_MAX_TOKENS
) -> list[dict[str, Any]]:
    """把 content list 裡太大的表格縮短，仍太大就切成多個 table 項目；其他項目原樣保留。

    不修改傳入的 content_list 與其中的項目（解析快取裡存的就是這份）。

    Args:
        content_list: MinerU 格式的 content list。
        count_tokens: 計算字串 token 數的函式。
        max_tokens: 每個表格 table_body 的 token 上限。

    Returns:
        新的 content list。table_body 不超過上限的項目是原物件；超過的被縮短後的項目，或依列切出來的幾個項目取代。
    """
    result: list[dict[str, Any]] = []
    for item in content_list:
        body = item.get("table_body") if item.get("type") == "table" else None
        if not isinstance(body, str) or count_tokens(body) <= max_tokens:
            result.append(item)
            continue
        parts = split_table_html(shorten_table_html(body), count_tokens, max_tokens)
        captions = item.get("table_caption") or []
        captions = [captions] if isinstance(captions, str) else list(captions)
        for number, part in enumerate(parts, start=1):
            piece = {**item, "table_body": part}
            if len(parts) > 1:
                piece["table_caption"] = captions + [
                    f"（原表依列切成 {len(parts)} 張小表，這是第 {number} 張；每張都重複表頭列）"
                ]
            result.append(piece)
    return result
