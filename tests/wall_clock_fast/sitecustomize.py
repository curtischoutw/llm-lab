"""測試夾具：讓牆上時鐘（`time.time`）比 `time.perf_counter` 走得快很多，模擬電腦睡眠。

為什麼存在：Mac 睡眠時 `time.time` 繼續走、`time.perf_counter` 停住，所以用牆上時鐘量的時間會比
`perf_counter` 量的長。測試不能真的讓機器睡眠，改在子行程啟動時把 `time.time` 換成「以啟動時刻為起點、
走得快 N 倍」的版本，`perf_counter` 不動；任何用 `time.time` 量出來的區間都會比實際長 N 倍。

使用方式：把這個資料夾放進子行程的 `PYTHONPATH`，並設環境變數 `WALL_CLOCK_SPEED`（倍數）；Python 啟動時
自動載入 `sitecustomize`。沒設 `WALL_CLOCK_SPEED` 就什麼都不做。

已知極限：只換 `time.time`；`time.monotonic`、event loop 的計時與 `perf_counter` 不受影響（這正是要的）。

Dependencies: 僅標準函式庫。
"""

import os
import time

_speed = os.environ.get("WALL_CLOCK_SPEED")
if _speed:
    _factor = float(_speed)
    _real_time = time.time
    _start = _real_time()
    time.time = lambda: _start + (_real_time() - _start) * _factor
