"""模型端點冒煙測試：確認 LLM、VLM、embedding 三個 OpenAI 相容端點都能用。

為什麼存在：RAG-Anything 依賴三種模型函式，mlx-vlm 的 base64 圖片與 /v1/embeddings
先前只讀過原始碼、沒實測過，所以在寫任何 pipeline 之前先用這支腳本把關。
端點設定讀環境變數（與 .env.example 同名），只用標準函式庫，不依賴專案 venv。

關鍵設計決策：
- VLM 測試圖由腳本現場用純 Python 畫出（紅色方塊在白底），不依賴外部檔案；
  預期描述包含 red 或「紅」。
- 任何一項失敗就以非零碼結束並印出原始回應，不重試、不繞過。

Dependencies: 僅標準函式庫。
"""

import base64
import json
import os
import struct
import sys
import urllib.error
import urllib.request
import zlib

# ==============================
# 設定
# ==============================

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8080/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "mlx-community/Qwen3-4B-Instruct-2507-4bit")
VLM_BASE_URL = os.environ.get("VLM_BASE_URL", "http://127.0.0.1:8081/v1")
VLM_MODEL = os.environ.get("VLM_MODEL", "mlx-community/Qwen3-VL-4B-Instruct-4bit")
EMBED_BASE_URL = os.environ.get("EMBED_BASE_URL", "http://127.0.0.1:8081/v1")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "mlx-community/Qwen3-Embedding-0.6B-8bit")

TIMEOUT_SEC = 300


# ==============================
# 工具函式
# ==============================


def post_json(url: str, payload: dict) -> dict:
    """送出 JSON POST 並回傳解析後的 JSON。

    Args:
        url: 完整端點 URL。
        payload: 請求內容。

    Returns:
        回應 JSON（dict）。HTTP 錯誤時直接拋出，由呼叫端讓腳本失敗。
    """
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
        return json.load(resp)


def make_red_square_png(size: int = 64) -> bytes:
    """產生白底紅色方塊的 PNG。

    Args:
        size: 圖片邊長（像素）。

    Returns:
        PNG 檔案的 bytes。
    """

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    lo, hi = size // 4, size * 3 // 4
    rows = []
    for y in range(size):
        row = bytearray([0])  # filter type 0
        for x in range(size):
            row += bytes((255, 0, 0)) if lo <= x < hi and lo <= y < hi else bytes((255, 255, 255))
        rows.append(bytes(row))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


# ==============================
# 測試項目
# ==============================


def test_chat() -> None:
    out = post_json(
        f"{LLM_BASE_URL}/chat/completions",
        {
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": "Reply with the single word: pong"}],
            "max_tokens": 16,
        },
    )
    text = out["choices"][0]["message"]["content"]
    print(f"[chat] reply={text!r}")
    assert text.strip(), "chat 回傳空字串"


def test_vision() -> None:
    b64 = base64.b64encode(make_red_square_png()).decode()
    out = post_json(
        f"{VLM_BASE_URL}/chat/completions",
        {
            "model": VLM_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What color is the square in this image? Answer in one word."},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                }
            ],
            "max_tokens": 32,
        },
    )
    text = out["choices"][0]["message"]["content"]
    print(f"[vision] reply={text!r}")
    assert "red" in text.lower() or "紅" in text, "VLM 描述不含 red／紅，可能沒有真的看到圖"


def test_embeddings() -> None:
    out = post_json(
        f"{EMBED_BASE_URL}/embeddings",
        {"model": EMBED_MODEL, "input": ["retrieval augmented generation", "knowledge graph"]},
    )
    vecs = [d["embedding"] for d in out["data"]]
    dims = {len(v) for v in vecs}
    print(f"[embeddings] count={len(vecs)} dim={dims}")
    assert len(vecs) == 2 and len(dims) == 1, "embedding 數量或維度不一致"


# ==============================
# 主程式
# ==============================


def main() -> int:
    failed = 0
    for fn in (test_chat, test_vision, test_embeddings):
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except (AssertionError, KeyError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {type(exc).__name__}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
