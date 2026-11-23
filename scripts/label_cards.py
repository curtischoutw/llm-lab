"""替台新知識庫每份文件產生卡片標籤（卡別＋適用卡片），並產生交使用者抽查的報告。

為什麼存在：重匯要把卡片標籤放進檔名與每個 chunk 的標頭（spec「卡片標籤」，GLOSSARY「卡片標籤」），
讓問題裡的卡片名稱能比對到正確文件的 chunk。標籤由程式依規則產生、使用者抽查後才給下游用；
使用者修正的項目要回寫成規則，所以每次重跑得到同樣的結果。

用法：
    python3 scripts/label_cards.py [--data-dir DIR] [--labels FILE] [--review FILE] [--manual FILE]
    預設讀 data/taishin_credit_card 與 scripts/label_cards_manual.json，寫 DIR/_meta/document_labels.json 與 output/rag_opt/labels_review.md。
    不連網；輸入是 _meta/manifest.jsonl、類別資料夾與 _meta/html、_meta/print 的頁面快照。

規則（依序，第一條適用的就用）：
0. 人工標籤優先：scripts/label_cards_manual.json（版本控制的資料檔，--manual 可換路徑）有這份文件就直接用，
   跳過下面所有規則。格式：key 是文件相對於資料根目錄的路徑，值是 {"kind", "cards", "decision"}：
   kind 是「信用卡」「金融卡」或「信用卡及金融卡」；cards 是字串清單，每項可以是已知卡名、「全部信用卡」「全部金融卡」，
   或不在已知清單的自由描述（例如「台新VISA、JCB信用卡」），但不能含「／」「｜」（含就報錯中止，不自動修改）；
   decision 是使用者怎麼決定的（寫進 source，可省略）。路徑在 manifest 找不到也報錯。
   short_name 與 header 仍依 make_label 的格式規則產生；source 是「人工確認：decision」、needs_review 是 false。
   何時要加進去：使用者抽查後改的標籤、或使用者確認了待人工確認的文件，而這個結果無法（或不該）靠修改比對規則得到時
   （例如只出現在某一份文件的卡別寫法）；能用規則表達的修正（別名、已知卡）改規則，不加人工標籤。
   人工標籤的頁面，連到它的附件與活動圖片仍沿用它的標籤，但只限 cards 每一項都對得到已知卡（卡名或「全部」）；
   含自由描述時，沿用它的文件列為待人工確認。
1. 卡片頁（cards/、debit_cards/）：網址的 cgXXX 對應卡名，卡名是頁面 h1。卡別由資料夾決定。
   信用卡與金融卡的 cgXXX 會重複（cg003、cg008），所以用（卡別，cgXXX）當 key。
2. richart/ 兩份文件依檔名：richart_credit-card 是「台新Richart卡」，richart_debit-card 是「Richart簽帳金融卡」。
   兩頁內文都會提到對方的卡名，所以不用內文比對。
3. 其他有頁面快照的文件：在主內容區（_meta/print）比對已知卡名，加上泛稱（GENERAL_TERMS）所指的整個卡別。
   比對前去掉空白、不分大小寫；先比對長的寫法並遮掉，所以「元氣VISA金融卡」不會同時算成「VISA金融卡」。
   一個寫法可以是多張卡的別名（「新光三越聯名卡」「台新新光三越聯名卡」＝新光三越兩張卡）。
   比對不到任何卡名時列為待人工確認，不猜。
4. 沒有頁面快照的權益附件：讀權益子頁的原始 HTML 找出連到它的頁面（fetch_taishin.py 的 collect_attachments 也是這樣找，
   manifest 沒有記來源頁面），沿用那些頁面標籤的聯集；沒有頁面連到它、或連到它的頁面待人工確認時，列為待人工確認。
5. 沒有頁面快照的活動圖片：檔名裡的活動編號（WM_數字）對應活動頁，沿用那一頁的標籤。
6. 其他（下載區 PDF、金融卡約定條款 PDF）：官網沒有記錄它從哪頁連過去，列為待人工確認。

仍比對不到的文件（Q41）：標籤檔裡維持 needs_review: true，另有 suggested 欄位放程式依資料夾給的建議
（rights、rights_attachments、downloads、offers 建議全部信用卡，debit_info、debit_terms 建議全部金融卡，
richart_discounts 建議台新Richart卡，檔名含 BENZ 建議 Mercedes-Benz卡）。建議不會自動採用；
使用者確認後直接把 suggested 的內容搬到標籤欄位並把 needs_review 改成 false。
抽查報告逐份列出這些文件的路徑、頁面標題、內文開頭約 150 字與建議。

卡名附近的否定詞（Q42）：子字串比對不看上下文。報告另列一節，卡名前後 30 字內有「不適用、除外、排除、不含、恕不、非上述」
的文件，列出路徑、卡名與前後文；標籤本身不因此改變。

標籤內容（make_label）：某一卡別的已知卡片全部出現時，該卡別寫「全部信用卡」或「全部金融卡」；
簡短卡名：一張卡寫卡名，多張寫「多卡」，全部寫「全部」；兩種卡別都有時卡別寫「信用卡及金融卡」。
標頭是「卡別：…｜適用卡片：…」，超過 150 個 token 時改寫成「適用卡片：共 N 張卡」（rag_lab.chunking.short_header：縮短邏輯只留那一份，格式 parse_header 接受）。

檔名格式（rag-optimization ticket 02）：文件改名後是 <卡別>_<簡短卡名>_<原檔名>（labelled_filename）。標籤檔、人工標籤檔與頁面快照
一律用原檔名當 key，read_docs 把已經改名的文件還原成原檔名（original_filename），所以改名之後重跑本腳本得到同樣的 key。
卡別或簡短卡名含路徑分隔、:*?"<>|、逗號、底線或控制字元時報錯（逗號是 eval 題目 source 欄的分隔符號，底線是檔名三段的分隔）；
空白不算不安全（目前只有「Gogoro Rewards聯名卡」含空白）。改名本身由 rename_documents.py 做。

標籤檔格式：key 是文件相對於資料根目錄的路徑，值有 kind、cards、short_name、header、source、needs_review、reason、suggested。
待人工確認的文件 needs_review 是 true，kind 是空字串、cards 是空清單、short_name 與 header 是 null：
下游（改檔名、標頭檔）看到 needs_review 是 true 要停下來，不能當成有標籤。使用者修正時直接改這個檔
（needs_review 改成 false 並填好欄位）。

關鍵設計決策與 ASSUMPTION：
- 已知卡名清單（使用者 2026-11-19 決定 Q40）：官網有獨立卡片頁的卡（信用卡 16 張、金融卡 5 張）、寫死的 Richart簽帳金融卡，
  加上 EXTRA_CARDS（沒有卡片頁、但頁面內文實際提到的卡，同一張卡的不同寫法與更名前後的名稱併在一起）。
  不確定是不是「一張卡」的詞（卡片階級、卡組織泛稱、支付工具、系列名稱）不加，列在 UNDECIDED_TERMS，抽查報告每次印出文件數。
  ASSUMPTION：EXTRA_CARDS 裡的卡一律當信用卡；卡別是從內文語境判斷（適用卡別列表、保險、停車等信用卡權益），沒有逐張查證。
- 「全部信用卡」「全部金融卡」有兩種來源：內文比對到該卡別所有已知卡片；或內文出現泛稱（使用者 2026-11-20 決定）：
  「全台新信用卡」算全部信用卡、「簽帳金融卡會員」算全部金融卡（GENERAL_TERMS）。內文只寫「台新信用卡」仍不算。
  泛稱的誤差：「簽帳金融卡會員」會把沒有簽帳功能的金融卡（例如勞動保障卡）也算進去，使用者接受；
  「Richart簽帳金融卡會員」這類帶卡名的寫法也會同時觸發（泛稱不遮蔽、也不被卡名遮蔽）。
  判斷「全部信用卡」時不要求比對到企業卡（Q54，OPTIONAL_FOR_ALL）：比對到其他所有信用卡就算全部。
- ASSUMPTION：內文比對讀 _meta/print（主內容區）而不是 _meta/html（整頁），因為整頁含導覽選單，會讓每頁都比到卡名。
- ASSUMPTION：卡名裡的「/」換成「・」（例如「新光三越御璽・鈦金・白金卡」）：「／」是清單分隔符號，而且卡名要放進檔名；
  內文比對仍認得原本的 h1 寫法。
- ASSUMPTION：活動圖片靠檔名裡的活動編號對應活動頁（manifest 沒有來源頁面欄位，fetch_taishin.py 的主視覺也是從活動頁取的）。
- ASSUMPTION：同一份附件被多個權益頁連到時，適用卡片取各頁的聯集。
- ASSUMPTION：標頭 token 數用 LightRAG 預設的 tokenizer（tiktoken，gpt-4o-mini 的編碼）。
- 已知卡「企業卡」（別名「企業信用卡」）算一張信用卡（使用者 2026-11-20 決定）；「smart聯名卡」「輔仁大學認同卡」
  使用者決定不加進已知卡。
- 內文別名（EXTRA_ALIASES）只補「頁面 h1 與內文寫法不同」的卡（例如 h1 是「新光三越御璽/鈦金/白金卡」，內文寫「新光三越白金卡」）；
  使用者抽查後發現漏比對的寫法，加進這個表。

已知極限：
- 子字串比對不看上下文：內文寫「不含雙幣卡」也會算成適用雙幣信用卡（使用者接受，報告另列否定詞清單）。
  例外只有「企業卡」（Q53）：它幾乎只出現在「不含簽帳金融卡、企業卡」這類排除句，所以位置前後 EXCLUSION_WINDOW 字內有
  「不適用、除外、排除、不含、恕不、非上述」就不算這次出現，同一份文件其他位置仍算。誤差：視窗是字數不是語意，排除句與清單句相隔太近時
  清單句的企業卡也會被排掉，排除詞離得太遠則擋不住。
- 官網新增卡片頁時，卡名會自動進清單，但內文別名要手動補。

Dependencies: tiktoken（LightRAG 已依賴，不是新增依賴）；rag_lab.chunking（專案內，只用標準函式庫，取標頭縮短格式與長度上限）。
"""

import argparse
import json
import random
import re
import sys
from dataclasses import dataclass
from functools import cache
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import tiktoken

# 標頭縮短的格式與長度上限沿用 rag_lab/chunking.py（只用標準函式庫）；腳本在 scripts/ 底下，要先把 repo 根目錄放進 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag_lab.chunking import HEADER_MAX_TOKENS, short_header  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
MANUAL_LABELS_PATH = Path(__file__).resolve().parent / "label_cards_manual.json"
KINDS = ("信用卡", "金融卡")
LIST_SEPARATOR = "／"


@dataclass(frozen=True)
class Card:
    """一張已知卡片。

    Attributes:
        kind: 卡別，「信用卡」或「金融卡」。
        name: 顯示用卡名。
        aliases: 在內文比對時算作這張卡的寫法（已去空白、不分大小寫比對）。
    """

    kind: str
    name: str
    aliases: tuple[str, ...]


def normalize(text: str) -> str:
    """去掉所有空白並轉小寫，讓「Richart  簽帳金融卡」與「richart簽帳金融卡」比得上同一個寫法。

    Args:
        text: 原始文字。

    Returns:
        去空白、小寫的文字。
    """
    return re.sub(r"\s+", "", text).lower()


def compact(text: str) -> str:
    """去掉所有空白，保留大小寫（內文比對與取前後文都用這個版本）。

    Args:
        text: 原始文字。

    Returns:
        沒有空白的文字。
    """
    return re.sub(r"\s+", "", text)


# 「企業卡」專用的排除規則（使用者 2026-11-20 決定 Q53）：它幾乎只出現在「不含簽帳金融卡、企業卡」這類排除句，
# 子字串比對會把它誤算成適用卡。企業卡的位置前後 EXCLUSION_WINDOW 字（去空白後）內有 EXCLUSION_WORDS 就不算這次出現，
# 同一份文件其他沒被排除的位置仍算；其他卡不看上下文（Q42 不變）。
# 誤差：視窗是字數不是語意，排除句與清單句相隔不到視窗時，清單句的企業卡也會被排掉；
# 超出視窗的排除句（「不含」離企業卡太遠）擋不住。
EXCLUSION_CARDS = ("企業卡",)
# 否定詞清單（Q42 的報告與企業卡排除規則共用同一份），例如「簽帳金融卡、企業卡恕不適用」。
NEGATION_WORDS = ("不適用", "除外", "排除", "不含", "恕不", "非上述")
EXCLUSION_WORDS = NEGATION_WORDS
EXCLUSION_WINDOW = 15
# 判斷「全部信用卡」「全部金融卡」時不要求比對到的卡（使用者 2026-11-20 決定 Q54）：比對到其他所有卡就算全部；
# 企業卡比對到了也照樣算在適用卡片裡。
OPTIONAL_FOR_ALL = ("企業卡",)


def is_excluded(body: str, start: int, end: int) -> bool:
    """卡名前後 EXCLUSION_WINDOW 字內有沒有排除詞。

    Args:
        body: 去空白後的內文。
        start: 卡名起點。
        end: 卡名終點。

    Returns:
        有排除詞時是 True。
    """
    window = body[max(0, start - EXCLUSION_WINDOW) : end + EXCLUSION_WINDOW]
    return any(word in window for word in EXCLUSION_WORDS)


def occurrences(text: str, catalog: list[Card]) -> list[tuple[Card, int, int]]:
    """內文裡每一處卡名的位置。

    先比對長的寫法並把比到的位置遮掉，所以「元氣VISA金融卡」不會同時算成「VISA金融卡」。
    同一個寫法可以是多張卡的別名（例如「新光三越聯名卡」），比到時每張卡都算。
    EXCLUSION_CARDS 的卡在排除句裡的出現不算（見 EXCLUSION_WINDOW）。

    Args:
        text: 頁面內文。
        catalog: 已知卡片清單。

    Returns:
        (卡片, 起點, 終點)，位置是 compact(text) 的索引，順序依出現位置。
    """
    body = compact(text).lower()
    remaining = body
    owners: dict[str, list[Card]] = {}
    for card in catalog:
        for alias in card.aliases:
            owners.setdefault(normalize(alias), []).append(card)
    found: list[tuple[Card, int, int]] = []
    for alias in sorted(owners, key=len, reverse=True):
        for match in re.finditer(re.escape(alias), remaining):
            found.extend(
                (card, match.start(), match.end())
                for card in owners[alias]
                if not (card.name in EXCLUSION_CARDS and is_excluded(body, match.start(), match.end()))
            )
        remaining = remaining.replace(alias, "\0" * len(alias))
    return sorted(found, key=lambda item: item[1])


def find_cards(text: str, catalog: list[Card]) -> list[Card]:
    """在文字裡比對已知卡名。

    Args:
        text: 頁面內文。
        catalog: 已知卡片清單。

    Returns:
        內文提到的卡片，順序同 catalog。
    """
    hit = {card for card, _, _ in occurrences(text, catalog)}
    return [card for card in catalog if card in hit]


# 內文出現這些詞就算某一卡別的全部卡片（使用者 2026-11-20 決定）：詞 -> 卡別
GENERAL_TERMS = {"全台新信用卡": "信用卡", "簽帳金融卡會員": "金融卡"}


def match_cards(text: str, catalog: list[Card]) -> list[Card]:
    """內文適用的卡片：比對到的卡名，加上 GENERAL_TERMS 的詞所指的整個卡別。

    Args:
        text: 頁面內文。
        catalog: 已知卡片清單。

    Returns:
        適用的卡片，順序同 catalog。
    """
    hit = set(find_cards(text, catalog))
    body = normalize(text)
    for term, kind in GENERAL_TERMS.items():
        if normalize(term) in body:
            hit.update(card for card in catalog if card.kind == kind)
    return [card for card in catalog if card in hit]


NEGATION_WINDOW = 30


def find_negations(text: str, catalog: list[Card]) -> list[tuple[Card, str]]:
    """卡名前後 NEGATION_WINDOW 個字內有否定詞的卡名。

    子字串比對不看上下文，「非上述表列卡別皆不適用，例:台新Richart卡」也會算成適用台新Richart卡；
    這個函式把這種卡名找出來給使用者看，不改標籤。距離以去掉空白後的字數算。

    Args:
        text: 頁面內文。
        catalog: 已知卡片清單。

    Returns:
        (卡片, 卡名前後文)，每張卡在一份文件只列第一處，順序依出現位置。
    """
    body = compact(text)
    result: list[tuple[Card, str]] = []
    seen: set[Card] = set()
    for card, start, end in occurrences(text, catalog):
        if card in seen:
            continue
        low, high = max(0, start - NEGATION_WINDOW), end + NEGATION_WINDOW
        if any(word in body[low:high] for word in NEGATION_WORDS):
            seen.add(card)
            result.append((card, body[low:high]))
    return result


@cache
def token_counter():
    """LightRAG 預設用的 tokenizer（gpt-4o-mini 的編碼），算標頭長度用。

    Returns:
        回傳文字 token 數的函式。
    """
    encoding = tiktoken.encoding_for_model("gpt-4o-mini")
    return lambda text: len(encoding.encode(text))


def make_label(cards: list[Card], catalog: list[Card]) -> dict:
    """卡片清單轉成標籤：卡別、適用卡片、簡短卡名與標頭文字。

    某一卡別的卡片全部在清單裡時，該卡別的卡名清單換成「全部信用卡」或「全部金融卡」
    （OPTIONAL_FOR_ALL 的卡不要求在清單裡）。
    標頭超過 HEADER_MAX_TOKENS 個 token 時，改寫成 rag_lab.chunking.short_header 的「適用卡片：共 N 張卡」，
    N 是實際張數（「全部」展開後的張數）。

    Args:
        cards: 文件適用的卡片，至少一張。
        catalog: 全部已知卡片，用來判斷「全部」。

    Returns:
        dict：kind（信用卡、金融卡或信用卡及金融卡）、cards（適用卡片，字串清單）、
        short_name（一張卡寫卡名，多張寫「多卡」，全部寫「全部」）、header（標頭文字）。
    """
    kinds = [kind for kind in KINDS if any(card.kind == kind for card in cards)]
    entries: list[str] = []
    all_entries = 0
    count = 0
    for kind in kinds:
        chosen = [card for card in cards if card.kind == kind]
        in_catalog = [card for card in catalog if card.kind == kind and card.name not in OPTIONAL_FOR_ALL]
        if len(in_catalog) > 1 and set(in_catalog) <= set(chosen):
            entries.append(f"全部{kind}")
            all_entries += 1
        else:
            entries.extend(card.name for card in chosen)
        count += len(chosen)
    return compose_label("及".join(kinds), entries, all_entries, count)


def compose_label(kind_text: str, entries: list[str], all_entries: int, count: int) -> dict:
    """卡別與適用卡片字串組成標籤（自動標籤與人工標籤共用的格式規則）。

    Args:
        kind_text: 卡別（信用卡、金融卡或信用卡及金融卡）。
        entries: 適用卡片，字串清單（「全部信用卡」「全部金融卡」算一項）。
        all_entries: entries 裡「全部…」的項數。
        count: 實際張數（「全部」展開後），標頭超過 token 上限時寫進「適用 N 張卡」。

    Returns:
        dict：kind、cards、short_name、header。
    """
    if all_entries == len(entries):
        short_name = "全部"
    elif len(entries) == 1:
        short_name = entries[0]
    else:
        short_name = "多卡"
    header = f"卡別：{kind_text}｜適用卡片：{LIST_SEPARATOR.join(entries)}"
    if token_counter()(header) > HEADER_MAX_TOKENS:
        header = short_header(kind_text, count)
    return {"kind": kind_text, "cards": entries, "short_name": short_name, "header": header}


def make_manual_label(path: str, entry: dict, catalog: list[Card]) -> dict:
    """使用者人工確認的標籤紀錄：卡別與卡片照人工檔，標頭等欄位的格式同 make_label。

    cards 的每一項可以是已知卡名、「全部信用卡」「全部金融卡」，或不在已知清單的自由描述
    （例如「台新VISA、JCB信用卡」）。自由描述不能含「／」「｜」，含的話報錯，不自動修改。

    Args:
        path: 文件相對路徑（錯誤訊息用）。
        entry: 人工檔裡這份文件的紀錄：kind、cards、decision（decision 可省略）。
        catalog: 全部已知卡片，用來算「全部」展開後的張數。

    Returns:
        標籤紀錄（同 labelled 的欄位，source 是「人工確認」加 decision）。

    Raises:
        ValueError: 缺 kind 或 cards、卡別不是信用卡／金融卡／信用卡及金融卡、cards 是空的或有項目含分隔符號。
    """
    kind, cards = entry.get("kind"), entry.get("cards")
    if kind not in (*KINDS, "及".join(KINDS)):
        raise ValueError(f"人工標籤 {path} 的卡別不合法：{kind!r}")
    if not isinstance(cards, list) or not cards or not all(isinstance(card, str) and card for card in cards):
        raise ValueError(f"人工標籤 {path} 的 cards 必須是非空字串清單：{cards!r}")
    for card in cards:
        if LIST_SEPARATOR in card or "｜" in card:
            raise ValueError(f"人工標籤 {path} 的卡片描述含分隔符號「{LIST_SEPARATOR}」或「｜」：{card}")
    all_kinds = {f"全部{k}": k for k in KINDS}
    count = sum(sum(c.kind == all_kinds[card] for c in catalog) if card in all_kinds else 1 for card in cards)
    label = compose_label(kind, list(cards), sum(card in all_kinds for card in cards), count)
    decision = entry.get("decision", "")
    source = f"人工確認：{decision}" if decision else "人工確認"
    return {**label, "source": source, "needs_review": False, "reason": "", "suggested": None}


# ==============================
# 檔名格式
# ==============================

# 檔名前綴的卡別；長的在前，original_filename 的比對才不會把「信用卡及金融卡」切成「信用卡」
FILENAME_KINDS = ("信用卡及金融卡", "信用卡", "金融卡")
# 檔名裡不能出現的字元：路徑分隔、Windows／macOS 保留字元、控制字元，加上兩個本專案的分隔符號：
# 「_」（檔名三段的分隔，改回原檔名要靠它）與「,」（eval 題目的 source 欄用逗號分隔多個來源）
UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|,_\x00-\x1f]')
# ASSUMPTION：檔名位元組數上限 200（macOS、Linux 單一檔名上限 255，留空間給後綴）。
# 超過時簡短卡名改用「多卡」：完整的卡片清單在標頭檔裡，檔名只是方便人看。目前資料最長 102 位元組，沒有用到
FILENAME_BYTE_LIMIT = 200
FALLBACK_SHORT_NAME = "多卡"
_PREFIXED_FILENAME = re.compile(rf"^(?:{'|'.join(FILENAME_KINDS)})_[^_]+_(.+)$")


def labelled_filename(label: dict, filename: str) -> str:
    """文件的新檔名：<卡別>_<簡短卡名>_<原檔名>。

    Args:
        label: 標籤紀錄，要有 kind 與 short_name（needs_review 為 true 的紀錄沒有，不能傳進來）。
        filename: 原檔名。

    Returns:
        新檔名。位元組數超過 FILENAME_BYTE_LIMIT 時簡短卡名改寫成「多卡」。

    Raises:
        ValueError: 卡別或簡短卡名含不能放進檔名的字元（UNSAFE_FILENAME_CHARS），或是空的。
    """
    kind, short_name = label["kind"], label["short_name"]
    for part in (kind, short_name):
        if not part or UNSAFE_FILENAME_CHARS.search(part):
            raise ValueError(f"卡別或簡短卡名含不安全的檔名字元（路徑分隔、:*?\"<>|、逗號、底線、控制字元）或是空的：{part!r}")
    name = f"{kind}_{short_name}_{filename}"
    if len(name.encode("utf-8")) > FILENAME_BYTE_LIMIT:
        name = f"{kind}_{FALLBACK_SHORT_NAME}_{filename}"
    return name


def original_filename(filename: str) -> str:
    """新檔名還原成原檔名；本來就是原檔名的原樣回傳。

    原檔名（fetch_taishin.py 的 local_name）以英文類別前綴開頭，不會被當成帶卡別前綴。
    頁面快照（_meta/html、_meta/print）、標籤檔與人工標籤檔都用原檔名當 key。

    Args:
        filename: 檔名（新或舊格式）。

    Returns:
        原檔名。
    """
    match = _PREFIXED_FILENAME.match(filename)
    return match.group(1) if match else filename


# ==============================
# 讀 manifest 與頁面快照
# ==============================

# manifest 的類別對應到資料夾（同 scripts/fetch_taishin.py 各 Category 的 folder）
CATEGORY_FOLDERS = {
    "卡片": "cards",
    "權益": "rights",
    "下載": "downloads",
    "權益附件": "rights_attachments",
    "活動": "offers",
    "活動圖片": "offer_images",
    "金融卡卡片頁": "debit_cards",
    "金融卡約定條款 PDF": "debit_terms",
    "金融卡說明頁": "debit_info",
    "Richart 卡片頁": "richart",
    "Richart 優惠細則": "richart_discounts",
}
CARD_PAGE_KINDS = {"卡片": "信用卡", "金融卡卡片頁": "金融卡"}


@dataclass(frozen=True)
class Doc:
    """manifest 裡一份有實體檔的文件。

    Attributes:
        path: 相對於資料根目錄的原檔名路徑（標籤檔的 key）。檔案已改成新檔名時，path 仍是原檔名。
        category: manifest 的類別。
        url: 文件網址。
        stem: 原檔名去掉副檔名，也是 _meta/html 與 _meta/print 的快照檔名。
        filename: 檔案現在的檔名（新或舊格式）。
    """

    path: str
    category: str
    url: str
    stem: str
    filename: str


class _PageParser(HTMLParser):
    """從 HTML 取出可見文字（不含 <title>）、第一個 h1、第一個 h1～h3 與 <title>，並收集 <a> 的連結。"""

    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.hrefs: list[str] = []
        self.title = ""
        self.h1 = ""
        self.heading = ""
        self._skip = 0
        self._capture: set[str] = set()
        self._done: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "a":
            self.hrefs.extend(value for name, value in attrs if name == "href" and value)
        else:
            for field in self._fields(tag):
                if field not in self._done:
                    self._capture.add(field)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip -= 1
        for field in self._fields(tag):
            if field in self._capture:
                self._capture.discard(field)
                self._done.add(field)
        if tag in ("p", "div", "li", "tr", "br", "h1", "h2", "h3"):
            self.text.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        for field in self._capture:
            setattr(self, field, getattr(self, field) + data)
        if "title" not in self._capture:
            self.text.append(data)

    @staticmethod
    def _fields(tag: str) -> list[str]:
        """這個標籤的內容要記到哪些欄位。

        Args:
            tag: 標籤名稱。

        Returns:
            欄位名稱清單（title、h1、heading）。
        """
        return {"title": ["title"], "h1": ["h1", "heading"], "h2": ["heading"], "h3": ["heading"]}.get(tag, [])


def parse_page(path: Path) -> _PageParser:
    """讀一個 HTML 檔並解析。

    Args:
        path: HTML 檔。

    Returns:
        解析結果：text（可見文字片段）、hrefs、title、h1。
    """
    parser = _PageParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def squash(text: str) -> str:
    """連續空白合成一個空格並去頭尾。

    Args:
        text: 原始文字。

    Returns:
        整理後的文字。
    """
    return re.sub(r"\s+", " ", text).strip()


def read_docs(data_dir: Path) -> list[Doc]:
    """讀 manifest，留下有實體檔的文件。檔名已改成新格式（labelled_filename）的文件，path 與 stem 還原成原檔名。

    manifest 寫的檔名在資料夾裡找不到、但資料夾裡有同一份文件改過名的檔案（改名做到一半中斷：檔案已改、manifest 還沒改）時，
    也算有實體檔，Doc.filename 是那個檔案現在的檔名。

    Args:
        data_dir: 資料根目錄（含 _meta/manifest.jsonl 與各類別資料夾）。

    Returns:
        有實體檔的文件，順序同 manifest。
    """
    renamed: dict[str, dict[str, str]] = {}

    def renamed_in(folder: str) -> dict[str, str]:
        if folder not in renamed:
            names = sorted(p.name for p in (data_dir / folder).iterdir() if p.is_file()) if (data_dir / folder).is_dir() else []
            renamed[folder] = {original_filename(name): name for name in names if original_filename(name) != name}
        return renamed[folder]

    docs = []
    with (data_dir / "_meta" / "manifest.jsonl").open(encoding="utf-8") as manifest:
        for line in manifest:
            row = json.loads(line)
            folder = CATEGORY_FOLDERS[row["category"]]
            original = original_filename(row["filename"])
            current = row["filename"] if (data_dir / folder / row["filename"]).is_file() else renamed_in(folder).get(original)
            if current is not None:
                docs.append(Doc(f"{folder}/{original}", row["category"], row["url"], original.rsplit(".", 1)[0], current))
    return docs


# ==============================
# 已知卡名清單
# ==============================

# 卡片頁標題以外的寫法。key 是（卡別，官網群組編號 cgXXX）。內文裡的寫法和卡片頁的 h1 不同時才需要補
# （例如 h1 是「新光三越御璽/鈦金/白金卡」，內文寫「新光三越白金卡」）。
# 泛稱「新光三越聯名卡」同時是 cg008、cg014 兩張卡的別名（使用者 2026-11-20 決定：內文出現就兩張都算）
SHIN_KONG_ALIASES = ("新光三越聯名卡", "台新新光三越聯名卡")
EXTRA_ALIASES: dict[tuple[str, str], tuple[str, ...]] = {
    ("信用卡", "cg003"): ("國泰航空翱翔鈦金卡", "國泰航空鈦金卡"),
    ("信用卡", "cg008"): ("新光三越御璽卡", "新光三越鈦金卡", "新光三越白金卡", *SHIN_KONG_ALIASES),
    ("信用卡", "cg009"): ("昇恆昌御璽卡", "昇恆昌白金卡", "昇恆昌普卡"),
    ("信用卡", "cg010"): ("大全聯卡", "大潤發聯名卡"),  # 官網：2025/9/12 起原大潤發聯名卡更名為大全聯信用卡
    ("信用卡", "cg014"): ("新光三越無限卡", "新光三越世界卡", *SHIN_KONG_ALIASES),
    ("信用卡", "cg019"): ("friDay聯名卡",),
    ("信用卡", "cg039"): ("雙幣卡",),
    ("信用卡", "cg042"): ("Gogoro聯名卡",),
    # 官網卡片頁 cg047 的公告：下列舊卡名皆已更名為台新Richart卡（使用者 Q43：算同一張卡）
    ("信用卡", "cg047"): ("Richart卡", "@GoGo卡", "FlyGo卡", "玫瑰Giving卡", "大買家聯名卡", "Woojii卡", "三商美邦聯名卡", "全家Richart聯名卡"),
    ("信用卡", "cg048"): ("美麗華卡",),
    ("金融卡", "cg008"): ("蝴蝶悠遊卡", "悠遊Debit卡"),
}
# 沒有獨立卡片頁、但頁面內文實際提到的卡（Q40，依 _meta/print 整理）。同一張卡的不同寫法併在 aliases；
# 更名的卡（「原 Woojii 世界商務卡」）算同一張，卡名用新名。名稱是卡名的才加；階級（御璽卡、白金卡）、
# 卡組織（台新Visa卡）、支付工具（悠遊卡）與系列名稱（悠遊聯名卡）不加，列在 UNDECIDED_TERMS 讓使用者決定。
EXTRA_CARDS: tuple[Card, ...] = (
    Card("信用卡", "環球無限卡", ("環球無限卡",)),
    Card("信用卡", "財富無限卡", ("財富無限卡",)),
    Card("信用卡", "昇恆昌無限卡", ("昇恆昌無限卡",)),
    Card("信用卡", "國泰航空世界卡", ("國泰航空世界卡",)),
    Card("信用卡", "尊爵世界卡", ("尊爵世界卡",)),
    Card("信用卡", "台新商務卡", ("台新商務卡",)),
    Card("信用卡", "台新商務鈦金卡", ("台新商務鈦金卡",)),
    Card("信用卡", "Mercedes-Benz無限卡", ("Mercedes-Benz無限卡", "賓士無限卡")),
    Card("信用卡", "Mercedes-Benz御璽卡", ("Mercedes-Benz御璽卡",)),
    Card("信用卡", "Mercedes-Benz白金卡", ("Mercedes-Benz白金卡",)),
    Card("信用卡", "Mercedes-Benz卡", ("Mercedes-Benz卡", "Mercedes-Benz信用卡")),
    Card("信用卡", "Richart世界商務卡", ("Richart世界商務卡", "Woojii世界商務卡")),
    Card("信用卡", "Richart鈦金商務卡", ("Richart鈦金商務卡", "Woojii鈦金商務卡")),
    Card("信用卡", "Richart商務御璽卡", ("Richart商務御璽卡",)),
    Card("信用卡", "街口鈦金商務卡", ("街口鈦金商務卡",)),
    Card("信用卡", "玫瑰悠遊商務鈦金卡", ("玫瑰悠遊商務鈦金卡",)),
    Card("信用卡", "比漾聯名卡", ("比漾聯名卡",)),
    Card("信用卡", "棉花田聯名卡", ("棉花田聯名卡",)),
    Card("信用卡", "SKM Park Outlets聯名卡", ("SKM Park Outlets聯名卡",)),
    Card("信用卡", "企業卡", ("企業卡", "企業信用卡")),  # 使用者 2026-11-20 決定算一張信用卡
)
# 不確定是不是「一張卡」的詞：不加進已知清單，每次產報告時列出文件數，讓使用者決定
UNDECIDED_TERMS: tuple[tuple[str, str], ...] = (
    ("御璽卡", "卡片階級，多張卡共用"),
    ("白金卡", "卡片階級，多張卡共用"),
    ("鈦金卡", "卡片階級，多張卡共用"),
    ("晶緻卡", "卡片階級，多張卡共用"),
    ("世界卡", "卡片階級，多張卡共用"),
    ("無限卡", "卡片階級，多張卡共用"),
    ("普卡", "卡片階級，多張卡共用"),
    ("頂級卡", "卡片階級的泛稱（美饌優惠專案用語）"),
    ("商務卡", "台新商務卡、街口商務卡等多張卡的泛稱"),
    ("台新Visa卡", "卡組織泛稱，不是一張卡"),
    ("Visa信用卡", "卡組織泛稱，不是一張卡"),
    ("Visa無限卡", "卡組織加階級，不是一張卡"),
    ("JCB信用卡", "卡組織泛稱，不是一張卡"),
    ("Mastercard卡", "卡組織泛稱，不是一張卡"),
    ("悠遊聯名卡", "系列名稱（信用卡與金融卡都有），多數出現在約定條款連結"),
    ("一卡通聯名卡", "系列名稱，只出現在行動裝置支付的約定條款"),
    ("icash聯名卡", "系列名稱，只出現在行動裝置支付的約定條款"),
    ("新光三越卡", "新光三越卡的泛稱（卡片頁有 cg008、cg014 兩張）"),
    ("國泰航空聯名卡", "國泰航空卡的泛稱（國泰航空翱翔鈦金卡、國泰航空世界卡兩張）"),
    ("昇恆昌聯名卡", "昇恆昌卡的泛稱（昇恆昌無限卡、昇恆昌御璽/白金/普卡）"),
    ("賓士聯名卡", "Mercedes-Benz 卡的泛稱"),
    ("街口商務卡", "可能是街口鈦金商務卡，內文只在卡別列表裡出現"),
    ("頭家商務卡", "只出現在金融卡卡片頁的「不含」清單，看不出卡別"),
    ("Story簽帳金融卡", "只出現在金融卡卡片頁的「不含」清單"),
)
# richart.tw 的簽帳金融卡沒有 cgXXX 頁面，寫死
RICHART_DEBIT = Card(
    "金融卡",
    "Richart簽帳金融卡",
    ("Richart簽帳金融卡", "Richart Mastercard簽帳金融卡", "Richart D卡", "遛狗卡", "綠狗卡", "白狗卡"),
)
# richart/ 資料夾兩份文件各自對應的卡名
RICHART_PAGE_CARDS = {"richart_credit-card": "台新Richart卡", "richart_debit-card": "Richart簽帳金融卡"}


def build_catalog(
    data_dir: Path, docs: list[Doc], extra_cards: tuple[Card, ...] = EXTRA_CARDS
) -> tuple[list[Card], dict[tuple[str, str], Card]]:
    """從卡片頁建立已知卡名清單：群組編號 cgXXX 對應卡名（頁面 h1）。

    Args:
        data_dir: 資料根目錄。
        docs: 有實體檔的文件。
        extra_cards: 沒有卡片頁的卡，接在卡片頁的卡後面。

    Returns:
        (清單, 以（卡別，cgXXX）查卡的字典)。清單依序是卡片頁的卡、extra_cards、寫死的 Richart 簽帳金融卡。
        卡名裡的「/」換成「・」，因為「／」是清單分隔符號，而且卡名要能放進檔名。
    """
    catalog: list[Card] = []
    by_cg: dict[tuple[str, str], Card] = {}
    for doc in docs:
        kind = CARD_PAGE_KINDS.get(doc.category)
        match = re.search(r"/(cg\d+)/", doc.url)
        snapshot = data_dir / "_meta" / "html" / f"{doc.stem}.html"
        if kind is None or match is None or not snapshot.is_file():
            continue
        heading = squash(parse_page(snapshot).h1)
        if not heading:
            continue
        cg = match.group(1)
        aliases = (heading, *EXTRA_ALIASES.get((kind, cg), ()))
        card = Card(kind, heading.replace("/", "・"), aliases)
        catalog.append(card)
        by_cg[(kind, cg)] = card
    catalog.extend(extra_cards)
    catalog.append(RICHART_DEBIT)
    return catalog, by_cg


# ==============================
# 產生標籤
# ==============================

# 仍比對不到的文件依資料夾的預設建議（Q41）：資料夾 -> 預設卡別（"credit"、"debit"）或卡名
FOLDER_SUGGESTIONS = {
    "rights": "credit",
    "rights_attachments": "credit",
    "downloads": "credit",
    "offers": "credit",
    "debit_info": "debit",
    "debit_terms": "debit",
    "richart_discounts": "台新Richart卡",
}
BENZ_CARD = "Mercedes-Benz卡"


def suggest(doc: Doc, catalog: list[Card]) -> dict | None:
    """待人工確認的文件，程式依資料夾給的建議標籤。只是建議，needs_review 仍是 true。

    檔名含 BENZ 的文件建議 Mercedes-Benz卡；其他依資料夾：rights、rights_attachments、downloads、offers 建議全部信用卡，
    debit_info、debit_terms 建議全部金融卡，richart_discounts 建議台新Richart卡；其他資料夾不建議。

    Args:
        doc: 文件。
        catalog: 全部已知卡片。

    Returns:
        make_label 的結果；沒有建議時是 None。
    """
    rule = FOLDER_SUGGESTIONS.get(doc.path.split("/")[0])
    if "BENZ" in doc.stem.upper():
        cards = [card for card in catalog if card.name == BENZ_CARD]
    elif rule in ("credit", "debit"):
        kind = KINDS[0] if rule == "credit" else KINDS[1]
        cards = [card for card in catalog if card.kind == kind]
    else:
        cards = [card for card in catalog if card.name == rule]
    return make_label(cards, catalog) if cards else None


def pending(reason: str, suggested: dict | None = None) -> dict:
    """待人工確認的標籤紀錄：沒有卡別與適用卡片，下游不能使用。

    Args:
        reason: 為什麼沒有標籤。
        suggested: 程式建議的標籤（suggest 的結果）。

    Returns:
        標籤紀錄。
    """
    return {
        "kind": "",
        "cards": [],
        "short_name": None,
        "header": None,
        "source": "",
        "needs_review": True,
        "reason": reason,
        "suggested": suggested,
    }


def labelled(cards: list[Card], catalog: list[Card], source: str) -> dict:
    """有標籤的紀錄。

    Args:
        cards: 適用的卡片。
        catalog: 全部已知卡片。
        source: 標籤怎麼來的。

    Returns:
        標籤紀錄（make_label 的欄位加 source、needs_review、reason、suggested）。
    """
    return {**make_label(cards, catalog), "source": source, "needs_review": False, "reason": "", "suggested": None}


def linked_pages(data_dir: Path, docs: list[Doc]) -> dict[str, list[str]]:
    """權益附件 PDF 是從哪些權益子頁連過去的：讀權益子頁存下來的原始 HTML 裡的連結。

    fetch_taishin.py 的 collect_attachments 也是這樣找附件，manifest 本身沒有記錄來源頁面。

    Args:
        data_dir: 資料根目錄。
        docs: 有實體檔的文件。

    Returns:
        PDF 的網址路徑（百分比解碼、小寫）對連到它的權益子頁（文件相對路徑）。
    """
    links: dict[str, list[str]] = {}
    for doc in docs:
        snapshot = data_dir / "_meta" / "html" / f"{doc.stem}.html"
        if doc.category != "權益" or not snapshot.is_file():
            continue
        for href in parse_page(snapshot).hrefs:
            path = unquote(urlparse(urljoin(doc.url, href)).path).lower()
            if path.endswith(".pdf") and doc.path not in links.setdefault(path, []):
                links[path].append(doc.path)
    return links


def label_data_dir(data_dir: Path, manual: dict[str, dict] | None = None) -> dict[str, dict]:
    """替資料夾裡每份有實體檔的文件產生標籤。

    規則依序是：人工標籤（manual 有這份文件就直接用，跳過其餘規則）；卡片頁用頁面 h1 對應的卡名；richart/ 兩份文件依檔名；其他有頁面快照的文件，
    在 _meta/print（主內容區）比對已知卡名；沒有頁面快照的權益附件與活動圖片沿用連到它的頁面的標籤；
    其他一律列為待人工確認。

    Args:
        data_dir: 資料根目錄（含 _meta/manifest.jsonl、_meta/html、_meta/print 與各類別資料夾）。
        manual: 人工標籤，文件相對路徑對 {kind, cards, decision}；None 表示沒有。

    Returns:
        文件相對路徑對標籤紀錄。

    Raises:
        ValueError: manual 裡有路徑不在 manifest 的實體檔文件中，或人工標籤格式不合法（見 make_manual_label）。
    """
    docs = read_docs(data_dir)
    manual = manual or {}
    if unknown := sorted(set(manual) - {doc.path for doc in docs}):
        raise ValueError(f"人工標籤的路徑在 manifest 找不到：{'、'.join(unknown)}")
    catalog, by_cg = build_catalog(data_dir, docs)
    by_name = {card.name: card for card in catalog}
    cards_of: dict[str, list[Card]] = {}
    labels: dict[str, dict] = {}
    for doc in docs:
        if doc.path in manual:
            labels[doc.path] = make_manual_label(doc.path, manual[doc.path], catalog)
            # 附件與活動圖片沿用這一頁的標籤；只有每一項都對得到已知卡（卡名或「全部」）時才能沿用，
            # 含自由描述時不放進 cards_of，沿用它的文件會列為待人工確認
            resolved = [[c for c in catalog if f"全部{c.kind}" == name] or [by_name.get(name)] for name in labels[doc.path]["cards"]]
            if all(cards and None not in cards for cards in resolved):
                cards_of[doc.path] = [card for cards in resolved for card in cards]
        elif doc.category in CARD_PAGE_KINDS:
            match = re.search(r"/(cg\d+)/", doc.url)
            card = by_cg.get((CARD_PAGE_KINDS[doc.category], match.group(1))) if match else None
            if card:
                cards_of[doc.path] = [card]
                labels[doc.path] = labelled([card], catalog, "卡片頁")
            else:
                labels[doc.path] = pending("卡片頁找不到卡名", suggest(doc, catalog))
        elif doc.category == "Richart 卡片頁":
            card = by_name.get(RICHART_PAGE_CARDS.get(doc.stem, ""))
            if card:
                cards_of[doc.path] = [card]
                labels[doc.path] = labelled([card], catalog, "卡片頁")
            else:
                labels[doc.path] = pending("Richart 卡片頁對應的卡名不在已知清單", suggest(doc, catalog))
        elif (snapshot := data_dir / "_meta" / "print" / f"{doc.stem}.html").is_file():
            found = match_cards("".join(parse_page(snapshot).text), catalog)
            if found:
                cards_of[doc.path] = found
                labels[doc.path] = labelled(found, catalog, "頁面內文")
            else:
                labels[doc.path] = pending("頁面內文沒有比對到已知卡名", suggest(doc, catalog))
    links = linked_pages(data_dir, docs)
    for doc in docs:
        if doc.path in labels:
            continue
        sources: list[str] = []
        if doc.category == "權益附件":
            sources = links.get(unquote(urlparse(doc.url).path).lower(), [])
            missing = "沒有任何權益頁連到它"
        elif doc.category == "活動圖片" and (offer := re.match(r"offer_image_(WM_\d+)", doc.stem)):
            sources = [d.path for d in docs if d.category == "活動" and d.stem == f"offer_{offer.group(1)}"]
            missing = "找不到對應的活動頁"
        else:
            missing = "沒有頁面快照，查不到它從哪個頁面連過去"
        if not sources:
            labels[doc.path] = pending(missing, suggest(doc, catalog))
        elif unlabelled := [path for path in sources if path not in cards_of]:
            labels[doc.path] = pending(f"連到它的頁面待人工確認：{'、'.join(unlabelled)}", suggest(doc, catalog))
        else:
            union = {card for path in sources for card in cards_of[path]}
            labels[doc.path] = labelled([c for c in catalog if c in union], catalog, f"沿用連到它的頁面：{'、'.join(sources)}")
    return labels


# ==============================
# 抽查報告與命令列
# ==============================

SAMPLES_PER_FOLDER = 3
SAMPLE_SEED = 0


def page_title(data_dir: Path, doc: Doc) -> str:
    """文件的頁面標題，抽查時用來看標籤對不對。

    卡片頁用頁面 h1（官網卡片頁的 <title> 是共用的總覽標題）；活動用 <title>；
    其他類別用主內容區的第一個標題，沒有時用 <title>。

    Args:
        data_dir: 資料根目錄。
        doc: 文件。

    Returns:
        標題；沒有頁面快照時是「（沒有頁面快照）」。
    """
    raw = data_dir / "_meta" / "html" / f"{doc.stem}.html"
    if not raw.is_file():
        return "（沒有頁面快照）"
    page = parse_page(raw)
    if doc.category in CARD_PAGE_KINDS and page.h1.strip():
        return squash(page.h1)
    if doc.category != "活動":
        main = data_dir / "_meta" / "print" / f"{doc.stem}.html"
        if main.is_file() and (heading := squash(parse_page(main).heading)):
            return heading
    return squash(page.title) or "（沒有標題）"


def label_text(entry: dict) -> str:
    """標籤紀錄在報告裡的寫法。

    Args:
        entry: 標籤紀錄。

    Returns:
        「卡別｜適用卡片」，待人工確認的寫「待人工確認」。
    """
    if entry["needs_review"]:
        return "待人工確認"
    return f"{entry['kind']}｜{LIST_SEPARATOR.join(entry['cards'])}"


TEXT_START_CHARS = 150


def read_texts(data_dir: Path, docs: list[Doc]) -> dict[str, str]:
    """有頁面快照的文件的主內容區文字（_meta/print）。

    Args:
        data_dir: 資料根目錄。
        docs: 有實體檔的文件。

    Returns:
        文件相對路徑對內文；沒有頁面快照的文件不在裡面。
    """
    texts = {}
    for doc in docs:
        snapshot = data_dir / "_meta" / "print" / f"{doc.stem}.html"
        if snapshot.is_file():
            texts[doc.path] = "".join(parse_page(snapshot).text)
    return texts


def text_start(text: str | None) -> str:
    """內文開頭約 TEXT_START_CHARS 個字，抽查時用來判斷頁面在講什麼。

    Args:
        text: 內文；沒有頁面快照時是 None。

    Returns:
        去掉多餘空白後的前 TEXT_START_CHARS 個字，超過時加「…」。
    """
    if text is None:
        return "（沒有頁面快照）"
    flat = squash(text)
    return flat[:TEXT_START_CHARS] + ("…" if len(flat) > TEXT_START_CHARS else "")


def render_review(data_dir: Path, labels: dict[str, dict]) -> str:
    """產生抽查報告（markdown）。

    內容依序是：各類別資料夾文件數、標籤統計、待人工確認（逐份：標題、內文開頭、程式建議）、
    卡名附近有否定詞的文件、補進已知清單的卡名與文件數、未加入已知清單的詞，最後每個資料夾抽 3 份。
    抽樣用固定種子，同樣的標籤重跑得到同樣的報告。

    Args:
        data_dir: 資料根目錄（讀頁面標題與內文用）。
        labels: label_data_dir 的結果。

    Returns:
        報告全文。
    """
    doc_list = read_docs(data_dir)
    docs = {doc.path: doc for doc in doc_list}
    catalog, _ = build_catalog(data_dir, doc_list)
    texts = read_texts(data_dir, doc_list)
    folders = sorted({path.split("/")[0] for path in labels})
    in_folder = {folder: sorted(path for path in labels if path.split("/")[0] == folder) for folder in folders}
    out = ["# 卡片標籤抽查報告", "", "## 各類別資料夾", "", "| 類別資料夾 | 文件數 | 待人工確認 |", "| --- | --- | --- |"]
    for folder in folders:
        review_count = sum(labels[path]["needs_review"] for path in in_folder[folder])
        out.append(f"| {folder} | {len(in_folder[folder])} | {review_count} |")
    out += ["", "## 標籤統計", "", "| 卡別 | 份數 |", "| --- | --- |"]
    out += [f"| {kind} | {sum(e['kind'] == kind for e in labels.values())} |" for kind in (*KINDS, "信用卡及金融卡")]
    reviewing = [e for e in labels.values() if e["needs_review"]]
    done = [e for e in labels.values() if not e["needs_review"]]
    out += ["", "| 適用卡片 | 份數 |", "| --- | --- |"]
    out.append(f"| 一張卡 | {sum(e['short_name'] not in ('多卡', '全部') for e in done)} |")
    out.append(f"| 多卡 | {sum(e['short_name'] == '多卡' for e in done)} |")
    out.append(f"| 全部 | {sum(e['short_name'] == '全部' for e in done)} |")
    out.append(f"| 待人工確認 | {len(reviewing)} |")
    out += ["", "## 待人工確認", "", f"共 {len(reviewing)} 份。標籤檔裡這些文件仍是 needs_review: true，建議標籤放在 suggested 欄位。", ""]
    for path, entry in labels.items():
        if not entry["needs_review"]:
            continue
        suggested = entry["suggested"]
        out.append(f"- `{path}`：{entry['reason']}")
        out.append(f"  - 頁面標題：{page_title(data_dir, docs[path])}")
        out.append(f"  - 內文開頭：{text_start(texts.get(path))}")
        out.append(f"  - 程式建議：{suggested['kind']}｜{LIST_SEPARATOR.join(suggested['cards'])}" if suggested else "  - 程式建議：（無）")
    negated = {
        path: found
        for path, text in texts.items()
        if labels[path]["source"] == "頁面內文" and (found := find_negations(text, catalog))
    }
    out += ["", "## 卡名附近有否定詞", ""]
    out.append(
        f"共 {len(negated)} 份文件：卡名前後 {NEGATION_WINDOW} 字內出現「{'、'.join(NEGATION_WORDS)}」。"
        "標籤用子字串比對，不看上下文，這些文件的標籤可能把被排除的卡也列進去。每張卡每份文件只列第一處。"
    )
    out.append("")
    out += [f"- `{path}`｜{card.name}｜{context}" for path, found in negated.items() for card, context in found]
    mentioned = [set(find_cards(text, catalog)) for text in texts.values()]
    counts = {card: sum(card in found for found in mentioned) for card in EXTRA_CARDS}
    out += ["", "## 補進已知清單的卡名", "", "沒有獨立卡片頁、但內文實際提到的卡（文件數是內文提到的文件份數，含卡片頁以外的所有類別）。", ""]
    out += ["| 卡名 | 卡別 | 文件數 |", "| --- | --- | --- |"]
    out += [f"| {card.name} | {card.kind} | {count} |" for card, count in counts.items()]
    out += ["", "## 未加入已知清單的詞", "", "不確定是不是「一張卡」，沒有加進已知清單；文件數是內文含這個字串的份數。請使用者決定。", ""]
    out += ["| 詞 | 文件數 | 為什麼沒加 |", "| --- | --- | --- |"]
    for term, reason in UNDECIDED_TERMS:
        count = sum(normalize(term) in normalize(text) for text in texts.values())
        out.append(f"| {term} | {count} | {reason} |")
    out += ["", "## 每個類別資料夾抽 3 份", ""]
    rng = random.Random(SAMPLE_SEED)
    for folder in folders:
        paths = in_folder[folder]
        out += [f"### {folder}", ""]
        for path in sorted(rng.sample(paths, min(SAMPLES_PER_FOLDER, len(paths)))):
            filename = path.split("/", 1)[1]
            out.append(f"- `{filename}`｜頁面標題：{page_title(data_dir, docs[path])}｜標籤：{label_text(labels[path])}")
        out.append("")
    return "\n".join(out)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析命令列參數。

    Args:
        argv: 不含程式名稱的參數。

    Returns:
        解析結果：data_dir、labels、review、manual。
    """
    parser = argparse.ArgumentParser(description="為台新知識庫的每份文件產生卡片標籤與抽查報告。")
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data" / "taishin_credit_card", help="資料根目錄")
    parser.add_argument("--labels", type=Path, help="標籤檔路徑（預設是 <資料根目錄>/_meta/document_labels.json）")
    parser.add_argument("--review", type=Path, default=REPO_ROOT / "output" / "rag_opt" / "labels_review.md", help="抽查報告路徑")
    parser.add_argument("--manual", type=Path, default=MANUAL_LABELS_PATH, help="人工標籤檔（版本控制的資料檔）")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """產生標籤檔與抽查報告。

    Args:
        argv: 不含程式名稱的命令列參數。

    Returns:
        結束碼，0 表示成功。
    """
    args = parse_args(argv)
    labels_path = args.labels or args.data_dir / "_meta" / "document_labels.json"
    manual = json.loads(args.manual.read_text(encoding="utf-8"))
    labels = label_data_dir(args.data_dir, manual)
    labels_path.write_text(json.dumps(labels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.review.parent.mkdir(parents=True, exist_ok=True)
    args.review.write_text(render_review(args.data_dir, labels), encoding="utf-8")
    pending_count = sum(entry["needs_review"] for entry in labels.values())
    print(f"{len(labels)} 份文件，待人工確認 {pending_count} 份；標籤檔 {labels_path}；抽查報告 {args.review}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
