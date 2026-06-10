"""
禮貌爬蟲等待模組 — 模擬真人瀏覽節奏

統一所有 neko-pedia 爬蟲的延遲邏輯。
所有 delay 加 ±50% 隨機抖動，讓間隔不規律。
"""

import time
import random


def _jittered(base: float) -> float:
    """base 秒 +/- 50% 的隨機值"""
    return random.uniform(base * 0.5, base * 1.5)


def wait_page() -> float:
    """列表翻頁（2s +/-50% = 1~3s）"""
    delay = _jittered(2.0)
    time.sleep(delay)
    return delay


def wait_detail() -> float:
    """讀 detail 頁（3s +/-50% = 1.5~4.5s）"""
    delay = _jittered(3.0)
    time.sleep(delay)
    return delay


def wait_api() -> float:
    """API 呼叫間隔（1.5s +/-50% = 0.75~2.25s）"""
    delay = _jittered(1.5)
    time.sleep(delay)
    return delay
