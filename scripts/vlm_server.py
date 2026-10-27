"""啟動 VLM＋embedding 的 mlx_vlm.server，並限制 MLX 保留的 GPU buffer cache。

為什麼存在：mlx-vlm 的 embedding 路徑（server/embeddings.py，0.7.10 實測）處理完請求不呼叫
mx.clear_cache()，而 MLX 預設的 cache 上限等於記憶體上限（32 GB 機器上為 30.4 GB）。ingest
會連續送出數百個小型 embedding 請求，已釋放的 buffer 一直留在 cache，server footprint 從
5 GB 漲到 13 GB，與 mlx_lm.server 加起來把 32 GB 的機器推到 GPU 記憶體不足（ticket 03 調查）。
chat 路徑會清 cache，所以只有 embedding 期間會累積。

關鍵設計決策：
- 不修改已安裝的 mlx-vlm，只在同一個行程先設 cache 上限，再交給 mlx_vlm.server 原本的進入點。
  server 以 uvicorn workers=1 在同一個行程執行，MLX allocator 是全域的，所以設定套用到所有請求。
- 上限只限制「已釋放但保留著」的 cache，不影響正在使用的記憶體；超過時下一次配置會先回收。
  預設 1 GB：完整 ingest 一篇論文時，server footprint 最高 5.8 GB。

用法（以 pipx 安裝 mlx-vlm 的 python 執行，不是專案 venv）：
    ~/.local/share/pipx/venvs/mlx-vlm/bin/python scripts/vlm_server.py [--mlx-cache-limit-gb 1] \\
        --host 127.0.0.1 --port 8081 \\
        --model mlx-community/Qwen3-VL-4B-Instruct-4bit \\
        --embedding-model mlx-community/Qwen3-Embedding-0.6B-8bit
--mlx-cache-limit-gb 以外的參數原樣轉給 mlx_vlm.server。

已知極限：依賴 mlx_vlm.server 在同一個行程內執行；若之後的版本改成多行程（workers>1 或 reload），
cache 上限不會帶到子行程。

Dependencies: mlx、mlx-vlm（pipx 的 mlx-vlm venv）。
"""

import argparse
import sys

import mlx.core as mx
from mlx_vlm.server import main as server_main


def main() -> int:
    """設定 MLX cache 上限後啟動 mlx_vlm.server。

    Returns:
        server 的結束碼。
    """
    # allow_abbrev=False：避免把 mlx_vlm.server 的參數誤認成本腳本參數的縮寫
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
    parser.add_argument(
        "--mlx-cache-limit-gb", type=float, default=1.0, help="MLX 保留的 GPU buffer cache 上限（GB），預設 1"
    )
    args, server_args = parser.parse_known_args()
    if args.mlx_cache_limit_gb < 0:
        parser.error("--mlx-cache-limit-gb 不能是負數")
    limit_bytes = int(args.mlx_cache_limit_gb * 1024**3)
    previous = mx.set_cache_limit(limit_bytes)
    print(
        f"MLX cache limit: {previous / 1024**3:.1f} GB -> {limit_bytes / 1024**3:.1f} GB", file=sys.stderr, flush=True
    )
    sys.argv = ["mlx_vlm.server", *server_args]
    return server_main()


if __name__ == "__main__":
    sys.exit(main())
