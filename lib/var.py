"""
风险度量库：VaR / CVaR / 波动率 / 压力测试 / 阈值预警 / 防守建议。

纯计算函数，无 API 调用。输入日收益率序列，输出风险指标。
"""

from typing import Dict, List, Optional

import numpy as np

try:
    from scipy.stats import norm as _norm
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


def parametric_var(returns: np.ndarray, confidence: float = 0.95) -> float:
    """
    参数法 VaR: μ - z_α × σ

    假设正态分布。返回负数表示损失（如 -0.033 = -3.3%）。
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 5:
        return 0.0
    mu = np.mean(arr)
    sigma = np.std(arr, ddof=1)
    if _HAS_SCIPY:
        z_alpha = _norm.ppf(1 - confidence)
    else:
        # 近似: z_0.05 ≈ -1.645
        z_map = {0.95: -1.6449, 0.99: -2.3263, 0.90: -1.2816}
        z_alpha = z_map.get(confidence, -1.6449)
    return round(float(mu + z_alpha * sigma), 6)


def historical_var(returns: np.ndarray, confidence: float = 0.95) -> float:
    """
    历史模拟法 VaR: 取收益率序列的 (1-confidence) 分位数。

    返回负数表示损失。
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 5:
        return 0.0
    pct = (1 - confidence) * 100
    return round(float(np.percentile(arr, pct)), 6)


def cvar(returns: np.ndarray, confidence: float = 0.95) -> float:
    """
    条件 VaR (Expected Shortfall): mean(returns[returns < VaR])

    衡量尾部风险均值，比 VaR 更保守。
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 5:
        return 0.0
    var = historical_var(arr, confidence)
    tail = arr[arr <= var]
    if len(tail) == 0:
        return var
    return round(float(np.mean(tail)), 6)


def volatility_regime(returns: np.ndarray, window: int = 20) -> Dict:
    """
    波动率状态判断：当前 vol 在历史中的百分位。

    Returns:
        {
            "current_vol": float (年化),
            "percentile": float (0-100),
            "regime": "LOW" / "MEDIUM" / "HIGH"
        }
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < window + 5:
        daily_vol = np.std(arr, ddof=1) if len(arr) > 1 else 0.0
        return {
            "current_vol": round(float(daily_vol * np.sqrt(252) * 100), 2),
            "percentile": 50.0,
            "regime": "MEDIUM",
        }

    # 滚动窗口波动率
    rolling_vols = []
    for i in range(window, len(arr) + 1):
        w = arr[i - window:i]
        rolling_vols.append(np.std(w, ddof=1))

    current_vol = rolling_vols[-1]
    percentile = float(np.sum(np.array(rolling_vols) < current_vol) / len(rolling_vols) * 100)

    if percentile <= 33:
        regime = "LOW"
    elif percentile <= 67:
        regime = "MEDIUM"
    else:
        regime = "HIGH"

    return {
        "current_vol": round(float(current_vol * np.sqrt(252) * 100), 2),
        "percentile": round(percentile, 1),
        "regime": regime,
    }


def stress_tests(
    returns: np.ndarray,
    beta: float = 1.0,
    scenarios: Optional[List[Dict]] = None,
) -> List[Dict]:
    """
    压力测试：模拟市场极端场景下的预期损失。

    默认3场景:
      1. 大盘暴跌: -20% × beta
      2. 板块轮动: -10%
      3. 加息冲击: -5%
    """
    if scenarios is None:
        scenarios = [
            {"name": "大盘暴跌(-20%)", "market_shock": -0.20},
            {"name": "板块轮动(-10%)", "market_shock": -0.10},
            {"name": "加息冲击(-5%)", "market_shock": -0.05},
        ]

    results = []
    for s in scenarios:
        shock = s["market_shock"]
        expected_loss = shock * beta
        results.append({
            "scenario": s["name"],
            "market_shock_pct": round(shock * 100, 1),
            "expected_loss_pct": round(expected_loss * 100, 1),
            "beta": beta,
        })

    return results


def risk_alerts(
    var95: float, cvar95: float, max_dd_pct: float, vol_regime: str,
) -> List[Dict]:
    """
    阈值预警：检查各项风险指标是否触发预警线。

    Args:
        var95: 参数法 VaR95（已乘100，如 -3.3 表示 -3.3%）
        cvar95: CVaR95（已乘100）
        max_dd_pct: 最大回撤百分比（正数，如 18.5）
        vol_regime: 波动率状态 LOW/MEDIUM/HIGH

    Returns:
        预警列表 [{level, metric, message}]
    """
    alerts = []
    if var95 < -4:
        alerts.append({"level": "HIGH", "metric": "VaR95",
                        "message": f"单日最大亏损风险{var95}%，超过-4%预警线"})
    if cvar95 < -6:
        alerts.append({"level": "HIGH", "metric": "CVaR",
                        "message": f"尾部风险均值{cvar95}%，极端行情损失严重"})
    if max_dd_pct > 20:
        alerts.append({"level": "HIGH", "metric": "MaxDrawdown",
                        "message": f"最大回撤{max_dd_pct}%，超过20%警戒线"})
    elif max_dd_pct > 15:
        alerts.append({"level": "MEDIUM", "metric": "MaxDrawdown",
                        "message": f"最大回撤{max_dd_pct}%，接近20%警戒线"})
    if vol_regime == "HIGH":
        alerts.append({"level": "MEDIUM", "metric": "Volatility",
                        "message": "当前处于高波动率区间，建议降低仓位"})
    return alerts


def defensive_suggestions(
    alerts: List[Dict], kelly_half: float, vol_regime: str,
) -> Dict:
    """
    根据风险等级生成防守建议。

    Returns:
        {risk_level, actions[], strategy, max_position_pct}
    """
    high_count = sum(1 for a in alerts if a["level"] == "HIGH")

    if high_count >= 2:
        risk_level = "高风险"
        actions = ["建议降低仓位至半仓以下", "设置严格止损", "考虑增加对冲头寸"]
        strategy = "防御型资产配置，严格止损，控制单笔亏损不超过总资产2%"
        cap = 5.0
    elif high_count == 1 or vol_regime == "HIGH":
        risk_level = "中高风险"
        actions = ["适当降低仓位", "收紧止损线", "关注波动率变化"]
        strategy = "稳健型配置，止损线收紧至1.5倍日波动率"
        cap = 8.0
    elif vol_regime == "MEDIUM":
        risk_level = "中等风险"
        actions = ["维持正常仓位", "常规止损即可"]
        strategy = "正常操作，Kelly/2仓位管理"
        cap = 10.0
    else:
        risk_level = "低风险"
        actions = ["可适当提高仓位", "止损可适度放宽"]
        strategy = "积极配置，可考虑Kelly仓位上浮"
        cap = 12.0

    return {
        "risk_level": risk_level,
        "actions": actions,
        "strategy": strategy,
        "max_position_pct": round(min(kelly_half * 100, cap), 1),
    }
