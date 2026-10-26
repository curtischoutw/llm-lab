"""假的 OpenAI 相容 server：測試夾具，讓快速測試不必啟動真實 MLX 模型。

為什麼存在：spec 規定日常測試對一個回傳固定回應的假 server 執行，後續所有
ticket 的 CLI 測試都共用它。涵蓋 chat、vision、embeddings 三種能力，對應兩個路徑：
- POST /v1/chat/completions：純文字（chat）回固定字串；訊息含圖片時（vision）
  回另一個固定字串。為了讓 RAG-Anything／LightRAG 的完整流程能對它跑通，三種
  請求會改回合法的結構化內容：實體抽取（system prompt 含 Knowledge Graph
  Specialist）回 LightRAG 的 entity／relation 行格式；關鍵字抽取（請求帶
  response_format）回關鍵字 JSON；圖／表／公式描述（prompt 含 detailed_description）
  回描述 JSON。
- POST /v1/embeddings：每個輸入回一個維度可設定的決定性向量。

關鍵設計決策：
- vision 只接受 base64 data URI（與 mlx-vlm 實測行為一致）；格式或 base64
  不合法回 400，不對任何輸入都假裝成功。
- embedding 依請求的 encoding_format 回 float list 或 base64（float32 小端），
  因為 lightrag 預設以 base64 請求。
- 回傳固定且可預測：同一輸入永遠得到同一向量，測試不會因隨機性不穩；向量是詞袋向量，
  共用詞彙的文字相似，檢索才找得回內容。
- 綁定 127.0.0.1 的隨機埠，在背景 thread 啟停；用 context manager 使用。
- 記錄收到的請求（requests）與 chat、embeddings 各自同時處理數的最大值
  （max_inflight_chat、max_inflight_embed），並可注入故障（fail_chat、fail_vision）與延遲
  （chat_delay、embed_delay），讓測試從 HTTP 邊界觀察 CLI 的外部行為。
- die_after_chat 模擬 mlx_lm.server 生成執行緒死掉（GPU 記憶體不足時實測）：正在生成的那個
  請求永遠不回應，之後的請求回 404 generation thread died。不回應的請求在 stop() 時才放開。

已知極限：不支援 streaming；回覆內容只依請求類型變化，不會真的讀懂 prompt。

Dependencies: 僅標準函式庫。
"""

import base64
import contextlib
import hashlib
import json
import re
import struct
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

CHAT_REPLY = "pong"
VISION_REPLY = "The square in the image is red."
KEYWORDS_REPLY = json.dumps({"high_level_keywords": ["fake topic"], "low_level_keywords": ["Fake Entity Alpha"]})
EXTRACTION_REPLY = (
    "entity<|#|>Fake Entity Alpha<|#|>concept<|#|>Fake Entity Alpha is a made-up concept.\n"
    "entity<|#|>Fake Entity Beta<|#|>method<|#|>Fake Entity Beta is a made-up method.\n"
    "relation<|#|>Fake Entity Alpha<|#|>Fake Entity Beta<|#|>fake link<|#|>Alpha is related to Beta.\n"
    "<|COMPLETE|>"
)

_INSTRUCTION_PREFIX = re.compile(r"^Instruct:.*?\nQuery:", re.DOTALL)
_DATA_URI = re.compile(r"^data:image/[A-Za-z0-9.+-]+;base64,(?P<payload>.+)$", re.DOTALL)

# ==============================
# 回應內容
# ==============================


def _hash_vector(text: str, dim: int) -> list[float]:
    """由文字決定性地產生固定維度、每個值落在 [-1, 1) 的向量。"""
    values: list[float] = []
    counter = 0
    while len(values) < dim:
        digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
        values.extend(b / 128.0 - 1.0 for b in digest)
        counter += 1
    return values[:dim]


def fake_vector(text: str, dim: int) -> list[float]:
    """由文字決定性地產生固定維度的詞袋向量。

    每個詞對應一個固定的偽隨機向量，文字向量是這些詞向量的和再正規化，所以共用
    詞彙的文字餘弦相似度高。這讓 LightRAG 的檢索（餘弦門檻 0.2）在假 server 上
    也能找回內容。開頭的 `Instruct: ...\nQuery:` 前綴不參與計算，模擬真實 embedding
    模型把 instruction 當作任務說明而非內容。

    Args:
        text: 輸入文字。
        dim: 向量維度。

    Returns:
        長度為 dim、L2 範數為 1 的 float list。
    """
    body = _INSTRUCTION_PREFIX.sub("", text)
    tokens = re.findall(r"\w+", body.lower()) or [body]
    total = [0.0] * dim
    for token in tokens:
        for i, value in enumerate(_hash_vector(token, dim)):
            total[i] += value
    norm = sum(v * v for v in total) ** 0.5 or 1.0
    return [v / norm for v in total]


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


def _message_text(messages: list[dict[str, Any]], role: str | None = None) -> str:
    """串接 messages 內所有文字內容（可限定 role）。"""
    parts: list[str] = []
    for message in messages:
        if role is not None and message.get("role") != role:
            continue
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(p["text"] for p in content if isinstance(p, dict) and p.get("type") == "text")
    return "\n".join(parts)


def _describe_reply(prompt: str, has_image: bool) -> str:
    """圖／表／公式描述請求的回覆 JSON；entity_name 依 prompt 雜湊，避免不同項目撞名。"""
    tag = hashlib.sha256(prompt.encode()).hexdigest()[:6]
    description = "The image shows a red square on a white background." if has_image else "A fake table or equation."
    return json.dumps(
        {
            "detailed_description": description,
            "entity_info": {"entity_name": f"Fake Item {tag}", "entity_type": "figure", "summary": description},
        }
    )


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

        self.server.record(self.path, payload)
        if self.path == "/v1/chat/completions":
            with self.server.in_flight("chat"):
                self._chat(payload)
        elif self.path == "/v1/embeddings":
            with self.server.in_flight("embed"):
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
        if self.server.die_after_chat is not None:
            number = self.server.next_chat_number()
            if number == self.server.die_after_chat + 1:
                self.server.stalled.wait()
                return
            if number > self.server.die_after_chat + 1:
                self._send_json(404, {"error": "generation thread died"})
                return
        if self.server.fail_chat:
            self._send_error(500, "injected chat failure")
            return
        if images and self.server.fail_vision:
            self._send_error(500, "injected vision failure")
            return
        if self.server.chat_delay:
            time.sleep(self.server.chat_delay)
        reply = self._chat_reply(payload, messages, bool(images))
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

    @staticmethod
    def _chat_reply(payload: dict[str, Any], messages: list[dict[str, Any]], has_image: bool) -> str:
        """依請求類型選回覆：關鍵字 JSON、實體抽取、圖表描述 JSON、圖片或純文字。"""
        if payload.get("response_format"):
            return KEYWORDS_REPLY
        if "Knowledge Graph Specialist" in _message_text(messages, "system"):
            return EXTRACTION_REPLY
        prompt = _message_text(messages)
        if "detailed_description" in prompt:
            return _describe_reply(prompt, has_image)
        return VISION_REPLY if has_image else CHAT_REPLY

    def _embeddings(self, payload: dict[str, Any]) -> None:
        texts = payload.get("input")
        if isinstance(texts, str):
            texts = [texts]
        if not isinstance(texts, list) or not texts or not all(isinstance(t, str) for t in texts):
            self._send_error(400, "input must be a string or a non-empty list of strings")
            return
        if self.server.embed_delay:
            time.sleep(self.server.embed_delay)
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
        self.fail_chat = False
        self.fail_vision = False
        self.chat_delay = 0.0
        self.embed_delay = 0.0
        self.die_after_chat: int | None = None
        self.stalled = threading.Event()
        self.requests: list[dict[str, Any]] = []
        self.max_inflight = {"chat": 0, "embed": 0}
        self._lock = threading.Lock()
        self._inflight = {"chat": 0, "embed": 0}
        self._chat_count = 0

    def record(self, path: str, payload: dict[str, Any]) -> None:
        """記錄一筆請求（路徑與 JSON 內容）。"""
        with self._lock:
            self.requests.append({"path": path, "payload": payload})

    def next_chat_number(self) -> int:
        """取得這個 chat 請求的序號（從 1 開始），供 die_after_chat 判斷。"""
        with self._lock:
            self._chat_count += 1
            return self._chat_count

    @contextlib.contextmanager
    def in_flight(self, kind: str) -> Iterator[None]:
        """標記一個請求處理中，並更新該類請求同時處理數的最大值。

        Args:
            kind: "chat" 或 "embed"。
        """
        with self._lock:
            self._inflight[kind] += 1
            self.max_inflight[kind] = max(self.max_inflight[kind], self._inflight[kind])
        try:
            yield
        finally:
            with self._lock:
                self._inflight[kind] -= 1


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
    def requests(self) -> list[dict[str, Any]]:
        """目前收到的所有請求（每筆含 path 與 payload）。"""
        with self._server._lock:
            return list(self._server.requests)

    @property
    def max_inflight_chat(self) -> int:
        """chat 請求同時處理數的最大值。"""
        return self._server.max_inflight["chat"]

    @property
    def max_inflight_embed(self) -> int:
        """embeddings 請求同時處理數的最大值。"""
        return self._server.max_inflight["embed"]

    @property
    def fail_chat(self) -> bool:
        """為 True 時，所有 chat 請求回 500。"""
        return self._server.fail_chat

    @fail_chat.setter
    def fail_chat(self, value: bool) -> None:
        self._server.fail_chat = value

    @property
    def fail_vision(self) -> bool:
        """為 True 時，帶圖片的 chat 請求回 500（純文字仍正常）。"""
        return self._server.fail_vision

    @fail_vision.setter
    def fail_vision(self, value: bool) -> None:
        self._server.fail_vision = value

    @property
    def chat_delay(self) -> float:
        """每個 chat 請求處理前的延遲秒數，用來讓並行行為可被觀察。"""
        return self._server.chat_delay

    @chat_delay.setter
    def chat_delay(self, value: float) -> None:
        self._server.chat_delay = value

    @property
    def embed_delay(self) -> float:
        """每個 embeddings 請求處理前的延遲秒數，用來讓並行行為可被觀察。"""
        return self._server.embed_delay

    @embed_delay.setter
    def embed_delay(self, value: float) -> None:
        self._server.embed_delay = value

    @property
    def die_after_chat(self) -> int | None:
        """設為 N 時模擬生成執行緒死掉：前 N 個 chat 請求正常，第 N+1 個永遠不回應，之後的回 404。"""
        return self._server.die_after_chat

    @die_after_chat.setter
    def die_after_chat(self, value: int | None) -> None:
        self._server.die_after_chat = value

    @property
    def base_url(self) -> str:
        """可直接填入 *_BASE_URL 的位址（含 /v1）。"""
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1"

    def start(self) -> None:
        """啟動背景 thread 開始接受請求。"""
        self._thread.start()

    def stop(self) -> None:
        """停止 server 並釋放埠；die_after_chat 卡住的請求一併放開。"""
        self._server.stalled.set()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()

    def __enter__(self) -> "FakeOpenAIServer":
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()
