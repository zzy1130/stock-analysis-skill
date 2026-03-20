"""
K 线数据获取适配器。

数据源优先级:
  1. baostock (免费、无需注册、纯 Python)
  2. 东方财富公开 HTTP 接口 (fallback)

从 vendors/kline/get_kline.py 提取。
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd


def _resolve_baostock_code(code: str) -> str:
    """
    将股票代码转换为 baostock 格式。
    "002594" / "002594.SZ" → "sz.002594"
    "600519" / "600519.SH" → "sh.600519"
    """
    code = code.strip().upper()
    if "." in code:
        num, market = code.split(".", 1)
        return f"{market.lower()}.{num}"
    if code.startswith(("60", "68")):
        return f"sh.{code}"
    return f"sz.{code}"


def _fetch_baostock(code: str, days: int = 120, adjust: str = "qfq") -> pd.DataFrame:
    """通过 baostock 获取日 K 线数据。"""
    import baostock as bs

    bs_code = _resolve_baostock_code(code)
    adjustflag_map = {"qfq": "2", "hfq": "1", "none": "3"}
    adjustflag = adjustflag_map.get(adjust, "2")

    start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")

    lg = bs.login()
    if lg.error_code != "0":
        raise ConnectionError(f"baostock login failed: {lg.error_msg}")

    try:
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,amount,turn",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag=adjustflag,
        )
        if rs.error_code != "0":
            raise ValueError(f"baostock query failed: {rs.error_msg}")

        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())

        if not rows:
            raise ValueError(f"baostock 未返回数据: {bs_code}")

        df = pd.DataFrame(rows, columns=rs.fields)
    finally:
        bs.logout()

    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").astype("Int64")
    df["turnover_rate"] = pd.to_numeric(df["turn"], errors="coerce")
    df.drop(columns=["turn"], inplace=True)

    df["change_pct"] = df["close"].pct_change() * 100
    df["change_amt"] = df["close"].diff()

    df = df.sort_values("date").reset_index(drop=True)
    if len(df) > days:
        df = df.tail(days).reset_index(drop=True)

    return df


def _fetch_eastmoney(code: str, days: int = 120, adjust: str = "qfq") -> pd.DataFrame:
    """通过东方财富公开接口获取日 K 线数据。"""
    import httpx

    code_upper = code.strip().upper()
    if "." in code_upper:
        num, market = code_upper.split(".", 1)
        prefix_map = {"SZ": "0", "SH": "1", "HK": "116"}
        prefix = prefix_map.get(market, "0")
        secid = f"{prefix}.{num}"
    elif code_upper.startswith(("60", "68")):
        secid = f"1.{code_upper}"
    else:
        secid = f"0.{code_upper}"

    fqt_map = {"qfq": "1", "hfq": "2", "none": "0"}
    beg_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")

    resp = httpx.get(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        params={
            "secid": secid, "klt": "101", "fqt": fqt_map.get(adjust, "1"),
            "lmt": str(days), "beg": beg_date, "end": "20500101",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        },
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Referer": "https://quote.eastmoney.com/",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if not data.get("data") or not data["data"].get("klines"):
        raise ValueError(f"东方财富未返回 K 线数据: secid={secid}")

    records = []
    for line in data["data"]["klines"]:
        f = line.split(",")
        records.append({
            "date": f[0], "open": float(f[1]), "close": float(f[2]),
            "high": float(f[3]), "low": float(f[4]),
            "volume": int(f[5]), "amount": float(f[6]),
            "change_pct": float(f[8]), "change_amt": float(f[9]),
            "turnover_rate": float(f[10]),
        })

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    if len(df) > days:
        df = df.tail(days).reset_index(drop=True)

    df.attrs["code"] = data["data"].get("code", code)
    df.attrs["name"] = data["data"].get("name", "")
    return df


def fetch_kline(code: str, days: int = 120, adjust: str = "qfq") -> pd.DataFrame:
    """
    获取日 K 线数据（自动选择可用数据源）。

    Args:
        code:   股票代码，如 "002594" / "002594.SZ" / "600519.SH"
        days:   获取天数（交易日），默认 120
        adjust: 复权类型 "qfq"(前复权) / "hfq"(后复权) / "none"(不复权)

    Returns:
        DataFrame，列: date, open, high, low, close, volume, amount,
                       change_pct, change_amt, turnover_rate
    """
    try:
        return _fetch_baostock(code, days, adjust)
    except Exception as e:
        print(f"baostock 失败 ({e})，尝试东方财富接口...")

    return _fetch_eastmoney(code, days, adjust)
