"""
同业对比模块。

通过 mx-findata 获取同行业公司数据，用于 z-score 因子评分。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

VENDORS_DIR = Path(__file__).resolve().parent.parent
FINDATA_SCRIPT = str(VENDORS_DIR / "mx-findata" / "get_data.py")


def _run_findata(query: str) -> str | None:
    result = subprocess.run(
        [sys.executable, FINDATA_SCRIPT, "--query", query],
        capture_output=True, text=True, timeout=30,
    )
    for line in result.stdout.strip().split("\n"):
        if line.startswith("文件:"):
            return line.split(":", 1)[1].strip()
    return None


def _read_xlsx(path: str | None):
    if path and os.path.isfile(path):
        import pandas as pd
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


def get_full_peer_analysis(stock_name: str, pe_ttm: float = 20.0) -> dict:
    """
    获取同行业公司的关键指标。

    Returns:
        {
            "industry": str,
            "peers": [{"name": str, "pe": float, "pb": float, "roe": float, "gross_margin": float}],
            "comparison": DataFrame | None,
            "sector_metrics": {
                "pe_inverse": [float],
                "pb_inverse": [float],
                "roe": [float],
                "gross_margin": [float],
            }
        }
    """
    # 查询同行业公司
    xlsx_path = _run_findata(
        f"{stock_name}所属行业前10大公司的市盈率PE、市净率PB、ROE、毛利率"
    )
    df = _read_xlsx(xlsx_path)
    if df is None or df.empty:
        return {"industry": "未知", "peers": [], "sector_metrics": {}}

    # 尝试提取行业名
    industry = "未知"
    for col in df.columns:
        if "行业" in str(col):
            vals = df[col].dropna().unique()
            if len(vals) > 0:
                industry = str(vals[0])
                break

    # 提取各公司指标
    peers = []
    sector_pe_inv = []
    sector_pb_inv = []
    sector_roe = []
    sector_gm = []

    for _, row in df.iterrows():
        name = str(row.iloc[0]) if len(row) > 0 else ""
        pe_val = pb_val = roe_val = gm_val = None

        for col in df.columns:
            col_str = str(col)
            val = _parse_num(row.get(col))
            if val is None:
                continue
            if "市盈率" in col_str or "PE" in col_str:
                pe_val = val
            elif "市净率" in col_str or "PB" in col_str:
                pb_val = val
            elif "ROE" in col_str:
                roe_val = val
            elif "毛利率" in col_str:
                gm_val = val

        peer = {"name": name}
        if pe_val is not None:
            peer["pe"] = pe_val
            if pe_val > 0:
                sector_pe_inv.append(1.0 / pe_val)
        if pb_val is not None:
            peer["pb"] = pb_val
            if pb_val > 0:
                sector_pb_inv.append(1.0 / pb_val)
        if roe_val is not None:
            peer["roe"] = roe_val
            sector_roe.append(roe_val)
        if gm_val is not None:
            peer["gross_margin"] = gm_val
            sector_gm.append(gm_val)

        peers.append(peer)

    sector_metrics = {}
    if len(sector_pe_inv) >= 3:
        sector_metrics["pe_inverse"] = sector_pe_inv
    if len(sector_pb_inv) >= 3:
        sector_metrics["pb_inverse"] = sector_pb_inv
    if len(sector_roe) >= 3:
        sector_metrics["roe"] = sector_roe
    if len(sector_gm) >= 3:
        sector_metrics["gross_margin"] = sector_gm

    return {
        "industry": industry,
        "peers": peers,
        "sector_metrics": sector_metrics,
    }
