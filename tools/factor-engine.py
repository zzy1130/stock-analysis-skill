#!/usr/bin/env python3
"""
Z-score 多因子评分引擎。

替代旧 run_analysis.py 的 if/else 绝对阈值评分。

用法:
    python3 tools/factor-engine.py --input market-data.json --output factor-scores.json

输入: market-data.py 输出的 JSON
输出: {total, label, growth{score, z, sub_factors}, value{...}, quality{...}, momentum{...}}
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))


def _build_stock_metrics(market_data: dict) -> dict:
    """从 market-data 输出提取因子评分所需的指标。"""
    quote = market_data.get("quote", {})
    kline = market_data.get("kline", {})
    technical = market_data.get("technical", {})

    metrics = {}

    # Fix #3: Growth 因子 — 使用真实增速字段，不再用 ROE 冒充
    metrics["revenue_yoy"] = quote.get("revenue_yoy")  # None if missing
    metrics["profit_yoy"] = quote.get("profit_yoy")    # None if missing
    metrics["revenue_3y_cagr"] = quote.get("revenue_3y_cagr")  # None if missing

    # Value 因子
    pe = quote.get("pe_ttm")
    pb = quote.get("pb_mrq")
    metrics["pe_inverse"] = 1.0 / pe if pe and pe > 0 else None
    metrics["pb_inverse"] = 1.0 / pb if pb and pb > 0 else None
    metrics["dividend_yield"] = quote.get("dividend_yield")
    metrics["ev_ebitda_inverse"] = None  # 需要 EV/EBITDA 数据

    # Quality 因子
    metrics["roe"] = quote.get("roe")
    metrics["gross_margin"] = quote.get("gross_margin")
    ocf = quote.get("operating_cashflow")
    np_val = quote.get("net_profit")
    if ocf is not None and np_val is not None and np_val != 0:
        metrics["ocf_to_profit"] = ocf / np_val * 100
    else:
        metrics["ocf_to_profit"] = None
    metrics["roe_stability"] = None  # 需要多期 ROE 数据

    # Momentum 因子
    returns = kline.get("returns", [])
    if len(returns) >= 20:
        metrics["return_20d"] = float(np.prod([1 + r for r in returns[-20:]]) - 1) * 100
    else:
        metrics["return_20d"] = None

    if len(returns) >= 60:
        metrics["return_60d"] = float(np.prod([1 + r for r in returns[-60:]]) - 1) * 100
    else:
        metrics["return_60d"] = metrics.get("return_20d")

    indicators = technical.get("latest_indicators", {})
    rsi = indicators.get("RSI")
    metrics["rsi_distance"] = abs(rsi - 50) if rsi is not None else None

    # Fix #4: 量能趋势 — 使用真实成交量数据
    volumes = kline.get("volumes", [])
    if len(volumes) >= 20:
        # 近5日均量 / 近20日均量 × 100
        recent_avg = np.mean(volumes[-5:]) if len(volumes) >= 5 else np.mean(volumes)
        longer_avg = np.mean(volumes[-20:])
        metrics["volume_trend"] = (recent_avg / longer_avg * 100) if longer_avg > 0 else 100
    elif len(returns) >= 20:
        # 降级：用收益率波动作为代理（仅在无成交量数据时）
        recent_vol = np.std(returns[-5:]) if len(returns) >= 5 else 0
        longer_vol = np.std(returns[-20:])
        metrics["volume_trend"] = (recent_vol / longer_vol * 100) if longer_vol > 0 else 100
    else:
        metrics["volume_trend"] = None

    return metrics


def _build_sector_metrics(market_data: dict) -> dict | None:
    """Fix #5: 从同业对比数据构建行业指标数组，供 z-score 使用。"""
    peers = market_data.get("peers", {})
    sector_metrics = peers.get("sector_metrics")

    if not sector_metrics:
        return None

    # 转换 list 为 numpy array
    result = {}
    for key, values in sector_metrics.items():
        if isinstance(values, list) and len(values) >= 3:
            result[key] = np.array(values)

    return result if result else None


def run(market_data: dict) -> dict:
    from lib.zscore import compute_all_factors, load_factor_config

    config_path = str(BASE_DIR / "templates" / "factor-weights.json")
    config = load_factor_config(config_path)

    stock_metrics = _build_stock_metrics(market_data)
    sector_metrics = _build_sector_metrics(market_data)

    result = compute_all_factors(stock_metrics, sector_metrics, config)

    # 标注数据可用性
    quote = market_data.get("quote", {})
    has_fundamentals = any(quote.get(k) is not None for k in ["pe_ttm", "roe", "gross_margin", "pb_mrq"])
    has_growth = any(quote.get(k) is not None for k in ["revenue_yoy", "profit_yoy"])
    has_peers = bool(sector_metrics)

    missing_notes = []
    if not has_fundamentals:
        missing_notes.append("基本面数据不可用(API限额)")
    if not has_growth:
        missing_notes.append("增速数据缺失，Growth因子降级为默认5.5分")
    if not has_peers:
        missing_notes.append("无同业数据，使用绝对评分而非z-score行业对比")

    result["_data_availability"] = {
        "fundamentals": has_fundamentals,
        "growth_rates": has_growth,
        "kline": len(market_data.get("kline", {}).get("returns", [])) >= 20,
        "peers": has_peers,
        "note": "；".join(missing_notes) if missing_notes else "",
    }

    print(f"[factor-engine] 总分: {result['total']}/10 ({result['label']})")
    for name in ["growth", "value", "quality", "momentum"]:
        if name in result:
            print(f"  {name}: {result[name]['score']}")
    if missing_notes:
        for note in missing_notes:
            print(f"  ⚠ {note}")

    return result


def main():
    parser = argparse.ArgumentParser(description="Z-score 多因子评分")
    parser.add_argument("--input", required=True, help="market-data 输出 JSON")
    parser.add_argument("--output", required=True, help="输出 JSON 文件")
    args = parser.parse_args()

    market_data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = run(market_data)

    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[factor-engine] 输出: {args.output}")


if __name__ == "__main__":
    main()
