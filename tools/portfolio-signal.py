#!/usr/bin/env python3
"""
综合买卖信号 + 仓位建议 + 调仓节奏 + 约束校验。

整合因子评分 + 风险引擎 + 事件/情绪输出，给出操作建议。

用法:
    python3 tools/portfolio-signal.py --factor factor.json --risk risk.json --output signal.json
    python3 tools/portfolio-signal.py --factor factor.json --risk risk.json --sentiment sentiment.json --output signal.json

输出: {action, conviction, entry_range, target, stop_loss, position_size_pct, risk_reward, constraints, pacing}
"""

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))


def run(factor_data: dict, risk_data: dict, sentiment_data: dict = None) -> dict:
    total_score = factor_data.get("total", 5.0)
    label = factor_data.get("label", "待观察")

    vol_regime = risk_data.get("volatility", {}).get("regime", "MEDIUM")
    max_dd = risk_data.get("max_drawdown", {}).get("max_dd_pct", 0)
    var95 = risk_data.get("var_95_parametric", -3.0)
    kelly_half = risk_data.get("kelly", {}).get("kelly_half", 0.05)
    stop_loss = risk_data.get("stop_loss", 0)
    latest_close = risk_data.get("latest_close", 0)

    # ── 风险惩罚 ──
    risk_penalty = 0
    if vol_regime == "HIGH":
        risk_penalty += 1
    if max_dd > 20:
        risk_penalty += 1
    if var95 < -5:
        risk_penalty += 1

    # ── 事件影响调整 ──
    event_adjustment = 0
    if sentiment_data:
        events = sentiment_data.get("events", [])
        for evt in events:
            impact = evt.get("impact", "中性")
            if "负面" in impact:
                event_adjustment -= 0.5
            elif "正面" in impact:
                event_adjustment += 0.3

        temp = sentiment_data.get("sentiment", {}).get("temperature", 50)
        if temp > 80:
            event_adjustment -= 0.5  # 过热拥挤风险
        elif temp < -30:
            event_adjustment += 0.3  # 恐慌可能是机会

    adjusted_score = total_score - risk_penalty * 0.5 + event_adjustment

    # ── 操作方向 ──
    if adjusted_score >= 7.0 and risk_penalty <= 1:
        action = "BUY"
        conviction = "Strong"
    elif adjusted_score >= 5.5:
        action = "BUY"
        conviction = "Moderate"
    elif adjusted_score >= 4.0:
        action = "HOLD"
        conviction = "Neutral"
    elif adjusted_score >= 3.0:
        action = "REDUCE"
        conviction = "Moderate"
    else:
        action = "SELL"
        conviction = "Strong"

    # ── 价格目标 ──
    if latest_close > 0:
        if action == "BUY":
            target_pct = 0.15 + (adjusted_score - 5) * 0.03
            target = round(latest_close * (1 + max(target_pct, 0.05)), 2)
            entry_low = round(latest_close * 0.97, 2)
            entry_high = round(latest_close * 1.02, 2)
        elif action in ("HOLD", "REDUCE"):
            target = round(latest_close * 1.05, 2)
            entry_low = round(latest_close * 0.95, 2)
            entry_high = round(latest_close, 2)
        else:
            target = round(latest_close * 0.90, 2)
            entry_low = 0
            entry_high = 0
    else:
        target = 0
        entry_low = entry_high = 0

    # ── 仓位 ──
    position_pct = round(min(kelly_half * 100, 10.0), 2)  # 上限 10%
    if vol_regime == "HIGH":
        position_pct = round(position_pct * 0.6, 2)

    # ── 风险回报比 ──
    risk_amt = abs(latest_close - stop_loss) if stop_loss else latest_close * 0.08
    reward_amt = abs(target - latest_close) if target else latest_close * 0.15
    risk_reward = round(reward_amt / risk_amt, 1) if risk_amt > 0 else 0

    # ── 约束校验 ──
    constraints = []
    if position_pct > 10:
        position_pct = 10.0
        constraints.append("单票仓位上限10%")
    if action == "BUY" and vol_regime == "HIGH" and max_dd > 15:
        action = "HOLD"
        conviction = "Cautious"
        constraints.append("高波+大回撤，BUY降级为HOLD")
    if risk_reward < 1.5 and action == "BUY":
        conviction = "Weak"
        constraints.append("风险回报比<1.5，信心降级")
    if event_adjustment < -0.5:
        constraints.append("多项负面事件叠加，建议观望")

    # ── 调仓节奏 ──
    if action == "BUY":
        if conviction == "Strong":
            pacing = "可一次性建仓60%，剩余40%回调时补仓"
        elif conviction == "Moderate":
            pacing = "建议分3次建仓(40%/30%/30%)，间隔3-5个交易日"
        else:
            pacing = "建议小仓试探(20%)，确认趋势后再加仓"
    elif action == "REDUCE":
        pacing = "建议分2次减仓，先减50%观察"
    elif action == "SELL":
        pacing = "建议尽快清仓，分2批执行降低冲击成本"
    else:
        pacing = "维持现有仓位，无需调整"

    result = {
        "action": action,
        "conviction": conviction,
        "total_score": total_score,
        "adjusted_score": round(adjusted_score, 1),
        "risk_penalty": risk_penalty,
        "event_adjustment": round(event_adjustment, 1),
        "entry_range": [entry_low, entry_high],
        "target": target,
        "stop_loss": stop_loss,
        "position_size_pct": position_pct,
        "risk_reward": risk_reward,
        "constraints": constraints,
        "pacing": pacing,
    }

    print(f"[portfolio-signal] {action} ({conviction}) | Score: {total_score} → {adjusted_score}")
    print(f"  Entry: {entry_low}-{entry_high} | Target: {target} | Stop: {stop_loss}")
    print(f"  Position: {position_pct}% | R/R: {risk_reward}x")
    if event_adjustment != 0:
        print(f"  事件调整: {event_adjustment:+.1f}")
    if constraints:
        print(f"  约束: {' | '.join(constraints)}")
    print(f"  调仓: {pacing}")

    return result


def main():
    parser = argparse.ArgumentParser(description="综合买卖信号")
    parser.add_argument("--factor", required=True, help="factor-engine 输出 JSON")
    parser.add_argument("--risk", required=True, help="risk-engine 输出 JSON")
    parser.add_argument("--sentiment", default=None, help="news-sentiment 输出 JSON（可选）")
    parser.add_argument("--output", required=True, help="输出 JSON 文件")
    args = parser.parse_args()

    factor_data = json.loads(Path(args.factor).read_text(encoding="utf-8"))
    risk_data = json.loads(Path(args.risk).read_text(encoding="utf-8"))
    sentiment_data = None
    if args.sentiment:
        sentiment_data = json.loads(Path(args.sentiment).read_text(encoding="utf-8"))
    result = run(factor_data, risk_data, sentiment_data)

    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[portfolio-signal] 输出: {args.output}")


if __name__ == "__main__":
    main()
