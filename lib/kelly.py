"""
Kelly 仓位管理 + 止损计算。

纯计算函数，无 API 调用。
"""

import numpy as np


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """
    Kelly 公式: f* = (p × b - q) / b

    Args:
        win_rate: 胜率 (0-1)
        avg_win: 平均盈利幅度 (正数)
        avg_loss: 平均亏损幅度 (正数)

    Returns:
        最优仓位比例 (0-1)，负数表示不应投资
    """
    if avg_loss <= 0 or avg_win <= 0:
        return 0.0
    p = min(max(win_rate, 0.0), 1.0)
    q = 1.0 - p
    b = avg_win / avg_loss  # odds ratio
    f = (p * b - q) / b
    return round(max(f, 0.0), 4)


def half_kelly(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """保守仓位 = Kelly / 2，降低波动。"""
    return round(kelly_fraction(win_rate, avg_win, avg_loss) / 2, 4)


def kelly_from_returns(returns: np.ndarray) -> dict:
    """
    从历史收益率序列估算 Kelly 参数。

    Returns:
        {
            "win_rate": float,
            "avg_win": float,
            "avg_loss": float,
            "kelly_full": float,
            "kelly_half": float,
        }
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 10:
        return {
            "win_rate": 0.5, "avg_win": 0.0, "avg_loss": 0.0,
            "kelly_full": 0.0, "kelly_half": 0.0,
        }

    wins = arr[arr > 0]
    losses = arr[arr < 0]

    win_rate = len(wins) / len(arr) if len(arr) > 0 else 0.5
    avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
    avg_loss = float(np.mean(np.abs(losses))) if len(losses) > 0 else 0.0

    kf = kelly_fraction(win_rate, avg_win, avg_loss)

    return {
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 6),
        "avg_loss": round(avg_loss, 6),
        "kelly_full": kf,
        "kelly_half": round(kf / 2, 4),
    }


def stop_loss_price(price: float, daily_vol: float, holding_days: int = 10) -> float:
    """
    止损价计算: price × (1 - 2 × vol × √T)

    Args:
        price: 当前价格
        daily_vol: 日波动率 (如 0.02 = 2%)
        holding_days: 预期持有天数

    Returns:
        建议止损价
    """
    if daily_vol <= 0 or holding_days <= 0:
        return round(price * 0.92, 2)  # 默认8%止损
    loss_pct = 2.0 * daily_vol * np.sqrt(holding_days)
    loss_pct = min(loss_pct, 0.20)  # 上限20%
    return round(price * (1 - loss_pct), 2)


def position_size(
    portfolio_value: float,
    risk_pct: float,
    entry_price: float,
    stop_price: float,
) -> dict:
    """
    仓位计算：给定风险容忍度，计算可买入股数和金额。

    Args:
        portfolio_value: 总组合价值
        risk_pct: 单笔最大风险比例 (如 0.02 = 2%)
        entry_price: 入场价
        stop_price: 止损价

    Returns:
        {"shares": int, "amount": float, "position_pct": float}
    """
    risk_per_share = abs(entry_price - stop_price)
    if risk_per_share < 0.01:
        return {"shares": 0, "amount": 0.0, "position_pct": 0.0}

    max_risk = portfolio_value * risk_pct
    shares = int(max_risk / risk_per_share)
    # A股最小交易单位100股
    shares = (shares // 100) * 100
    amount = shares * entry_price
    position_pct = round(amount / portfolio_value * 100, 2) if portfolio_value > 0 else 0.0

    return {"shares": shares, "amount": round(amount, 2), "position_pct": position_pct}
