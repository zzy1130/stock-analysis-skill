"""
新闻情绪评分 + 事件影响分析。

从 vendors/sentiment/analyze.py 提取的纯计算库。
无外部依赖（仅 math, re, datetime）。
"""

import math
import re
from datetime import datetime
from typing import Optional


# ── 常量 ──

POSITIVE_KEYWORDS: list[str] = [
    "买入", "强烈推荐", "推荐", "增持", "超预期", "突破", "创新高",
    "增长", "利好", "战略合作", "回购", "增发", "上调", "领先",
    "强化", "加速", "获批", "中标",
]

NEGATIVE_KEYWORDS: list[str] = [
    "减持", "卖出", "下滑", "亏损", "处罚", "退市", "下调",
    "不及预期", "风险", "诉讼", "违规", "暴跌", "警示", "质押", "冻结",
]

REVERSAL_PATTERNS: list[tuple[str, str]] = [
    ("利空出尽", "positive"),
    ("不及预期", "negative"),
    ("风险可控", "neutral"),
]

ANALYST_RATING_MAP: dict[str, int] = {
    "强烈推荐": 2, "买入": 2,
    "推荐": 1, "增持": 1,
    "中性": 0, "持有": 0,
    "减持": -1, "卖出": -1,
}

SOURCE_WEIGHT: dict[str, float] = {
    "REPORT": 1.5,
    "INV_NEWS": 1.0,
}

HALF_LIFE_DAYS: float = 3.0

EVENT_TEMPLATES: dict[str, dict] = {
    "产品发布": {
        "chain": ["技术突破", "产品竞争力提升", "市场份额扩大", "营收增长"],
        "duration": "中期", "default_impact": "正面",
    },
    "技术突破": {
        "chain": ["研发实力验证", "产品力提升", "行业壁垒加深", "估值溢价"],
        "duration": "中长期", "default_impact": "正面",
    },
    "财报超预期": {
        "chain": ["盈利能力验证", "分析师上调预期", "估值重估", "资金流入"],
        "duration": "短期", "default_impact": "正面",
    },
    "海外拓展": {
        "chain": ["市场空间扩大", "收入多元化", "品牌国际化", "长期成长性"],
        "duration": "长期", "default_impact": "正面",
    },
    "政策利好": {
        "chain": ["行业需求提振", "补贴/减税落地", "渗透率提升", "龙头受益"],
        "duration": "中期", "default_impact": "正面",
    },
    "高管变动": {
        "chain": ["管理层不确定性", "战略方向调整", "市场观望", "逐步明朗"],
        "duration": "短期", "default_impact": "中性",
    },
    "诉讼/处罚": {
        "chain": ["合规风险暴露", "财务影响评估", "声誉受损", "逐步消化"],
        "duration": "短期", "default_impact": "负面",
    },
    "并购重组": {
        "chain": ["业务协同预期", "整合风险", "规模效应", "价值重估"],
        "duration": "中长期", "default_impact": "中性偏正",
    },
    "行业竞争加剧": {
        "chain": ["价格战压力", "毛利率承压", "份额争夺", "优胜劣汰"],
        "duration": "中期", "default_impact": "负面",
    },
    "资金面变化": {
        "chain": ["主力资金动向", "市场情绪传导", "股价短期波动", "回归基本面"],
        "duration": "短期", "default_impact": "中性",
    },
}

EVENT_TYPE_KEYWORDS: dict[str, list[str]] = {
    "产品发布": ["新品", "发布会", "产品发布", "新产品", "上市新品", "新款"],
    "技术突破": ["技术突破", "专利", "研发成功", "自主研发", "核心技术", "创新"],
    "财报超预期": ["财报", "业绩", "超预期", "净利润增长", "营收增长", "盈利"],
    "海外拓展": ["海外", "出海", "国际化", "海外市场", "出口", "跨境", "全球化"],
    "政策利好": ["政策", "补贴", "减税", "扶持", "国家战略", "纲要", "规划"],
    "高管变动": ["董事长", "总裁", "高管", "换帅", "离职", "任命", "辞职"],
    "诉讼/处罚": ["诉讼", "处罚", "罚款", "违规", "立案", "调查", "起诉"],
    "并购重组": ["并购", "重组", "收购", "合并", "借壳", "资产注入", "整合"],
    "行业竞争加剧": ["价格战", "竞争加剧", "产能过剩", "降价", "内卷"],
    "资金面变化": ["主力资金", "北向资金", "融资融券", "大宗交易", "资金流入", "资金流出"],
}


# ── 辅助函数 ──

def _parse_date(date_str: str) -> Optional[datetime]:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y%m%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _recency_weight(item_date: Optional[datetime], reference_date: datetime) -> float:
    if item_date is None:
        return 0.5
    delta_days = (reference_date - item_date).total_seconds() / 86400.0
    if delta_days < 0:
        delta_days = 0.0
    return math.pow(2.0, -delta_days / HALF_LIFE_DAYS)


def _count_keyword_hits(text: str, keywords: list[str]) -> int:
    return sum(1 for kw in keywords if kw in text)


# ── 实体提取 ──

def extract_entities(text: str) -> list[str]:
    """提取公司名、政策名、人名。"""
    entities: list[str] = []

    for m in re.finditer(r"([\u4e00-\u9fff]{2,6}(?:股份|集团|证券|科技|电子|银行|保险|基金|控股|实业|投资))", text):
        entities.append(m.group(1))

    for m in re.finditer(r"《([^》]{1,30})》", text):
        entities.append(f"《{m.group(1)}》")

    _verb_starts = ("认为", "表示", "称", "说", "指出", "预计", "建议", "强调", "透露")
    for m in re.finditer(r"(?:董事长|总裁|CEO|总经理|分析师|首席|副总裁|秘书长)([\u4e00-\u9fff]{2,3})", text):
        name = m.group(1)
        end_pos = m.end()
        full_after_title = text[m.start() + len(m.group(0)) - len(name):]
        is_verb = any(full_after_title.startswith(v) for v in _verb_starts)
        if is_verb:
            continue
        entities.append(name)

    seen: set[str] = set()
    unique: list[str] = []
    for e in entities:
        if e not in seen:
            seen.add(e)
            unique.append(e)
    return unique


# ── 新闻情绪评分 ──

def _score_single_item(text: str, rating: Optional[str], info_type: Optional[str],
                       item_date: Optional[datetime], reference_date: datetime) -> tuple[float, str]:
    raw_score: float = 0.0
    sentiment_override: Optional[str] = None

    for pattern, label in REVERSAL_PATTERNS:
        if pattern in text:
            if label == "positive":
                raw_score += 2.0
            elif label == "negative":
                raw_score -= 2.0
            else:
                sentiment_override = "neutral"
            text = text.replace(pattern, "")

    pos_hits = _count_keyword_hits(text, POSITIVE_KEYWORDS)
    neg_hits = _count_keyword_hits(text, NEGATIVE_KEYWORDS)
    raw_score += pos_hits - neg_hits

    if rating is not None and rating in ANALYST_RATING_MAP:
        raw_score += ANALYST_RATING_MAP[rating]

    src_w = SOURCE_WEIGHT.get(info_type or "", 1.0)
    rec_w = _recency_weight(item_date, reference_date)
    weighted_score = raw_score * src_w * rec_w

    if sentiment_override == "neutral":
        label_out = "中性"
    elif weighted_score > 0.3:
        label_out = "利好"
    elif weighted_score < -0.3:
        label_out = "利空"
    else:
        label_out = "中性"

    return weighted_score, label_out


def score_news(news_items: list[dict]) -> dict:
    """评分新闻列表，返回 {temperature, positive_count, neutral_count, negative_count, items}。"""
    if not news_items:
        return {"temperature": 0, "positive_count": 0, "neutral_count": 0, "negative_count": 0, "items": []}

    dates = [_parse_date(item.get("date", "")) for item in news_items]
    valid_dates = [d for d in dates if d is not None]
    reference_date = max(valid_dates) if valid_dates else datetime.now()

    scored_items: list[dict] = []
    total_score: float = 0.0
    pos_count = neu_count = neg_count = 0

    for item, item_dt in zip(news_items, dates):
        title = item.get("title", "")
        content = item.get("content", "")
        combined_text = f"{title} {content}"
        rating = item.get("rating")
        info_type = item.get("informationType")

        score, sentiment = _score_single_item(combined_text, rating, info_type, item_dt, reference_date)
        total_score += score
        entities = extract_entities(combined_text)

        if sentiment == "利好":
            pos_count += 1
        elif sentiment == "利空":
            neg_count += 1
        else:
            neu_count += 1

        scored_items.append({"title": title, "sentiment": sentiment, "score": round(score, 3), "entities": entities})

    n = len(news_items)
    normalised = total_score / max(n, 1)
    temperature = int(round(math.tanh(normalised) * 100))
    temperature = max(-100, min(100, temperature))

    return {
        "temperature": temperature,
        "positive_count": pos_count, "neutral_count": neu_count, "negative_count": neg_count,
        "items": scored_items,
    }


# ── 事件影响分析 ──

def _classify_event(text: str) -> list[str]:
    matched: list[str] = []
    for event_type, keywords in EVENT_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                matched.append(event_type)
                break
    return matched


def _impact_label(template: dict, text: str) -> str:
    default = template["default_impact"]
    neg_signals = _count_keyword_hits(text, NEGATIVE_KEYWORDS)
    pos_signals = _count_keyword_hits(text, POSITIVE_KEYWORDS)
    if default in ("正面", "中性偏正") and neg_signals > pos_signals + 1:
        return "负面"
    if default in ("负面",) and pos_signals > neg_signals + 1:
        return "正面"
    if default == "中性偏正":
        return "中性" if neg_signals >= pos_signals else "正面"
    return default


def analyze_events(news_items: list[dict], stock_name: str) -> list[dict]:
    """事件分类 + 传导链分析。"""
    results: list[dict] = []
    seen_types: set[str] = set()

    for item in news_items:
        title = item.get("title", "")
        content = item.get("content", "")
        combined = f"{title} {content}"

        event_types = _classify_event(combined)
        for etype in event_types:
            if etype in seen_types:
                continue
            seen_types.add(etype)

            tmpl = EVENT_TEMPLATES[etype]
            impact = _impact_label(tmpl, combined)
            event_desc = f"{stock_name}{etype}" if stock_name else etype

            results.append({
                "event": event_desc, "type": etype,
                "chain": list(tmpl["chain"]), "duration": tmpl["duration"],
                "impact": impact, "source_title": title,
            })

    return results


def run_full_sentiment_analysis(news_items: list[dict], stock_name: str) -> dict:
    """运行完整的情绪评分 + 事件分析。"""
    sentiment = score_news(news_items)
    events = analyze_events(news_items, stock_name)
    return {"sentiment": sentiment, "events": events}
