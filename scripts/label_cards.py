"""替台新知識庫每份文件產生卡片標籤（卡別＋適用卡片），並產生交使用者抽查的報告。

為什麼存在：重匯要把卡片標籤放進檔名與每個 chunk 的標頭（spec「卡片標籤」，GLOSSARY「卡片標籤」），
讓問題裡的卡片名稱能比對到正確文件的 chunk。標籤由程式依規則產生、使用者抽查後才給下游用；
使用者修正的項目要回寫成規則，所以每次重跑得到同樣的結果。

用法：
    python3 scripts/label_cards.py [--data-dir DIR] [--labels FILE] [--review FILE]
    預設讀 data/taishin_credit_card，寫 DIR/_meta/document_labels.json 與 output/rag_opt/labels_review.md。
    不連網；輸入是 _meta/manifest.jsonl、類別資料夾與 _meta/html、_meta/print 的頁面快照。

規則（依序，第一條適用的就用）：
1. 卡片頁（cards/、debit_cards/）：網址的 cgXXX 對應卡名，卡名是頁面 h1。卡別由資料夾決定。
   信用卡與金融卡的 cgXXX 會重複（cg003、cg008），所以用（卡別，cgXXX）當 key。
2. richart/ 兩份文件依檔名：richart_credit-card 是「台新Richart卡」，richart_debit-card 是「Richart簽帳金融卡」。
   兩頁內文都會提到對方的卡名，所以不用內文比對。
3. 其他有頁面快照的文件：在主內容區（_meta/print）比對已知卡名。比對前去掉空白、不分大小寫；先比對長的寫法
   並遮掉，所以「元氣VISA金融卡」不會同時算成「VISA金融卡」。比對不到任何卡名時列為待人工確認，不猜。
4. 沒有頁面快照的權益附件：讀權益子頁的原始 HTML 找出連到它的頁面（fetch_taishin.py 的 collect_attachments 也是這樣找，
   manifest 沒有記來源頁面），沿用那些頁面標籤的聯集；沒有頁面連到它、或連到它的頁面待人工確認時，列為待人工確認。
5. 沒有頁面快照的活動圖片：檔名裡的活動編號（WM_數字）對應活動頁，沿用那一頁的標籤。
6. 其他（下載區 PDF、金融卡約定條款 PDF）：官網沒有記錄它從哪頁連過去，列為待人工確認。

標籤內容（make_label）：某一卡別的已知卡片全部出現時，該卡別寫「全部信用卡」或「全部金融卡」；
簡短卡名：一張卡寫卡名，多張寫「多卡」，全部寫「全部」；兩種卡別都有時卡別寫「信用卡及金融卡」。
標頭是「卡別：…｜適用卡片：…」，超過 150 個 token 時改寫成「適用 N 張卡（清單見本文件第一段）」。

標籤檔格式：key 是文件相對於資料根目錄的路徑，值有 kind、cards、short_name、header、source、needs_review、reason。
待人工確認的文件 needs_review 是 true，kind 是空字串、cards 是空清單、short_name 與 header 是 null：
下游（改檔名、標頭檔）看到 needs_review 是 true 要停下來，不能當成有標籤。使用者修正時直接改這個檔
（needs_review 改成 false 並填好欄位）。

關鍵設計決策與 ASSUMPTION：
- ASSUMPTION：已知卡名清單只有官網有獨立卡片頁的卡片（信用卡 16 張、金融卡 5 張，加上寫死的 Richart簽帳金融卡）。
  權益頁與活動頁常提到沒有卡片頁的卡（環球無限卡、財富無限卡、國泰航空世界卡、商務卡等），這些卡不會出現在標籤裡，
  只提到它們的文件會變成待人工確認；同時提到已知卡與這些卡的文件，標籤只列已知卡（不完整）。
- ASSUMPTION：「全部信用卡」「全部金融卡」只在內文比對到該卡別所有已知卡片時才標；內文只寫「台新信用卡」不算。
- ASSUMPTION：內文比對讀 _meta/print（主內容區）而不是 _meta/html（整頁），因為整頁含導覽選單，會讓每頁都比到卡名。
- ASSUMPTION：卡名裡的「/」換成「・」（例如「新光三越御璽・鈦金・白金卡」）：「／」是清單分隔符號，而且卡名要放進檔名；
  內文比對仍認得原本的 h1 寫法。
- ASSUMPTION：活動圖片靠檔名裡的活動編號對應活動頁（manifest 沒有來源頁面欄位，fetch_taishin.py 的主視覺也是從活動頁取的）。
- ASSUMPTION：同一份附件被多個權益頁連到時，適用卡片取各頁的聯集。
- ASSUMPTION：標頭 token 數用 LightRAG 預設的 tokenizer（tiktoken，gpt-4o-mini 的編碼）。
- 內文別名（EXTRA_ALIASES）只補「頁面 h1 與內文寫法不同」的卡（例如 h1 是「新光三越御璽/鈦金/白金卡」，內文寫「新光三越白金卡」）；
  使用者抽查後發現漏比對的寫法，加進這個表。

已知極限：
- 子字串比對不看上下文：內文寫「不含雙幣卡」也會算成適用雙幣信用卡。
- 官網新增卡片頁時，卡名會自動進清單，但內文別名要手動補。

Dependencies: tiktoken（LightRAG 已依賴，不是新增依賴）。
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

REPO_ROOT = Path(__file__).resolve().parent.parent
KINDS = ("信用卡", "金融卡")
HEADER_TOKEN_LIMIT = 150
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


def find_cards(text: str, catalog: list[Card]) -> list[Card]:
    """在文字裡比對已知卡名。

    先比對長的寫法並把比到的位置遮掉，所以「元氣VISA金融卡」不會同時算成「VISA金融卡」。

    Args:
        text: 頁面內文。
        catalog: 已知卡片清單。

    Returns:
        內文提到的卡片，順序同 catalog。
    """
    remaining = normalize(text)
    entries = sorted(
        ((normalize(alias), card) for card in catalog for alias in card.aliases),
        key=lambda entry: len(entry[0]),
        reverse=True,
    )
    hit: set[Card] = set()
    for alias, card in entries:
        if alias in remaining:
            hit.add(card)
            remaining = remaining.replace(alias, "\0")
    return [card for card in catalog if card in hit]


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

    某一卡別的卡片全部在清單裡時，該卡別的卡名清單換成「全部信用卡」或「全部金融卡」。
    標頭超過 HEADER_TOKEN_LIMIT 個 token 時，改寫成「適用 N 張卡（清單見本文件第一段）」，
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
        in_catalog = [card for card in catalog if card.kind == kind]
        if len(in_catalog) > 1 and set(chosen) == set(in_catalog):
            entries.append(f"全部{kind}")
            all_entries += 1
        else:
            entries.extend(card.name for card in chosen)
        count += len(chosen)
    kind_text = "及".join(kinds)
    if all_entries == len(entries):
        short_name = "全部"
    elif len(entries) == 1:
        short_name = entries[0]
    else:
        short_name = "多卡"
    header = f"卡別：{kind_text}｜適用卡片：{LIST_SEPARATOR.join(entries)}"
    if token_counter()(header) > HEADER_TOKEN_LIMIT:
        header = f"卡別：{kind_text}｜適用 {count} 張卡（清單見本文件第一段）"
    return {"kind": kind_text, "cards": entries, "short_name": short_name, "header": header}


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
        path: 相對於資料根目錄的路徑（標籤檔的 key）。
        category: manifest 的類別。
        url: 文件網址。
        stem: 檔名去掉副檔名，也是 _meta/html 與 _meta/print 的快照檔名。
    """

    path: str
    category: str
    url: str
    stem: str


class _PageParser(HTMLParser):
    """從 HTML 取出可見文字、第一個 h1、第一個 h1～h3 與 <title>，並收集 <a> 的連結。"""

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
        self.text.append(data)
        for field in self._capture:
            setattr(self, field, getattr(self, field) + data)

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
    """讀 manifest，留下有實體檔的文件。

    Args:
        data_dir: 資料根目錄（含 _meta/manifest.jsonl 與各類別資料夾）。

    Returns:
        有實體檔的文件，順序同 manifest。
    """
    docs = []
    with (data_dir / "_meta" / "manifest.jsonl").open(encoding="utf-8") as manifest:
        for line in manifest:
            row = json.loads(line)
            path = f"{CATEGORY_FOLDERS[row['category']]}/{row['filename']}"
            if (data_dir / path).is_file():
                docs.append(Doc(path, row["category"], row["url"], row["filename"].rsplit(".", 1)[0]))
    return docs


# ==============================
# 已知卡名清單
# ==============================

# 卡片頁標題以外的寫法。key 是（卡別，官網群組編號 cgXXX）。內文裡的寫法和卡片頁的 h1 不同時才需要補
# （例如 h1 是「新光三越御璽/鈦金/白金卡」，內文寫「新光三越白金卡」）。
EXTRA_ALIASES: dict[tuple[str, str], tuple[str, ...]] = {
    ("信用卡", "cg003"): ("國泰航空翱翔鈦金卡", "國泰航空鈦金卡"),
    ("信用卡", "cg008"): ("新光三越御璽卡", "新光三越鈦金卡", "新光三越白金卡"),
    ("信用卡", "cg009"): ("昇恆昌御璽卡", "昇恆昌白金卡", "昇恆昌普卡"),
    ("信用卡", "cg010"): ("大全聯卡",),
    ("信用卡", "cg014"): ("新光三越無限卡", "新光三越世界卡"),
    ("信用卡", "cg019"): ("friDay聯名卡",),
    ("信用卡", "cg039"): ("雙幣卡",),
    ("信用卡", "cg042"): ("Gogoro聯名卡",),
    ("信用卡", "cg047"): ("Richart卡",),
    ("金融卡", "cg008"): ("蝴蝶悠遊卡",),
}
# richart.tw 的簽帳金融卡沒有 cgXXX 頁面，寫死
RICHART_DEBIT = Card(
    "金融卡",
    "Richart簽帳金融卡",
    ("Richart簽帳金融卡", "Richart Mastercard簽帳金融卡", "Richart D卡", "遛狗卡", "綠狗卡", "白狗卡"),
)
# richart/ 資料夾兩份文件各自對應的卡名
RICHART_PAGE_CARDS = {"richart_credit-card": "台新Richart卡", "richart_debit-card": "Richart簽帳金融卡"}


def build_catalog(data_dir: Path, docs: list[Doc]) -> tuple[list[Card], dict[tuple[str, str], Card]]:
    """從卡片頁建立已知卡名清單：群組編號 cgXXX 對應卡名（頁面 h1）。

    Args:
        data_dir: 資料根目錄。
        docs: 有實體檔的文件。

    Returns:
        (清單, 以（卡別，cgXXX）查卡的字典)。清單含寫死的 Richart 簽帳金融卡。
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
    catalog.append(RICHART_DEBIT)
    return catalog, by_cg


# ==============================
# 產生標籤
# ==============================

def pending(reason: str) -> dict:
    """待人工確認的標籤紀錄：沒有卡別與適用卡片，下游不能使用。

    Args:
        reason: 為什麼沒有標籤。

    Returns:
        標籤紀錄。
    """
    return {"kind": "", "cards": [], "short_name": None, "header": None, "source": "", "needs_review": True, "reason": reason}


def labelled(cards: list[Card], catalog: list[Card], source: str) -> dict:
    """有標籤的紀錄。

    Args:
        cards: 適用的卡片。
        catalog: 全部已知卡片。
        source: 標籤怎麼來的。

    Returns:
        標籤紀錄（make_label 的欄位加 source、needs_review、reason）。
    """
    return {**make_label(cards, catalog), "source": source, "needs_review": False, "reason": ""}


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


def label_data_dir(data_dir: Path) -> dict[str, dict]:
    """替資料夾裡每份有實體檔的文件產生標籤。

    規則依序是：卡片頁用頁面 h1 對應的卡名；richart/ 兩份文件依檔名；其他有頁面快照的文件，
    在 _meta/print（主內容區）比對已知卡名；沒有頁面快照的權益附件與活動圖片沿用連到它的頁面的標籤；
    其他一律列為待人工確認。

    Args:
        data_dir: 資料根目錄（含 _meta/manifest.jsonl、_meta/html、_meta/print 與各類別資料夾）。

    Returns:
        文件相對路徑對標籤紀錄。
    """
    docs = read_docs(data_dir)
    catalog, by_cg = build_catalog(data_dir, docs)
    by_name = {card.name: card for card in catalog}
    cards_of: dict[str, list[Card]] = {}
    labels: dict[str, dict] = {}
    for doc in docs:
        if doc.category in CARD_PAGE_KINDS:
            match = re.search(r"/(cg\d+)/", doc.url)
            card = by_cg.get((CARD_PAGE_KINDS[doc.category], match.group(1))) if match else None
            if card:
                cards_of[doc.path] = [card]
                labels[doc.path] = labelled([card], catalog, "卡片頁")
            else:
                labels[doc.path] = pending("卡片頁找不到卡名")
        elif doc.category == "Richart 卡片頁":
            card = by_name.get(RICHART_PAGE_CARDS.get(doc.stem, ""))
            if card:
                cards_of[doc.path] = [card]
                labels[doc.path] = labelled([card], catalog, "卡片頁")
            else:
                labels[doc.path] = pending("Richart 卡片頁對應的卡名不在已知清單")
        elif (snapshot := data_dir / "_meta" / "print" / f"{doc.stem}.html").is_file():
            found = find_cards("".join(parse_page(snapshot).text), catalog)
            if found:
                cards_of[doc.path] = found
                labels[doc.path] = labelled(found, catalog, "頁面內文")
            else:
                labels[doc.path] = pending("頁面內文沒有比對到已知卡名")
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
            labels[doc.path] = pending(missing)
        elif unlabelled := [path for path in sources if path not in cards_of]:
            labels[doc.path] = pending(f"連到它的頁面待人工確認：{'、'.join(unlabelled)}")
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


def render_review(data_dir: Path, labels: dict[str, dict]) -> str:
    """產生抽查報告（markdown）：各資料夾文件數、標籤統計、待人工確認清單、每個資料夾抽 3 份。

    抽樣用固定種子，同樣的標籤重跑得到同樣的報告。

    Args:
        data_dir: 資料根目錄（讀頁面標題用）。
        labels: label_data_dir 的結果。

    Returns:
        報告全文。
    """
    docs = {doc.path: doc for doc in read_docs(data_dir)}
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
    out += ["", "## 待人工確認", ""]
    out += [f"- `{path}`：{entry['reason']}" for path, entry in labels.items() if entry["needs_review"]] or ["（無）"]
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
        解析結果：data_dir、labels、review。
    """
    parser = argparse.ArgumentParser(description="為台新知識庫的每份文件產生卡片標籤與抽查報告。")
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data" / "taishin_credit_card", help="資料根目錄")
    parser.add_argument("--labels", type=Path, help="標籤檔路徑（預設是 <資料根目錄>/_meta/document_labels.json）")
    parser.add_argument("--review", type=Path, default=REPO_ROOT / "output" / "rag_opt" / "labels_review.md", help="抽查報告路徑")
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
    labels = label_data_dir(args.data_dir)
    labels_path.write_text(json.dumps(labels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.review.parent.mkdir(parents=True, exist_ok=True)
    args.review.write_text(render_review(args.data_dir, labels), encoding="utf-8")
    pending_count = sum(entry["needs_review"] for entry in labels.values())
    print(f"{len(labels)} 份文件，待人工確認 {pending_count} 份；標籤檔 {labels_path}；抽查報告 {args.review}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
