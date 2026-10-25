"""假的 OpenAI 相容 server：測試夾具，讓快速測試不必啟動真實 MLX 模型。

為什麼存在：spec 規定日常測試對一個回傳固定回應的假 server 執行，後續所有
ticket 的 CLI 測試都共用它。涵蓋 chat、vision、embeddings 三種能力，對應兩個路徑：
- POST /v1/chat/completions：純文字（chat）回固定字串；訊息含圖片時（vision）
  回另一個固定字串。
- POST /v1/embeddings：每個輸入回一個維度可設定的決定性向量。

關鍵設計決策：
- vision 只接受 base64 data URI（與 mlx-vlm 實測行為一致）；格式或 base64
  不合法回 400，不對任何輸入都假裝成功。
- embedding 依請求的 encoding_format 回 float list 或 base64（float32 小端），
  因為 lightrag 預設以 base64 請求。
- 回傳固定且可預測：同一輸入永遠得到同一向量，測試不會因隨機性不穩。
- 綁定 127.0.0.1 的隨機埠，在背景 thread 啟停；用 context manager 使用。

已知極限：不支援 streaming；chat 回覆是固定字串，不會依 prompt 變化。

Dependencies: 僅標準函式庫。
"""

import base64
import hashlib
import json
import re
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

CHAT_REPLY = "pong"
VISION_REPLY = "The square in the image is red."

_DATA_URI = re.compile(r"^data:image/[A-Za-z0-9.+-]+;base64,(?P<payload>.+)$", re.DOTALL)

# ==============================
# 回應內容
# ==============================


def fake_vector(text: str, dim: int) -> list[float]:
    """由文字決定性地產生固定維度的向量。

    Args:
        text: 輸入文字。
        dim: 向量維度。

    Returns:
        長度為 dim、每個值落在 [-1, 1) 的 float list。
    """
    values: list[float] = []
    counter = 0
    while len(values) < dim:
        digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
        values.extend(b / 128.0 - 1.0 for b in digest)
        counter += 1
    return values[:dim]


def _image_urls(messages: list[dict[str, Any]]) -> list[str]:
    """取出 messages 中所有 image_url 的 url。"""
    urls: list[str] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            urls.extend(
                part["image_url"]["url"]
                for part in content
                if isinstance(part, dict) and part.get("type") == "image_url"
            )
    return urls


def _is_valid_image_data_uri(url: str) -> bool:
    """判斷是否為合法的 base64 圖片 data URI。"""
    match = _DATA_URI.match(url)
    if not match:
        return False
    try:
        return len(base64.b64decode(match.group("payload"), validate=True)) > 0
    except ValueError:
        return False


# ==============================
# HTTP handler
# ==============================


class _Handler(BaseHTTPRequestHandler):
    """處理 /v1/chat/completions 與 /v1/embeddings。"""

    server: "_Server"

    def log_message(self, format: str, *args: Any) -> None:
        """關閉預設的 stderr 請求記錄，保持測試輸出乾淨。"""

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_error(self, status: int, message: str) -> None:
        self._send_json(status, {"error": {"message": message, "type": "invalid_request_error"}})

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._send_error(400, "request body is not valid JSON")
            return
        if not isinstance(payload, dict):
            self._send_error(400, "request body must be a JSON object")
            return

        if self.path == "/v1/chat/completions":
            self._chat(payload)
        elif self.path == "/v1/embeddings":
            self._embeddings(payload)
        else:
            self._send_error(404, f"unknown endpoint {self.path}")

    def _chat(self, payload: dict[str, Any]) -> None:
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            self._send_error(400, "messages must be a non-empty list")
            return
        images = _image_urls(messages)
        if any(not _is_valid_image_data_uri(url) for url in images):
            self._send_error(400, "image_url must be a base64 data URI (data:image/...;base64,...)")
            return
        reply = VISION_REPLY if images else CHAT_REPLY
        self._send_json(
            200,
            {
                "id": "chatcmpl-fake",
                "object": "chat.completion",
                "created": 0,
                "model": payload.get("model", "fake"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": reply},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    def _embeddings(self, payload: dict[str, Any]) -> None:
        texts = payload.get("input")
        if isinstance(texts, str):
            texts = [texts]
        if not isinstance(texts, list) or not texts or not all(isinstance(t, str) for t in texts):
            self._send_error(400, "input must be a string or a non-empty list of strings")
            return
        use_base64 = payload.get("encoding_format") == "base64"
        data = []
        for index, text in enumerate(texts):
            vector = fake_vector(text, self.server.embed_dim)
            embedding: Any = (
                base64.b64encode(struct.pack(f"<{len(vector)}f", *vector)).decode() if use_base64 else vector
            )
            data.append({"object": "embedding", "index": index, "embedding": embedding})
        self._send_json(
            200,
            {
                "object": "list",
                "data": data,
                "model": payload.get("model", "fake"),
                "usage": {"prompt_tokens": len(texts), "total_tokens": len(texts)},
            },
        )


class _Server(ThreadingHTTPServer):
    """帶有 embed_dim 的 HTTP server。"""

    daemon_threads = True

    def __init__(self, embed_dim: int):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.embed_dim = embed_dim


# ==============================
# 對外介面
# ==============================


class FakeOpenAIServer:
    """在背景 thread 執行的假 OpenAI 相容 server。

    用法：
        with FakeOpenAIServer(embed_dim=1024) as server:
            server.base_url  # 例如 http://127.0.0.1:54321/v1

    Args:
        embed_dim: embedding 向量維度，應與被測設定的 EMBED_DIM 一致。
    """

    def __init__(self, embed_dim: int = 1024):
        self._server = _Server(embed_dim)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        """可直接填入 *_BASE_URL 的位址（含 /v1）。"""
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1"

    def start(self) -> None:
        """啟動背景 thread 開始接受請求。"""
        self._thread.start()

    def stop(self) -> None:
        """停止 server 並釋放埠。"""
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()

    def __enter__(self) -> "FakeOpenAIServer":
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()
