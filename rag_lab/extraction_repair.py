"""修補 LLM 抽取輸出裡 LightRAG 會整筆丟掉的紀錄，並把修補掛到 LightRAG 的解析函式上。

為什麼存在：Gemma 4 的實體／關係抽取輸出常有格式錯誤：開頭分隔符號寫壞（`entity<|名稱`）、欄位中間的分隔符號寫壞
（`A<|도>B`）、keywords 和描述用逗號黏在一起或整個漏掉。LightRAG 1.4.16 的解析器要求欄位數剛好對，錯一點就整筆丟掉；
2026-11-23 重匯後的快取裡有 1,904 筆，其中約 1,500 筆看得出原意。

關鍵設計決策：
- 只改 LightRAG 會丟的紀錄：每一行先用 LightRAG 自己的步驟（fix_tuple_delimiter_corruption＋兩個欄位檢查函式）判斷，
  接受的原樣保留；修補後 LightRAG 仍不接受的也原樣保留，交給 LightRAG 照舊丟掉（迴圈產生的垃圾不救）。
- 一行裡有好幾筆紀錄（`…<|#|>entity<|#|>…`）的交給 LightRAG 自己切，不修。
- 修補掛在 lightrag.operate._process_extraction_result 前面：匯入時的新輸出、讀快取重放、刪文件後的重建都會經過它，
  快取裡存的仍是模型原始輸出。

已知極限：
- 規則是從 Gemma 實際的錯誤樣本歸納的，不保證涵蓋其他模型的錯誤型態；抽查 40 筆修補結果 39 筆正確。
- keywords 與描述用逗號黏在一起時，開頭幾段都很短（≤ 8 字）才當成 keywords；描述本身以短句加逗號開頭時會被誤切。
- 完全漏掉 keywords 的關係補上佔位詞「相關」（MISSING_KEYWORDS），不是模型抽出來的。
- 修補後實體類型超過 8 字（ENTITY_TYPE_MAX_CHARS）就不修：多半是模型把名稱寫在類型欄，修了會得到錯的名稱。
- 掛的是 LightRAG 的內部函式；升級 LightRAG 要重新確認（測試會擋）。

Dependencies: lightrag。
"""

import functools
import re

import lightrag.operate
from lightrag.operate import _handle_single_entity_extraction, _handle_single_relationship_extraction
from lightrag.utils import fix_tuple_delimiter_corruption, split_string_by_multi_markers

REPAIRED_LIGHTRAG_VERSION = "1.4.16"
DEFAULT_TUPLE_DELIMITER = "<|#|>"
KEYWORD_MAX_CHARS = 8
# 關係漏掉 keywords 時補的佔位詞：LightRAG 切欄位會丟掉空欄位，keywords 不能是空字串
MISSING_KEYWORDS = "相關"

# 開頭標記後面的雜訊：完整的標籤（`<|…|>`、`<…>`）或不完整的開頭（`<|`、`<`、`|`）
_JUNK_TAG = re.compile(r"^<\|?[^<>]*?\|?>")
_JUNK_OPENER = re.compile(r"^(?:<\||<|\|)")
_ASCII_IDENTIFIER = re.compile(r"^[A-Za-z0-9_\- ]+$")
# 名稱前面的 ASCII 標籤（`ebb_name: `）
_ASCII_LABEL = re.compile(r"^[A-Za-z_]+:\s*")
# 名稱前面黏著的其他文字系統雜訊字（韓文、泰文、阿拉伯文、天城文、假名），中文知識庫不會出現
_FOREIGN_SCRIPT_PREFIX = re.compile(r"^[\u0600-\u06ff\u0900-\u097f\u0e00-\u0e7f\u3040-\u30ff\uac00-\ud7af\s]+")
# 修補後的實體類型最長字數；超過代表類型欄裝的其實是名稱（領域實體類型最長 5 字）
ENTITY_TYPE_MAX_CHARS = 8
# 欄位中間寫壞的分隔符號：`<|도>`、`<|突破_|>`（不含 # 的短標記）
_INNER_DELIMITER = re.compile(r"<\|[^<>#]{0,12}\|?>")
# 不在 `<|#|>` 裡的 `|#|`
_BARE_HASH = re.compile(r"(?<!<)\|#\|(?!>)")
# 開頭一段或幾段 ≤ KEYWORD_MAX_CHARS 字、以逗號結尾的 keywords，後面接描述
_GLUED_KEYWORDS = re.compile(rf"^((?:[^,，。]{{1,{KEYWORD_MAX_CHARS}}}[,，]\s*)+)(.+)$", re.DOTALL)
_HEAD = re.compile(r"^(entity|relationship|relation)(.*)$", re.IGNORECASE | re.DOTALL)


# ==============================
# 判斷 LightRAG 是否接受
# ==============================


def _accepted(line: str, tuple_delimiter: str) -> bool:
    """這一行照 LightRAG 的步驟能不能解析成一筆實體或關係。

    Args:
        line: 一行抽取輸出。
        tuple_delimiter: 欄位分隔符號。

    Returns:
        LightRAG 會接受時為 True。
    """
    core = tuple_delimiter[2:-2]
    record = fix_tuple_delimiter_corruption(line.strip(), core, tuple_delimiter)
    attrs = split_string_by_multi_markers(record, [tuple_delimiter])
    return (
        _handle_single_entity_extraction(attrs, "repair-check", 0) is not None
        or _handle_single_relationship_extraction(attrs, "repair-check", 0) is not None
    )


# ==============================
# 修補規則
# ==============================


def _split_head(line: str, tuple_delimiter: str) -> list[str] | None:
    """切欄位並修開頭標記；沒有 entity／relation 開頭時依欄位數判斷（3 欄 entity、4 欄 relation）。

    Args:
        line: 一行抽取輸出。
        tuple_delimiter: 欄位分隔符號。

    Returns:
        第一欄為 "entity" 或 "relation" 的欄位清單；看不出是哪一種時為 None。
    """
    if line.startswith(tuple_delimiter):
        body = split_string_by_multi_markers(line[len(tuple_delimiter):], [tuple_delimiter])
        kind = {3: "entity", 4: "relation"}.get(len(body))
        return [kind, *body] if kind else None
    attrs = split_string_by_multi_markers(line, [tuple_delimiter])
    match = _HEAD.match(attrs[0].strip())
    if not match:
        return None
    kind = "entity" if match.group(1).lower() == "entity" else "relation"
    rest = match.group(2).strip()
    if not rest:
        return [kind, *attrs[1:]]
    tag = _JUNK_TAG.match(rest)
    if tag:
        # 完整的標籤（`<|：#|>`、`<dt_type=卡片>`）後面接的就是名稱
        tail = rest[tag.end():].strip()
    else:
        tail = _FOREIGN_SCRIPT_PREFIX.sub("", _JUNK_OPENER.sub("", rest, count=1)).strip()
        tail = _ASCII_LABEL.sub("", tail, count=1)
        if _ASCII_IDENTIFIER.match(tail):
            # 不完整的開頭後面接 ASCII 識別字（`<|hold_type`）：那是雜訊，第一個真正的欄位在分隔符號後面
            tail = ""
    return [kind, tail, *attrs[1:]] if tail else [kind, *attrs[1:]]


def _split_inner(attrs: list[str], want: int) -> list[str]:
    """欄位數不足時，把欄位裡寫壞的分隔符號當成分隔拆開。

    Args:
        attrs: 欄位清單（第一欄是種類）。
        want: 這個種類應有的欄位數。

    Returns:
        拆過的欄位清單；欄位數已足夠時原樣回傳。
    """
    if len(attrs) >= want:
        return attrs
    fixed = [attrs[0]]
    for field in attrs[1:]:
        if _INNER_DELIMITER.search(field):
            fixed.extend(part for part in _INNER_DELIMITER.split(field) if part.strip())
        else:
            fixed.append(field)
    return fixed


def _split_keywords(field: str) -> tuple[str, str]:
    """把逗號黏在一起的「keywords,描述」拆開。

    Args:
        field: 關係的最後一個欄位（應是描述）。

    Returns:
        (keywords, 描述)；沒有 keywords 段時 keywords 是 MISSING_KEYWORDS。
    """
    match = _GLUED_KEYWORDS.match(field.strip())
    if not match:
        return MISSING_KEYWORDS, field.strip()
    keywords = ",".join(part.strip() for part in re.split(r"[,，]", match.group(1)) if part.strip())
    return keywords, match.group(2).strip()


def _repair_line(line: str, tuple_delimiter: str) -> str | None:
    """修補一行；修不了時回傳 None。

    Args:
        line: LightRAG 不接受的一行。
        tuple_delimiter: 欄位分隔符號。

    Returns:
        修好的一行（欄位以 tuple_delimiter 相連），或 None。
    """
    line = _BARE_HASH.sub(tuple_delimiter, line.strip())
    attrs = _split_head(line, tuple_delimiter)
    if attrs is None:
        return None
    if attrs[0] == "entity":
        attrs = _split_inner(attrs, 4)
        if len(attrs) == 5:
            attrs = ["relation", *attrs[1:]]
        elif len(attrs) == 4:
            entity_type = re.sub(r"^\((.*)\)$", r"\1", attrs[2].strip())
            entity_type = re.split(r"[<|]", entity_type)[0].strip()
            if len(entity_type) > ENTITY_TYPE_MAX_CHARS:
                return None
            attrs = [attrs[0], attrs[1], entity_type, attrs[3]]
    if attrs[0] == "relation":
        attrs = _split_inner(attrs, 5)
        if len(attrs) == 4:
            keywords, description = _split_keywords(attrs[3])
            attrs = [attrs[0], attrs[1], attrs[2], keywords, description]
    if any("<|" in field or "|>" in field for field in attrs[1:3]):
        return None
    return tuple_delimiter.join(attrs)


# ==============================
# 公開介面
# ==============================


def repair_extraction_output(result: str, tuple_delimiter: str = DEFAULT_TUPLE_DELIMITER) -> str:
    """修補一段抽取輸出裡 LightRAG 會丟掉、但看得出原意的紀錄。

    Args:
        result: LLM 的抽取輸出（一行一筆紀錄，最後是完成標記）。
        tuple_delimiter: 欄位分隔符號（LightRAG 預設 `<|#|>`）。

    Returns:
        修補後的輸出；LightRAG 原本就接受的行、修不了的行、一行多筆的行都原樣保留。
    """
    multi_record = (f"{tuple_delimiter}entity{tuple_delimiter}", f"{tuple_delimiter}relation")
    lines = result.split("\n")
    for index, line in enumerate(lines):
        if not line.strip() or tuple_delimiter not in line and "|#|" not in line:
            continue
        if any(marker in line for marker in multi_record) or _accepted(line, tuple_delimiter):
            continue
        fixed = _repair_line(line, tuple_delimiter)
        if fixed is not None and _accepted(fixed, tuple_delimiter):
            lines[index] = fixed
    return "\n".join(lines)


def install() -> None:
    """把修補掛到 lightrag.operate._process_extraction_result 前面；重複呼叫只掛一次。"""
    original = lightrag.operate._process_extraction_result
    if getattr(original, "rag_lab_repair", False):
        return

    @functools.wraps(original)
    async def repaired(result, chunk_key, timestamp, file_path="unknown_source", tuple_delimiter="<|#|>", *args, **kwargs):
        return await original(
            repair_extraction_output(result, tuple_delimiter), chunk_key, timestamp, file_path, tuple_delimiter, *args, **kwargs
        )

    repaired.rag_lab_repair = True
    lightrag.operate._process_extraction_result = repaired
