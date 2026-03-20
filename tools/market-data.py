#!/usr/bin/env python3
"""
行情 + 基本面 + K线 + 同业数据采集工具。

合并旧 Skill 1 (行情抓取) + Skill 2 (基本面解析) + K线 + 同业对比。

用法:
    python3 tools/market-data.py --input in.json --output out.json

输入 JSON:
    {"stock_name": "比亚迪", "stock_code": "002594", "kline_days": 60}

输出 JSON:
    {quote, financials, kline_summary, peers, pe_history, technical, stock_code}
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
VENDORS_DIR = BASE_DIR / "vendors"
FINDATA_SCRIPT = str(VENDORS_DIR / "mx-findata" / "get_data.py")

# Add lib to path
sys.path.insert(0, str(BASE_DIR))

# 确保 EM_API_KEY 可用
from lib.config import ensure_em_api_key
ensure_em_api_key()


def _json_serializer(obj):
    """自定义 JSON 序列化，处理 numpy 类型但不把 int 变成 str。"""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _run_findata(query: str) -> str | None:
    result = subprocess.run(
        [sys.executable, FINDATA_SCRIPT, "--query", query],
        capture_output=True, text=True, timeout=30,
    )
    for line in result.stdout.strip().split("\n"):
        if line.startswith("文件:"):
            return line.split(":", 1)[1].strip()
    return None


def _read_xlsx(path: str | None) -> pd.DataFrame | None:
    if path and os.path.isfile(path):
        return pd.read_excel(path)
    return None


def _parse_num(val) -> float | None:
    if val is None:
        return None
    s = str(val).replace(",", "").replace("亿元", "").replace("亿", "").replace("万元", "").replace("%", "").strip()
    if s in ("-", "", "nan"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _extract_code(dfs: list) -> str:
    for df in dfs:
        if df is None:
            continue
        for col in df.columns:
            m = re.search(r"(\d{6}\.\w{2})", str(col))
            if m:
                return m.group(1)
    return ""


def _extract_rows(df, mapping, raw_data):
    if df is None:
        return
    for _, row in df.iterrows():
        key = str(row.iloc[0]).strip()
        val = row.iloc[1] if df.shape[1] > 1 else None
        for keyword, field in mapping.items():
            if keyword in key:
                raw_data[field] = _parse_num(val)
                break


def run(input_data: dict) -> dict:
    stock_name = input_data["stock_name"]
    stock_code = input_data.get("stock_code", "")
    kline_days = input_data.get("kline_days", 60)

    # ── 基本面数据采集 ──
    print(f"[market-data] 采集 {stock_name} 数据...")

    xlsx_quote = _run_findata(f"{stock_name}最新价、涨跌幅、成交量、成交额、换手率")
    xlsx_fund = _run_findata(f"{stock_name}主力资金净流入")
    xlsx_fin = _run_findata(f"{stock_name}最近4个季度营业收入、净利润、毛利率")
    xlsx_val = _run_findata(f"{stock_name}市盈率TTM、市净率、股息率、市盈率动态")
    xlsx_roe = _run_findata(f"{stock_name}ROE、经营现金流净额")
    # Fix #7: 增加增速指标查询
    xlsx_growth = _run_findata(f"{stock_name}营业收入同比增长率、净利润同比增长率")

    df_quote = _read_xlsx(xlsx_quote)
    df_fund = _read_xlsx(xlsx_fund)
    df_fin = _read_xlsx(xlsx_fin)
    df_val = _read_xlsx(xlsx_val)
    df_roe = _read_xlsx(xlsx_roe)
    df_growth = _read_xlsx(xlsx_growth)

    detected_code = stock_code or _extract_code([df_quote, df_val, df_fin, df_roe, df_fund, df_growth])
    raw = {"code": detected_code or stock_name}

    _extract_rows(df_quote, {"最新价": "price", "成交额": "volume_amount", "换手率": "turnover_rate"}, raw)
    _extract_rows(df_fund, {"主力": "main_net_inflow"}, raw)
    _extract_rows(df_fin, {"营业收入": "revenue", "净利润": "net_profit", "毛利率": "gross_margin"}, raw)
    # Fix #8 & #9: 更宽松的关键词匹配，覆盖"市盈率(动态)"、"市盈率TTM"等变体
    _extract_rows(df_val, {"市净率": "pb_mrq", "市盈率": "pe_ttm", "股息率": "dividend_yield"}, raw)
    _extract_rows(df_roe, {"ROE": "roe", "现金流": "operating_cashflow"}, raw)
    # Fix #7: 提取增速指标
    _extract_rows(df_growth, {
        "营业收入同比": "revenue_yoy",
        "营收同比": "revenue_yoy",
        "收入增长": "revenue_yoy",
        "净利润同比": "profit_yoy",
        "利润增长": "profit_yoy",
    }, raw)

    # 如果增速查询失败，尝试从财务数据二次提取
    if df_growth is not None:
        for _, row in df_growth.iterrows():
            key = str(row.iloc[0]).strip()
            val = row.iloc[1] if df_growth.shape[1] > 1 else None
            parsed = _parse_num(val)
            if parsed is None:
                continue
            if "revenue_yoy" not in raw and ("营收" in key or "收入" in key) and "同比" in key:
                raw["revenue_yoy"] = parsed
            if "profit_yoy" not in raw and ("利润" in key) and "同比" in key:
                raw["profit_yoy"] = parsed

    print(f"[market-data] 基本面: {', '.join(k for k in ['pe_ttm', 'pb_mrq', 'roe', 'revenue_yoy', 'profit_yoy', 'dividend_yield'] if raw.get(k) is not None)}")

    # ── K线数据 ──
    print(f"[market-data] K线数据...")
    pure_code = detected_code.split(".")[0] if detected_code and "." in detected_code else (stock_code or stock_name)

    kline_data = {}
    technical = {"trend": "-", "momentum": "-", "recent_signals": []}
    volumes = []  # Fix #4: 保存真实成交量数据
    try:
        from vendors.baostock_adapter import fetch_kline
        from lib.indicators import calc_all_indicators
        from lib.signals import get_technical_summary

        df_kline = fetch_kline(pure_code, days=kline_days)

        # ── 数据清洗：补缺、去异常 ──
        if not df_kline.empty:
            # 去除成交量为0的异常交易日（停牌日）
            df_kline = df_kline[df_kline["volume"] > 0].copy()
            # 去极端值：单日涨跌幅超过22%的标记为异常（A股涨跌停10%/20%+容差）
            if "change_pct" in df_kline.columns:
                df_kline = df_kline[df_kline["change_pct"].abs() <= 22].copy()
            # 补缺：收盘价用前值填充
            df_kline["close"] = df_kline["close"].ffill()
            df_kline = df_kline.reset_index(drop=True)

        df_kline = calc_all_indicators(df_kline)
        technical = get_technical_summary(df_kline)

        # 收益率序列
        changes = df_kline["change_pct"].dropna().values / 100
        closes = df_kline["close"].values
        volumes = df_kline["volume"].values.astype(float).tolist()
        dates = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for d in df_kline["date"]]

        kline_data = {
            "days": len(df_kline),
            "returns": changes.tolist(),
            "closes": closes.tolist(),
            "volumes": volumes,  # Fix #4: 输出真实成交量
            "dates": dates,
            "latest_close": float(closes[-1]),
        }
        print(f"[market-data] K线: {len(df_kline)}条, 趋势={technical['trend']}")
    except Exception as e:
        print(f"[market-data] K线失败: {e}")

    # ── 同业对比 ──  Fix #2: 修复 peers 导入
    print(f"[market-data] 同业对比...")
    peers_data = {}
    pe_history_data = {}
    try:
        from vendors.peer.get_peers import get_full_peer_analysis
        pe_ttm = raw.get("pe_ttm", 20) or 20
        peer_result = get_full_peer_analysis(stock_name, pe_ttm)

        peers_data = {
            "industry": peer_result.get("industry", "未知"),
            "peers": peer_result.get("peers", []),
        }
        # 传递 sector_metrics 供 factor-engine 使用
        if peer_result.get("sector_metrics"):
            peers_data["sector_metrics"] = peer_result["sector_metrics"]

        print(f"[market-data] 同业: {len(peers_data.get('peers', []))} 家, 行业={peers_data.get('industry', '未知')}")
    except Exception as e:
        print(f"[market-data] 同业对比失败: {e}")

    return {
        "stock_name": stock_name,
        "stock_code": detected_code,
        "quote": raw,
        "kline": kline_data,
        "technical": technical,
        "peers": peers_data,
        "pe_history": pe_history_data,
    }


def main():
    parser = argparse.ArgumentParser(description="行情+基本面+K线+同业数据采集")
    parser.add_argument("--input", required=True, help="输入 JSON 文件")
    parser.add_argument("--output", required=True, help="输出 JSON 文件")
    args = parser.parse_args()

    input_data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = run(input_data)

    # Fix #10: 使用自定义序列化器，不再用 default=str
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=_json_serializer),
        encoding="utf-8",
    )
    print(f"[market-data] 输出: {args.output}")


if __name__ == "__main__":
    main()
