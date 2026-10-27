"""假 OpenAI 相容 server 的契約測試：用既有冒煙測試腳本當客戶端。

為什麼存在：假 server 是後續 ticket 所有快速測試的地基，必須確認它的行為與
真實 MLX server 的契約一致。scripts/smoke_test.py 已對真實 server 實測通過，
本身就是這份契約的可執行定義（chat、帶 base64 data URI 的 vision、embeddings
維度一致），所以直接以它為客戶端，而不是另寫一套重述契約的斷言。

關鍵設計決策：
- 同樣從 CLI（腳本的子行程）進入，只看結束碼與輸出，不碰 server 內部。
- 另以子行程送一個壞的 data URI，確認 vision 端點會拒絕，避免假 server
  對任何輸入都回成功而掩蓋後續 ticket 的圖片編碼錯誤。

Dependencies: 僅標準函式庫。
"""

import json
import os
import subprocess
import sys
import unittest
import urllib.error
import urllib.request

from tests.fake_openai_server import FakeOpenAIServer
from tests.test_cli import REPO_ROOT

EMBED_DIM = 1024


def smoke_env(server: FakeOpenAIServer) -> dict[str, str]:
    """組出讓冒煙測試腳本指向假 server 的環境變數。

    Args:
        server: 已啟動的假 server。

    Returns:
        完整子行程環境。
    """
    env = dict(os.environ)
    env.update(
        {
            "LLM_BASE_URL": server.base_url,
            "LLM_MODEL": "fake-llm",
            "VLM_BASE_URL": server.base_url,
            "VLM_MODEL": "fake-vlm",
            "EMBED_BASE_URL": server.base_url,
            "EMBED_MODEL": "fake-embed",
        }
    )
    return env


class FakeServerContractTest(unittest.TestCase):
    def test_smoke_script_passes_against_fake_server(self):
        with FakeOpenAIServer(embed_dim=EMBED_DIM) as server:
            result = subprocess.run(
                [sys.executable, "scripts/smoke_test.py"],
                cwd=REPO_ROOT,
                env=smoke_env(server),
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in ("test_chat", "test_vision", "test_embeddings"):
            self.assertIn(f"PASS {name}", result.stdout)
        self.assertIn(f"dim={{{EMBED_DIM}}}", result.stdout)

    def test_embedding_dimension_follows_configuration(self):
        with FakeOpenAIServer(embed_dim=8) as server:
            result = subprocess.run(
                [sys.executable, "scripts/smoke_test.py"],
                cwd=REPO_ROOT,
                env=smoke_env(server),
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertIn("dim={8}", result.stdout)

    def test_vision_rejects_malformed_data_uri(self):
        payload = {
            "model": "fake-vlm",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "describe"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,@@not-base64@@"}},
                    ],
                }
            ],
        }
        with FakeOpenAIServer(embed_dim=EMBED_DIM) as server:
            request = urllib.request.Request(
                f"{server.base_url}/chat/completions",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(request, timeout=10)
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
