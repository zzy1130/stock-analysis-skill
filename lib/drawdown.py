"""
最大回撤分析。

纯计算函数，输入价格序列，输出回撤统计。
"""

from typing import List, Optional

import numpy as np


def max_drawdown(prices: np.ndarray, dates: Optional[List[str]] = None) -> dict:
    """
    计算最大回撤及相关日期。

    Args:
        prices: 收盘价序列
        dates: 对应日期字符串列表 (可选)

    Returns:
        {
            "max_dd_pct": float,       # 最大回撤百分比 (正数，如 18.5)
            "peak_date": str,          # 高点日期
            "trough_date": str,        # 低点日期
            "recovery_date": str|None, # 恢复日期 (未恢复则 None)
            "recovery_days": int|None, # 恢复天数
            "current_dd_pct": float,   # 当前回撤
        }
    """
    arr = np.asarray(prices, dtype=float)
    n = len(arr)
    if n < 2:
        return {
            "max_dd_pct": 0.0, "peak_date": None, "trough_date": None,
            "recovery_date": None, "recovery_days": None, "current_dd_pct": 0.0,
        }

    running_max = np.maximum.accumulate(arr)
    drawdowns = (running_max - arr) / running_max

    # 最大回撤
    max_dd_idx = np.argmax(drawdowns)
    max_dd_pct = round(float(drawdowns[max_dd_idx]) * 100, 2)

    # 高点：最大回撤低点之前的最高点
    peak_idx = np.argmax(arr[:max_dd_idx + 1])

    # 恢复日期：低点之后第一次价格回到高点水平
    recovery_idx = None
    peak_price = arr[peak_idx]
    for i in range(max_dd_idx + 1, n):
        if arr[i] >= peak_price:
            recovery_idx = i
            break

    # 当前回撤
    current_dd_pct = round(float((running_max[-1] - arr[-1]) / running_max[-1]) * 100, 2)

    def _date_at(idx):
        if dates and idx is not None and idx < len(dates):
            return dates[idx]
        return str(idx) if idx is not None else None

    recovery_days = None
    if recovery_idx is not None:
        recovery_days = recovery_idx - max_dd_idx

    return {
        "max_dd_pct": max_dd_pct,
        "peak_date": _date_at(peak_idx),
        "trough_date": _date_at(max_dd_idx),
        "recovery_date": _date_at(recovery_idx),
        "recovery_days": recovery_days,
        "current_dd_pct": current_dd_pct,
    }
