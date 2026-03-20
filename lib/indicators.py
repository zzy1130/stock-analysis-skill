"""
技术指标计算库。

纯计算函数，无 API 调用。输入 DataFrame (OHLCV)，输出带指标列的 DataFrame。

指标：MA5/10/20/60、MACD (DIF/DEA/MACD柱)、RSI(14)、布林带(20,2)
"""

from typing import List

import numpy as np
import pandas as pd


def calc_ma(df: pd.DataFrame, windows: List[int] = [5, 10, 20, 60]) -> pd.DataFrame:
    """计算移动平均线。"""
    for w in windows:
        df[f"MA{w}"] = df["close"].rolling(window=w, min_periods=1).mean()
    return df


def calc_macd(
    df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9,
) -> pd.DataFrame:
    """计算 MACD（DIF, DEA, MACD柱）。"""
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    df["DIF"] = ema_fast - ema_slow
    df["DEA"] = df["DIF"].ewm(span=signal, adjust=False).mean()
    df["MACD"] = (df["DIF"] - df["DEA"]) * 2
    return df


def calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """计算 RSI。"""
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))
    return df


def calc_bollinger(
    df: pd.DataFrame, window: int = 20, num_std: float = 2.0,
) -> pd.DataFrame:
    """计算布林带（中轨、上轨、下轨）。"""
    df["BOLL_MID"] = df["close"].rolling(window=window, min_periods=1).mean()
    rolling_std = df["close"].rolling(window=window, min_periods=1).std()
    df["BOLL_UP"] = df["BOLL_MID"] + num_std * rolling_std
    df["BOLL_DN"] = df["BOLL_MID"] - num_std * rolling_std
    return df


def calc_all_indicators(df: pd.DataFrame, signals: bool = True) -> pd.DataFrame:
    """一次性计算所有技术指标，可选检测交易信号。"""
    from lib.signals import detect_signals

    df = calc_ma(df)
    df = calc_macd(df)
    df = calc_rsi(df)
    df = calc_bollinger(df)
    if signals:
        df = detect_signals(df)
    return df
