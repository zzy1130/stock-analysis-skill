"""
交易信号检测库。

基于技术指标检测 6 类信号：
  1. MACD 金叉/死叉
  2. RSI 超买/超卖
  3. 布林带突破
  4. 量价背离
  5. 均线多头/空头排列
  6. 放量突破（量能确认）

纯计算函数，无 API 调用。
"""

from typing import List

import numpy as np
import pandas as pd


def detect_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    基于技术指标检测交易信号。需先计算 MA/MACD/RSI/布林带。

    新增列: SIG_MACD, SIG_RSI, SIG_BOLL, SIG_DIVERGE, SIG_MA_ALIGN, SIG_VOL_BREAK, SIGNAL_SUMMARY
    """
    n = len(df)

    # 1. MACD 金叉/死叉
    sig_macd = [""] * n
    if "DIF" in df.columns and "DEA" in df.columns:
        dif = df["DIF"].values
        dea = df["DEA"].values
        for i in range(1, n):
            if dif[i] > dea[i] and dif[i - 1] <= dea[i - 1]:
                sig_macd[i] = "金叉"
            elif dif[i] < dea[i] and dif[i - 1] >= dea[i - 1]:
                sig_macd[i] = "死叉"
    df["SIG_MACD"] = sig_macd

    # 2. RSI 超买/超卖
    sig_rsi = [""] * n
    if "RSI" in df.columns:
        rsi = df["RSI"].values
        for i in range(1, n):
            if np.isnan(rsi[i]):
                continue
            if rsi[i] > 70:
                sig_rsi[i] = "超买"
            elif rsi[i] < 30:
                sig_rsi[i] = "超卖"
            if rsi[i] <= 70 and rsi[i - 1] > 70:
                sig_rsi[i] = "超买回落↓"
            elif rsi[i] >= 30 and rsi[i - 1] < 30:
                sig_rsi[i] = "超卖反弹↑"
    df["SIG_RSI"] = sig_rsi

    # 3. 布林带突破
    sig_boll = [""] * n
    if "BOLL_UP" in df.columns and "BOLL_DN" in df.columns:
        close = df["close"].values
        boll_up = df["BOLL_UP"].values
        boll_dn = df["BOLL_DN"].values
        boll_mid = df["BOLL_MID"].values
        for i in range(1, n):
            if np.isnan(boll_up[i]):
                continue
            if close[i] > boll_up[i] and close[i - 1] <= boll_up[i - 1]:
                sig_boll[i] = "突破上轨↑"
            elif close[i] < boll_dn[i] and close[i - 1] >= boll_dn[i - 1]:
                sig_boll[i] = "跌破下轨↓"
            elif close[i] > boll_mid[i] and close[i - 1] <= boll_mid[i - 1]:
                sig_boll[i] = "站上中轨"
            elif close[i] < boll_mid[i] and close[i - 1] >= boll_mid[i - 1]:
                sig_boll[i] = "跌破中轨"
    df["SIG_BOLL"] = sig_boll

    # 4. 量价背离
    sig_diverge = [""] * n
    close = df["close"].values
    volume = df["volume"].values.astype(float)
    lookback = 10
    for i in range(lookback, n):
        window_close = close[i - lookback:i]
        window_vol = volume[i - lookback:i]
        prev_high_idx = np.argmax(window_close)
        prev_low_idx = np.argmin(window_close)

        if close[i] > np.max(window_close) and volume[i] < window_vol[prev_high_idx] * 0.8:
            sig_diverge[i] = "顶背离⚠"
        elif close[i] < np.min(window_close) and volume[i] < window_vol[prev_low_idx] * 0.8:
            sig_diverge[i] = "底背离✦"
    df["SIG_DIVERGE"] = sig_diverge

    # 5. 均线多头/空头排列
    sig_ma = [""] * n
    if all(f"MA{w}" in df.columns for w in [5, 10, 20, 60]):
        ma5 = df["MA5"].values
        ma10 = df["MA10"].values
        ma20 = df["MA20"].values
        ma60 = df["MA60"].values
        for i in range(n):
            if ma5[i] > ma10[i] > ma20[i] > ma60[i]:
                sig_ma[i] = "多头排列"
            elif ma5[i] < ma10[i] < ma20[i] < ma60[i]:
                sig_ma[i] = "空头排列"
            elif ma5[i] > ma10[i] > ma20[i] and ma20[i] <= ma60[i]:
                sig_ma[i] = "多头渐成"
            elif ma5[i] < ma10[i] < ma20[i] and ma20[i] >= ma60[i]:
                sig_ma[i] = "空头渐成"
    df["SIG_MA_ALIGN"] = sig_ma

    # 6. 放量突破
    sig_vol = [""] * n
    vol_ma20 = pd.Series(volume).rolling(window=20, min_periods=5).mean().values
    open_arr = df["open"].values
    for i in range(20, n):
        if np.isnan(vol_ma20[i]):
            continue
        vol_ratio = volume[i] / vol_ma20[i] if vol_ma20[i] > 0 else 0
        is_bullish = close[i] > open_arr[i]

        if vol_ratio >= 3.0 and is_bullish:
            sig_vol[i] = "巨量突破↑↑"
        elif vol_ratio >= 2.0 and is_bullish:
            sig_vol[i] = "放量突破↑"
        elif vol_ratio >= 3.0 and not is_bullish:
            sig_vol[i] = "放量下跌⚠"
        elif vol_ratio >= 2.0 and not is_bullish:
            sig_vol[i] = "放量阴线"
    df["SIG_VOL_BREAK"] = sig_vol

    # 综合信号汇总
    summaries = []
    signal_cols = ["SIG_MACD", "SIG_RSI", "SIG_BOLL", "SIG_DIVERGE", "SIG_MA_ALIGN", "SIG_VOL_BREAK"]
    for i in range(n):
        signals = [df[col].iloc[i] for col in signal_cols if df[col].iloc[i]]
        summaries.append(" | ".join(signals) if signals else "")
    df["SIGNAL_SUMMARY"] = summaries

    return df


def get_latest_signals(df: pd.DataFrame, lookback: int = 5) -> List[dict]:
    """获取最近 N 个交易日的信号汇总。"""
    results = []
    signal_cols = ["SIG_MACD", "SIG_RSI", "SIG_BOLL", "SIG_DIVERGE", "SIG_MA_ALIGN", "SIG_VOL_BREAK"]
    tail = df.tail(lookback)

    for _, row in tail.iterrows():
        signals = []
        for col in signal_cols:
            if col in row and row[col]:
                signals.append(row[col])
        if signals:
            results.append({
                "date": row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"]),
                "signals": signals,
                "close": row["close"],
                "change_pct": row.get("change_pct", 0),
            })

    return results


def get_technical_summary(df: pd.DataFrame) -> dict:
    """
    生成技术面综合摘要。

    Returns:
        {trend, momentum, risk_signals, opportunity_signals, latest_indicators, recent_signals}
    """
    latest = df.iloc[-1]

    # 趋势判断
    ma_sig = latest.get("SIG_MA_ALIGN", "")
    if "多头排列" in ma_sig:
        trend = "多头"
    elif "空头排列" in ma_sig:
        trend = "空头"
    elif "多头渐成" in ma_sig:
        trend = "偏多震荡"
    elif "空头渐成" in ma_sig:
        trend = "偏空震荡"
    else:
        trend = "震荡"

    # 动量判断
    rsi = latest.get("RSI", 50)
    macd = latest.get("MACD", 0)
    if rsi > 60 and macd > 0:
        momentum = "强"
    elif rsi < 40 and macd < 0:
        momentum = "弱"
    else:
        momentum = "中"

    # 分类近期信号
    recent = get_latest_signals(df, lookback=10)
    risk_signals = []
    opportunity_signals = []
    for item in recent:
        for sig in item["signals"]:
            entry = f"{item['date']}: {sig}"
            if any(k in sig for k in ["死叉", "超买", "顶背离", "空头", "跌破", "放量下跌", "放量阴线"]):
                risk_signals.append(entry)
            elif any(k in sig for k in ["金叉", "超卖", "底背离", "多头", "突破上轨", "站上", "放量突破", "巨量"]):
                opportunity_signals.append(entry)

    return {
        "trend": trend,
        "momentum": momentum,
        "risk_signals": risk_signals[-5:],
        "opportunity_signals": opportunity_signals[-5:],
        "latest_indicators": {
            "close": latest["close"],
            "MA5": latest.get("MA5"),
            "MA20": latest.get("MA20"),
            "MA60": latest.get("MA60"),
            "DIF": latest.get("DIF"),
            "DEA": latest.get("DEA"),
            "MACD": latest.get("MACD"),
            "RSI": latest.get("RSI"),
            "BOLL_UP": latest.get("BOLL_UP"),
            "BOLL_MID": latest.get("BOLL_MID"),
            "BOLL_DN": latest.get("BOLL_DN"),
        },
        "recent_signals": recent,
    }
