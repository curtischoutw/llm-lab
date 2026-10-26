"""抽樣檢視知識圖譜：讀 LightRAG 存在磁碟上的圖，列出實體與涉及它們的關係。

為什麼存在：ticket 04 要讓使用者親眼看實體與關係，判斷 4B LLM 的抽取品質夠不夠用。
檢視本身不需要任何模型，所以這裡不經 RAG-Anything／LightRAG 初始化，也不連端點。

關鍵設計決策：
- 直接讀 WORKING_DIR 下 LightRAG 的 graphml 檔（networkx 讀取）。避免為了唯讀檢視啟動
  整套儲存與限流 worker，也讓 `graph` 在 MLX server 沒開時照樣能用。
- 抽樣可重現：實體名稱先排序，再以固定 seed 的 random.Random 抽樣；同一張圖、同樣參數
  輸出必定相同。換 seed 可看另一批。
- LightRAG 的圖是無向圖，兩端順序只是儲存順序，所以關係用 `--` 連接，不用箭頭。
- 描述原樣輸出；LightRAG 合併重複描述時用 `<SEP>` 分隔，保留它能看出同一實體被重複抽取。
- 關係列出「任一端點在抽樣內」的所有邊，含 RAG-Anything 加的 belongs_to 邊（keywords 欄
  可辨認），不替使用者過濾。

已知極限：依賴 LightRAG 的內部檔名與節點／邊屬性名稱（entity_type、description、keywords）；
換 LightRAG 版本若改了儲存格式，這裡要跟著改。

Dependencies: networkx（由 lightrag 帶入）。
"""

import random
from pathlib import Path

import networkx as nx

# ==============================
# 常數與例外
# ==============================

# LightRAG NetworkXStorage 在 working_dir 下的圖檔名稱。
GRAPH_FILENAME = "graph_chunk_entity_relation.graphml"


class GraphReportError(RuntimeError):
    """圖譜不存在或是空的；訊息直接給使用者看。"""


# ==============================
# 讀取與格式化
# ==============================


def load_graph(working_dir: str) -> nx.Graph:
    """讀取 working_dir 下的知識圖譜。

    Args:
        working_dir: LightRAG 的 working_dir（WORKING_DIR）。

    Returns:
        networkx 圖。

    Raises:
        GraphReportError: 圖檔不存在，或圖裡沒有任何實體。
    """
    path = Path(working_dir) / GRAPH_FILENAME
    if not path.is_file():
        raise GraphReportError(f"找不到圖譜檔 {path}；請先執行 `ingest` 匯入論文。")
    graph = nx.read_graphml(path)
    if graph.number_of_nodes() == 0:
        raise GraphReportError(f"圖譜是空的（{path} 內沒有任何實體）；請確認 `ingest` 是否成功抽出實體。")
    return graph


def format_report(graph: nx.Graph, sample_size: int, seed: int) -> str:
    """抽樣實體並格式化成可閱讀的報告。

    Args:
        graph: 非空的知識圖譜。
        sample_size: 抽樣實體數；大於實體總數時全部列出。
        seed: 抽樣的隨機種子。

    Returns:
        多行文字：整張圖的實體與關係總數、抽樣實體（名稱、類型、描述）、涉及這些實體的關係。
    """
    names = sorted(graph.nodes)
    sampled = sorted(random.Random(seed).sample(names, min(sample_size, len(names))))
    chosen = set(sampled)

    lines = [f"圖譜：實體 {graph.number_of_nodes()}，關係 {graph.number_of_edges()}（抽樣 {len(sampled)} 個實體，seed={seed}）"]
    for index, name in enumerate(sampled, start=1):
        attrs = graph.nodes[name]
        lines.append(f"實體 {index}/{len(sampled)}：{name}（{attrs.get('entity_type', '?')}）")
        lines.append(f"  描述：{attrs.get('description', '')}")

    edges = sorted((u, v, attrs) for u, v, attrs in graph.edges(data=True) if u in chosen or v in chosen)
    lines.append(f"涉及抽樣實體的關係：{len(edges)} 條")
    for source, target, attrs in edges:
        lines.append(f"關係：{source} -- {target}（{attrs.get('keywords', '')}）")
        lines.append(f"  描述：{attrs.get('description', '')}")
    return "\n".join(lines)
