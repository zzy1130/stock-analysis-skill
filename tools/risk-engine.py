#!/usr/bin/env python3
"""
风险分析引擎：VaR / CVaR / 压力测试 / Kelly 仓位。

替代旧 run_analysis.py 的 4 个 bool flag 计数风控。

用法:
    python3 tools/risk-engine.py --input market-data.json --output risk.json

输入: market-data.py 输出的 JSON
输出: {var_95, cvar_95, max_drawdown{}, volatility{}, stress_tests[], kelly, stop_loss}
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))


def run(market_data: dict) -> dict:
    from lib.var import parametric_var, historical_var, cvar, volatility_regime, stress_tests, risk_alerts, defensive_suggestions
    from lib.drawdown import max_drawdown
    from lib.kelly import kelly_from_returns, stop_loss_price

    kline = market_data.get("kline", {})
    returns = np.array(kline.get("returns", []))
    closes = np.array(kline.get("closes", []))
    dates = kline.get("dates", [])

    if len(returns) < 5:
        print("[risk-engine] 数据不足，跳过风险分析")
        return {"error": "insufficient_data"}

    # VaR / CVaR
    var95 = parametric_var(returns, 0.95)
    hist_var95 = historical_var(returns, 0.95)
    cvar95 = cvar(returns, 0.95)

    # 波动率
    vol = volatility_regime(returns)

    # 最大回撤
    dd = max_drawdown(closes, dates)

    # 压力测试 — 用个股年化 vol 估算 beta (市场平均年化 vol ≈ 20%)
    daily_vol = np.std(returns, ddof=1) if len(returns) > 1 else 0.02
    annual_vol = daily_vol * np.sqrt(252)
    market_annual_vol = 0.20  # A 股长期平均年化波动率 ~20%
    beta = round(min(max(annual_vol / market_annual_vol, 0.3), 2.5), 2)  # 限制 0.3-2.5
    stress = stress_tests(returns, beta)

    # Kelly 仓位
    kelly = kelly_from_returns(returns)

    # 止损价
    latest_close = float(closes[-1]) if len(closes) > 0 else 0
    stop = stop_loss_price(latest_close, daily_vol)

    result = {
        "var_95_parametric": round(var95 * 100, 2),
        "var_95_historical": round(hist_var95 * 100, 2),
        "cvar_95": round(cvar95 * 100, 2),
        "max_drawdown": dd,
        "volatility": vol,
        "stress_tests": stress,
        "kelly": kelly,
        "stop_loss": stop,
        "latest_close": latest_close,
    }

    # 阈值预警 + 防守建议
    alerts = risk_alerts(
        result["var_95_parametric"], result["cvar_95"],
        dd["max_dd_pct"], vol["regime"],
    )
    defense = defensive_suggestions(alerts, kelly["kelly_half"], vol["regime"])
    result["alerts"] = alerts
    result["defense"] = defense

    print(f"[risk-engine] VaR95: {result['var_95_parametric']}%, CVaR: {result['cvar_95']}%")
    print(f"[risk-engine] MaxDD: {dd['max_dd_pct']}%, Vol: {vol['regime']}")
    print(f"[risk-engine] Kelly/2: {kelly['kelly_half']}, 止损: {stop}")
    print(f"[risk-engine] 风险等级: {defense['risk_level']}, 预警: {len(alerts)}条")

    return result


def main():
    parser = argparse.ArgumentParser(description="风险分析引擎")
    parser.add_argument("--input", required=True, help="market-data 输出 JSON")
    parser.add_argument("--output", required=True, help="输出 JSON 文件")
    args = parser.parse_args()

    market_data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = run(market_data)

    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[risk-engine] 输出: {args.output}")


if __name__ == "__main__":
    main()
