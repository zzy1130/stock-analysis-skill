"""
Z-score 行业中性化多因子评分。

核心思路：
  1. 缩尾处理 (winsorize) 去极端值
  2. MAD-based z-score 替代标准差，抗离群值
  3. CDF 映射到 1-10 分，z=0 → 5.5

因子定义：
  - Growth: revenue_yoy(0.4), profit_yoy(0.3), revenue_3y_cagr(0.3)
  - Value: pe_inverse(0.35), pb_inverse(0.30), dividend_yield(0.15), ev_ebitda_inverse(0.20)
  - Quality: roe(0.35), gross_margin(0.25), ocf_to_profit(0.25), roe_stability(0.15)
  - Momentum: return_20d(0.30), return_60d(0.25), rsi_distance(0.20), volume_trend(0.25)
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

try:
    from scipy.stats import norm as _norm
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


# ── 默认因子配置 ──

_DEFAULT_FACTOR_CONFIG = {
    "growth": {
        "weight": 0.25,
        "sub_factors": {
            "revenue_yoy": {"weight": 0.4, "higher_is_better": True},
            "profit_yoy": {"weight": 0.3, "higher_is_better": True},
            "revenue_3y_cagr": {"weight": 0.3, "higher_is_better": True},
        },
    },
    "value": {
        "weight": 0.25,
        "sub_factors": {
            "pe_inverse": {"weight": 0.35, "higher_is_better": True},
            "pb_inverse": {"weight": 0.30, "higher_is_better": True},
            "dividend_yield": {"weight": 0.15, "higher_is_better": True},
            "ev_ebitda_inverse": {"weight": 0.20, "higher_is_better": True},
        },
    },
    "quality": {
        "weight": 0.25,
        "sub_factors": {
            "roe": {"weight": 0.35, "higher_is_better": True},
            "gross_margin": {"weight": 0.25, "higher_is_better": True},
            "ocf_to_profit": {"weight": 0.25, "higher_is_better": True},
            "roe_stability": {"weight": 0.15, "higher_is_better": False},
        },
    },
    "momentum": {
        "weight": 0.25,
        "sub_factors": {
            "return_20d": {"weight": 0.30, "higher_is_better": True},
            "return_60d": {"weight": 0.25, "higher_is_better": True},
            "rsi_distance": {"weight": 0.20, "higher_is_better": False},
            "volume_trend": {"weight": 0.25, "higher_is_better": True},
        },
    },
}


def load_factor_config(config_path: Optional[str] = None) -> dict:
    """加载因子权重配置。优先从文件加载，否则用默认值。"""
    if config_path:
        p = Path(config_path)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return _DEFAULT_FACTOR_CONFIG


# ── 核心计算函数 ──

def winsorize(values: np.ndarray, lower: float = 5.0, upper: float = 95.0) -> np.ndarray:
    """缩尾处理：将超出指定百分位的值截断。"""
    arr = np.asarray(values, dtype=float)
    valid = arr[~np.isnan(arr)]
    if len(valid) < 3:
        return arr
    lo = np.percentile(valid, lower)
    hi = np.percentile(valid, upper)
    return np.clip(arr, lo, hi)


def zscore_mad(value: float, series: np.ndarray) -> float:
    """
    MAD-based z-score: z = (x - median) / (1.4826 * MAD)

    MAD 比标准差对离群值更鲁棒。1.4826 是正态分布下 MAD 到 σ 的换算系数。
    """
    arr = np.asarray(series, dtype=float)
    valid = arr[~np.isnan(arr)]
    if len(valid) < 2:
        return 0.0
    median = np.median(valid)
    mad = np.median(np.abs(valid - median))
    if mad < 1e-10:
        std = np.std(valid)
        if std < 1e-10:
            return 0.0
        return (value - np.mean(valid)) / std
    return (value - median) / (1.4826 * mad)


def score_cdf(z: float) -> float:
    """
    将 z-score 映射到 1-10 分: score = 1 + 9 * Φ(z)

    z=0 → 5.5, z=+2 → ~9.8, z=-2 → ~1.2
    """
    if _HAS_SCIPY:
        phi = _norm.cdf(z)
    else:
        # 近似 CDF (Abramowitz & Stegun)
        phi = 0.5 * (1.0 + np.tanh(np.sqrt(2.0 / np.pi) * (z + 0.044715 * z ** 3)))
    return round(1.0 + 9.0 * float(phi), 2)


def _absolute_score(value: float, higher_is_better: bool) -> float:
    """无 peer 数据时的绝对评分降级方案。"""
    if higher_is_better:
        if value > 30:
            return 9.0
        elif value > 15:
            return 7.0
        elif value > 5:
            return 5.5
        elif value > 0:
            return 4.0
        else:
            return 2.0
    else:
        if value < 5:
            return 8.0
        elif value < 15:
            return 6.0
        elif value < 30:
            return 4.0
        else:
            return 2.5


def compute_factor(
    stock_value: float,
    sector_values: Optional[np.ndarray],
    sub_factor_def: dict,
) -> Dict[str, Any]:
    """
    计算单个子因子得分。

    如果有 sector_values，使用 z-score + CDF 映射；否则降级为绝对评分。
    """
    higher_is_better = sub_factor_def.get("higher_is_better", True)

    if sector_values is not None and len(sector_values) >= 3:
        series = winsorize(sector_values)
        z = zscore_mad(stock_value, series)
        if not higher_is_better:
            z = -z
        score = score_cdf(z)
        return {"score": score, "z": round(z, 3), "method": "zscore"}
    else:
        score = _absolute_score(stock_value, higher_is_better)
        return {"score": score, "z": None, "method": "absolute"}


def compute_all_factors(
    stock_metrics: Dict[str, float],
    sector_metrics: Optional[Dict[str, np.ndarray]],
    config: Optional[dict] = None,
) -> dict:
    """
    计算全部 4 因子 + 总分。

    Args:
        stock_metrics: 目标股票指标值, e.g. {"revenue_yoy": 25.3, "roe": 18.5, ...}
        sector_metrics: 行业同业指标数组, e.g. {"revenue_yoy": np.array([...]), ...}
                        如果为 None，则全部使用绝对评分降级
        config: 因子权重配置 (默认使用内置配置)

    Returns:
        {
            "total": 6.7, "label": "潜力黑马",
            "growth": {"score": 7.8, "weight": 0.25, "sub_factors": {...}},
            "value": {...}, "quality": {...}, "momentum": {...}
        }
    """
    if config is None:
        config = _DEFAULT_FACTOR_CONFIG
    if sector_metrics is None:
        sector_metrics = {}

    factor_results = {}
    weighted_sum = 0.0
    total_weight = 0.0

    for factor_name, factor_def in config.items():
        factor_weight = factor_def["weight"]
        sub_factors = factor_def["sub_factors"]

        sub_results = {}
        factor_score_sum = 0.0
        sub_weight_sum = 0.0

        for sf_name, sf_def in sub_factors.items():
            sf_weight = sf_def["weight"]
            stock_val = stock_metrics.get(sf_name)

            if stock_val is None or (isinstance(stock_val, float) and np.isnan(stock_val)):
                sub_results[sf_name] = {"score": 5.5, "z": None, "method": "missing", "weight": sf_weight}
                factor_score_sum += 5.5 * sf_weight
                sub_weight_sum += sf_weight
                continue

            sector_vals = sector_metrics.get(sf_name)
            result = compute_factor(stock_val, sector_vals, sf_def)
            result["weight"] = sf_weight
            result["value"] = round(stock_val, 4)
            sub_results[sf_name] = result

            factor_score_sum += result["score"] * sf_weight
            sub_weight_sum += sf_weight

        factor_score = round(factor_score_sum / max(sub_weight_sum, 1e-10), 2)
        factor_results[factor_name] = {
            "score": factor_score,
            "weight": factor_weight,
            "sub_factors": sub_results,
        }

        weighted_sum += factor_score * factor_weight
        total_weight += factor_weight

    total = round(weighted_sum / max(total_weight, 1e-10), 1)

    if total >= 8:
        label = "绩优白马"
    elif total >= 6:
        label = "潜力黑马"
    elif total >= 4:
        label = "待观察"
    else:
        label = "风险警示"

    return {"total": total, "label": label, **factor_results}
