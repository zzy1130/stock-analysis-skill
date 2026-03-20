#!/usr/bin/env python3
"""
合并所有工具输出为 combined.json，供 report-pdf.py 使用。

避免手动拼接 JSON 导致字段丢失。

用法:
    python3 tools/assemble.py \
        --market market.json \
        --factor factor.json \
        --risk risk.json \
        --signal signal.json \
        --sentiment sentiment.json \
        --output combined.json

注意: insights 和 section_insights 字段需要由 LLM 在调用前写入 sentiment.json
或通过 --insights 参数传入单独的 JSON 文件。
"""

import argparse
import json
from pathlib import Path


def assemble(
    market_path: str,
    factor_path: str,
    risk_path: str,
    signal_path: str,
    sentiment_path: str,
    insights_path: str | None = None,
) -> dict:
    market = json.loads(Path(market_path).read_text(encoding="utf-8"))
    factor = json.loads(Path(factor_path).read_text(encoding="utf-8"))
    risk = json.loads(Path(risk_path).read_text(encoding="utf-8"))
    signal = json.loads(Path(signal_path).read_text(encoding="utf-8"))
    sentiment = json.loads(Path(sentiment_path).read_text(encoding="utf-8"))

    # 股票代码格式化
    stock_code = market.get("stock_code", "")
    if stock_code and "." not in stock_code:
        if stock_code.startswith(("60", "68")):
            stock_code = f"{stock_code}.SH"
        else:
            stock_code = f"{stock_code}.SZ"

    combined = {
        "stock_name": market.get("stock_name", ""),
        "stock_code": stock_code,
        # 完整的因子评分数据（包含所有 sub_factors 的 score, z, method, value, weight）
        "factor_scores": factor,
        # 完整的风险数据
        "risk": risk,
        # 完整的信号数据
        "signal": signal,
        # 完整的情绪数据（包含 items 的 score 字段）
        "sentiment": sentiment.get("sentiment", {}),
        # 完整的事件数据（包含 chain 字段）
        "events": sentiment.get("events", []),
        # 券商评级
        "analyst_ratings": sentiment.get("analyst_ratings", []),
        # K线数据
        "kline": market.get("kline", {}),
        # 技术面数据（trend, momentum, recent_signals, latest_indicators）
        "technical": market.get("technical", {}),
        # 同业对比
        "peers": market.get("peers", {}),
        # PE 历史
        "pe_history": market.get("pe_history", {}),
        # 基本面原始数据
        "quote": market.get("quote", {}),
    }

    # 加载 LLM 撰写的 insights
    if insights_path:
        insights_data = json.loads(Path(insights_path).read_text(encoding="utf-8"))
        combined["insights"] = insights_data.get("insights", "")
        combined["section_insights"] = insights_data.get("section_insights", {})

    return combined


def main():
    parser = argparse.ArgumentParser(description="合并所有工具输出为 combined.json")
    parser.add_argument("--market", required=True, help="market-data 输出 JSON")
    parser.add_argument("--factor", required=True, help="factor-engine 输出 JSON")
    parser.add_argument("--risk", required=True, help="risk-engine 输出 JSON")
    parser.add_argument("--signal", required=True, help="portfolio-signal 输出 JSON")
    parser.add_argument("--sentiment", required=True, help="news-sentiment 输出 JSON")
    parser.add_argument("--insights", default=None, help="LLM 撰写的 insights JSON（可选）")
    parser.add_argument("--output", required=True, help="输出 combined.json 路径")
    args = parser.parse_args()

    combined = assemble(
        args.market, args.factor, args.risk, args.signal, args.sentiment, args.insights,
    )

    Path(args.output).write_text(
        json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    # 验证关键字段
    issues = []
    items = combined.get("sentiment", {}).get("items", [])
    if items and "score" not in items[0]:
        issues.append("sentiment.items 缺少 score 字段")
    events = combined.get("events", [])
    if events and "chain" not in events[0]:
        issues.append("events 缺少 chain 字段")
    if not combined.get("insights"):
        issues.append("缺少 insights（需要 LLM 撰写后通过 --insights 传入）")

    if issues:
        print(f"[assemble] ⚠ 数据校验警告:")
        for i in issues:
            print(f"  - {i}")
    else:
        print(f"[assemble] ✓ 数据完整性校验通过")

    print(f"[assemble] 输出: {args.output}")


if __name__ == "__main__":
    main()
