"""依標題切塊的 LightRAG chunking_func，以及把 content list 改寫成它吃得進去的格式。

為什麼存在：台新知識庫有幾百份文件，同一個卡片名稱的內容分散在不同文件。LightRAG 預設的 chunker 只依 token 數
切，chunk 不知道自己屬於哪張卡、哪一節，檢索常撈到別張卡的文件。這裡讓每個 chunk 開頭帶「卡片標籤＋章節名稱」，
並在標題處切開。

關鍵設計決策：
- LightRAG 呼叫 chunking_func 時只傳文件內容，不傳檔名，所以標頭由 LabRAGAnything.parse_document 以固定標記區塊放在
  文件內容最前面（rewrite_content_list），chunker 再從內容讀出來。標記區塊：
  `<<<RAG_LAB_HEADER`、標頭文字、`RAG_LAB_HEADER>>>` 各占一行（ASSUMPTION：格式由 ticket 04 自訂；一般文件不會出現這兩個字串）。
  內容沒有這個區塊就拋 ValueError：這個 chunker 只在有設 DOCUMENT_HEADERS_FILE 時使用，那時每份文件都應該有。
- 標題是 `#` 到 `######` 開頭的行（parse_document 把 content list 裡有 text_level 的文字項目改成這個格式）。每個標題
  開一節，標題前的文字是沒有名稱的一節。章節名稱只用最近那一個標題的文字，不串上層標題（ASSUMPTION：現有文件只有一層標題）。
- 節的 token 數 = 標題行加內文。少於 SHORT_SECTION_TOKENS（100）的節併進下一節，累積到 100 以上才成一組；最後一組還不到
  100 時併進前一組。同一組在標頭下列出所有章節名稱（「章節：甲、乙」），組內第二節起保留標題行，讓內文看得出哪段屬於哪節。
- chunk_token_size 限制整個 chunk（標頭＋章節行＋內文），不只內文：實體抽取的 prompt 大小看整個 chunk。組超過時在組內依 token
  切內文，每段與前一段重疊 chunk_overlap_token_size（ASSUMPTION：spec 的「一節超過 1,200 token」解讀成整個 chunk 的上限）。
- 標頭超過 HEADER_MAX_TOKENS（150）時，整份文件的第一個 chunk 放完整標頭，其餘 chunk 改成短標頭。
  標頭格式是 ticket 01 產生的 `卡別：<卡別>｜適用卡片：<卡名>／<卡名>…`（卡別可以是「信用卡及金融卡」，「全部信用卡」是清單裡的
  一個項目）；短標頭保留「卡別：…」，適用卡片換成「共 N 張卡」（short_header），N 是以全形「／」分隔的項目數。短標頭本身符合
  同一個格式，不宣稱文件裡有清單：scripts/label_cards.py 也用它產生標籤檔的標頭（那份文件裡沒有完整清單）。格式不符時
  不猜，parse_header 拋 ValueError；chunker、rewrite_content_list 與 config 載入標頭檔時都會檢查。
- 文件沒有任何非空白的文字項目（純圖片、純表格）時，rewrite_content_list 不放標頭區塊：放了的話 RAG-Anything 會把只有標頭的
  文字插進 LightRAG，產生 0 個內容 chunk，偏離它原本只走多模態的路徑；這類文件的卡片標籤只靠 caption。
- 表格與圖片不經過 chunking_func（RAG-Anything 另外做成 chunk），所以 rewrite_content_list 把標頭加進它們的 caption。

已知極限：
- 自訂 chunking_func 之後 RAG-Anything 不再替文字 chunk 標頁碼（page_idx）；rag_lab 目前沒有用到頁碼。
- 依 token 切內文時，切點可能落在多位元組字元中間，解碼出替代字元；LightRAG 預設的 chunker 也是這樣。
- 文字項目裡以 `#` 加空白開頭的行會被當成標題。
- split_by_character 與 split_by_character_only 參數不支援（LightRAG 的簽名要求有，rag_lab 沒有使用）。

Dependencies: 僅標準函式庫。
"""

import re
from collections.abc import Callable
from typing import Any

# ==============================
# 常數
# ==============================

HEADER_START = "<<<RAG_LAB_HEADER"
HEADER_END = "RAG_LAB_HEADER>>>"

# 少於這個 token 數的節併進下一節（使用者 2026-11-19 選 (c)）
SHORT_SECTION_TOKENS = 100
# 標頭超過這個 token 數時，除了第一個 chunk 以外改寫成短標頭
HEADER_MAX_TOKENS = 150
# 圖片與表格 caption 開頭的標籤
CAPTION_LABEL = "卡片標籤："

_HEADER_BLOCK = re.compile(
    rf"\A{re.escape(HEADER_START)}\n(.*?)\n{re.escape(HEADER_END)}[ \t\r\n]*", re.DOTALL
)
_HEADING_LINE = re.compile(r"^(#{1,6}) +(\S.*)$")
_HEADER_FORMAT = re.compile(r"\A卡別：([^｜\n]*)｜適用卡片：([^｜\n]*)\Z")

# ==============================
# 標頭
# ==============================


def wrap_header(header: str) -> str:
    """把標頭文字包成固定的標記區塊。

    Args:
        header: 標頭文字，不可包含標記字串。

    Returns:
        標記區塊字串。
    """
    return f"{HEADER_START}\n{header}\n{HEADER_END}"


def parse_header(header: str) -> tuple[str, list[str]]:
    """解析「卡別：<卡別>｜適用卡片：<卡名>／<卡名>…」。

    Args:
        header: 標頭文字（單行）。

    Returns:
        (卡別, 適用卡片清單)，前後空白已去掉。

    Raises:
        ValueError: 格式不符、卡別為空，或清單有空項目。訊息不含標頭內容（標頭是使用者資料）。
    """
    match = _HEADER_FORMAT.match(header)
    if match is not None:
        kind = match.group(1).strip()
        cards = [card.strip() for card in match.group(2).split("／")]
        if kind and all(cards):
            return kind, cards
    raise ValueError("標頭格式必須是「卡別：<卡別>｜適用卡片：<卡名>／<卡名>…」（單行；卡別與每個卡名都不可為空）")


def short_header(kind: str, count: int) -> str:
    """組出短標頭「卡別：<卡別>｜適用卡片：共 N 張卡」（格式仍符合 parse_header，文字不宣稱文件裡有清單）。

    Args:
        kind: 卡別。
        count: 適用的實際張數。

    Returns:
        短標頭。
    """
    return f"卡別：{kind}｜適用卡片：共 {count} 張卡"


def shorten_header(header: str) -> str:
    """把「卡別：<卡別>｜適用卡片：<清單>」改寫成「卡別：<卡別>｜適用卡片：共 N 張卡」，N 是清單的項目數。

    Args:
        header: 完整標頭。

    Returns:
        短標頭（見 short_header）。

    Raises:
        ValueError: 標頭格式不符（見 parse_header）。
    """
    kind, cards = parse_header(header)
    return short_header(kind, len(cards))


# ==============================
# content list 改寫
# ==============================


def _with_caption_label(captions: Any, label: str) -> list[str]:
    """把卡片標籤放在 caption 清單最前面，原有的 caption 保留在後面。

    Args:
        captions: MinerU 的 caption 欄位，可以是字串、字串清單或 None。
        label: 卡片標籤文字（含「卡片標籤：」前綴）。

    Returns:
        新的 caption 清單：標籤在最前面，接著原有的 caption。
    """
    existing = [captions] if isinstance(captions, str) else list(captions or [])
    return [label, *existing]


def rewrite_content_list(
    content_list: list[dict[str, Any]], header: str, count_tokens: Callable[[str], int]
) -> list[dict[str, Any]]:
    """把 MinerU 的 content list 改寫成 chunk_by_headings 吃得進去的格式。

    做三件事：最前面放標頭標記區塊（文件沒有任何文字項目時不放：純圖片或純表格的文件靠 caption 的卡片標籤，
    且不放標頭才不會讓 RAG-Anything 把只有標頭的文字送進 LightRAG、改變它原本的多模態路徑）；有 text_level 的文字項目改成 markdown 標題（`#` 數量等於層級，最多 6）；
    表格與圖片的 caption 開頭加卡片標籤（標頭超過 HEADER_MAX_TOKENS 時用短標頭）。不修改傳入的 list 與其中的項目。

    Args:
        content_list: MinerU 格式的 content list。
        header: 這份文件的標頭文字。
        count_tokens: 計算字串 token 數的函式。

    Returns:
        新的 content list。

    Raises:
        ValueError: 標頭含有標記字串，或格式不符（見 parse_header）。
    """
    if HEADER_START in header or HEADER_END in header:
        raise ValueError("標頭不可以含有標頭標記字串")
    parse_header(header)
    label = CAPTION_LABEL + (shorten_header(header) if count_tokens(header) > HEADER_MAX_TOKENS else header)
    has_text = any(item.get("type") == "text" and str(item.get("text") or "").strip() for item in content_list)
    result: list[dict[str, Any]] = [{"type": "text", "text": wrap_header(header)}] if has_text else []
    for item in content_list:
        kind = item.get("type")
        level = item.get("text_level")
        if kind == "text" and isinstance(level, int) and not isinstance(level, bool) and level >= 1:
            text = str(item.get("text") or "").strip()
            result.append({**item, "text": f"{'#' * min(level, 6)} {text}"} if text else item)
        elif kind == "table":
            result.append({**item, "table_caption": _with_caption_label(item.get("table_caption"), label)})
        elif kind == "image":
            result.append({**item, "image_caption": _with_caption_label(item.get("image_caption"), label)})
        else:
            result.append(item)
    return result


# ==============================
# 切塊
# ==============================


def _split_sections(body: str) -> list[tuple[str | None, str]]:
    """依標題行把內文切成節。

    Args:
        body: 去掉標頭區塊之後的文件內容。

    Returns:
        [(章節名稱或 None, 含標題行的節文字)]；標題前的文字是名稱為 None 的一節；內容全空的節不列。
    """
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in body.split("\n"):
        match = _HEADING_LINE.match(line)
        if match:
            sections.append((match.group(2).strip(), [line]))
        else:
            sections[-1][1].append(line)
    result = []
    for title, lines in sections:
        text = "\n".join(lines).strip()
        if title is not None or text:
            result.append((title, text))
    return result


def _group_short_sections(
    sections: list[tuple[str | None, str]], tokenizer: Any
) -> list[list[tuple[str | None, str]]]:
    """少於 SHORT_SECTION_TOKENS 的節併進下一節，最後一組還太短時併進前一組。

    Args:
        sections: _split_sections 的輸出，[(章節名稱或 None, 含標題行的節文字)]。
        tokenizer: LightRAG 的 Tokenizer（用 encode 算 token 數）。

    Returns:
        分組後的節，每組是 sections 裡連續的幾節，順序不變。
    """
    groups: list[list[tuple[str | None, str]]] = []
    current: list[tuple[str | None, str]] = []
    current_tokens = 0
    for section in sections:
        current.append(section)
        current_tokens += len(tokenizer.encode(section[1]))
        if current_tokens >= SHORT_SECTION_TOKENS:
            groups.append(current)
            current, current_tokens = [], 0
    if current:
        if groups:
            groups[-1].extend(current)
        else:
            groups.append(current)
    return groups


def _group_text(group: list[tuple[str | None, str]]) -> tuple[list[str], str]:
    """取出一組節的章節名稱與內文。第一節有名稱時，它的標題行由章節行取代，其餘節保留標題行。

    Args:
        group: _group_short_sections 的一組節，[(章節名稱或 None, 含標題行的節文字)]。

    Returns:
        (章節名稱清單, 組的內文)；內文以空行串接各節。
    """
    titles = [title for title, _ in group if title]
    parts = []
    for index, (title, text) in enumerate(group):
        if index == 0 and title is not None:
            text = text.split("\n", 1)[1].strip() if "\n" in text else ""
        if text:
            parts.append(text)
    return titles, "\n\n".join(parts)


def chunk_by_headings(
    tokenizer: Any,
    content: str,
    split_by_character: str | None = None,
    split_by_character_only: bool = False,
    chunk_overlap_token_size: int = 100,
    chunk_token_size: int = 1200,
) -> list[dict[str, Any]]:
    """LightRAG 的 chunking_func：在標題處切塊，每個 chunk 開頭放標頭與章節名稱。

    Args:
        tokenizer: LightRAG 的 Tokenizer（encode／decode）。
        content: 文件內容，開頭必須是 rewrite_content_list 放的標頭標記區塊。
        split_by_character: 不支援，只為符合 LightRAG 的簽名。
        split_by_character_only: 不支援，只為符合 LightRAG 的簽名。
        chunk_overlap_token_size: 組內依 token 再切時，每段與前一段的重疊 token 數。
        chunk_token_size: 每個 chunk（含標頭與章節行）的 token 上限。

    Returns:
        [{"tokens", "content", "chunk_order_index"}]，順序與文件相同。

    Raises:
        ValueError: 內容沒有標頭標記區塊、標頭格式不符（見 parse_header），或標頭佔掉的 token 太多、內文每段剩下的 token 不超過重疊的 token 數。
    """
    match = _HEADER_BLOCK.match(content)
    if match is None:
        raise ValueError("文件內容開頭沒有標頭標記區塊；使用依標題切塊的 chunker 時，每份文件都必須經過 parse_document 的改寫")
    header = match.group(1)
    parse_header(header)
    long_header = len(tokenizer.encode(header)) > HEADER_MAX_TOKENS
    short_header = shorten_header(header) if long_header else header
    sections = _split_sections(content[match.end() :])
    chunks: list[dict[str, Any]] = []
    for group in _group_short_sections(sections, tokenizer):
        titles, text = _group_text(group)
        if not text and not titles:
            continue
        tokens = tokenizer.encode(text)
        start = 0
        while True:
            lead = header if not chunks else short_header
            if titles:
                lead += "\n章節：" + "、".join(titles)
            budget = chunk_token_size - len(tokenizer.encode(lead + "\n\n"))
            if budget <= chunk_overlap_token_size:
                raise ValueError(
                    f"標頭與章節行佔掉太多 token，內文每段只剩 {budget} token，不超過重疊的 {chunk_overlap_token_size}"
                )
            end = min(start + budget, len(tokens))
            piece = tokenizer.decode(tokens[start:end]).strip()
            chunk_content = f"{lead}\n\n{piece}" if piece else lead
            chunks.append(
                {
                    "tokens": len(tokenizer.encode(chunk_content)),
                    "content": chunk_content,
                    "chunk_order_index": len(chunks),
                }
            )
            if end >= len(tokens):
                break
            start = end - chunk_overlap_token_size
    return chunks
