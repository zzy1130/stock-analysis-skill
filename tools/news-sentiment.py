#!/usr/bin/env python3
"""
新闻 + 舆情 + 事件分析工具。

合并旧 Skill 3 (新闻舆情扫描) + Skill 5 (事件冲击分析)。

用法:
    python3 tools/news-sentiment.py --input in.json --output out.json

输入 JSON:
    {"stock_name": "比亚迪"}

输出 JSON:
    {temperature, items, events, analyst_ratings}
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
VENDORS_DIR = BASE_DIR / "vendors"
FINSEARCH_SCRIPT = str(VENDORS_DIR / "mx-finsearch" / "get_data.py")

sys.path.insert(0, str(BASE_DIR))

# 确保 EM_API_KEY 可用
from lib.config import ensure_em_api_key
ensure_em_api_key()


def _fetch_news(stock_name: str) -> list[dict]:
    """通过 mx-finsearch 获取新闻。"""
    search_out = subprocess.run(
        [sys.executable, FINSEARCH_SCRIPT, f"{stock_name}最新公告研报新闻动态"],
        capture_output=True, text=True, timeout=30,
    ).stdout

    news_items = []
    try:
        json_start = search_out.find("{")
        if json_start >= 0:
            jd = json.loads(search_out[json_start:])
            for item in jd.get("data", []):
                news_items.append({
                    "title": item.get("title", ""),
                    "content": item.get("content", ""),
                    "date": item.get("date", ""),
                    "source": item.get("source", item.get("insName", "")),
                    "rating": item.get("rating", ""),
                    "informationType": item.get("informationType", ""),
                })
    except Exception:
        pass
    return news_items


def _extract_analyst_ratings(news_items: list[dict], price: float = 0) -> list[dict]:
    """从新闻中提取券商评级。"""
    analyst_ratings = []
    seen_firms = set()
    for item in news_items:
        r = item.get("rating", "")
        firm = item.get("source", "")
        if r and firm and firm not in seen_firms:
            seen_firms.add(firm)
            target = None
            tm = re.search(r"目标价(\d+\.?\d*)", item.get("title", ""))
            if tm:
                target = float(tm.group(1))
            analyst_ratings.append({"firm": firm, "rating": r, "target": target})
    return analyst_ratings


def run(input_data: dict) -> dict:
    stock_name = input_data["stock_name"]
    price = input_data.get("price", 0)

    print(f"[news-sentiment] 采集 {stock_name} 新闻...")
    news_items = _fetch_news(stock_name)
    print(f"[news-sentiment] 获取 {len(news_items)} 条新闻")

    from lib.sentiment import run_full_sentiment_analysis
    result = run_full_sentiment_analysis(news_items, stock_name)

    analyst_ratings = _extract_analyst_ratings(news_items, price)

    return {
        "sentiment": result["sentiment"],
        "events": result["events"],
        "analyst_ratings": analyst_ratings,
        "news_count": len(news_items),
    }


def main():
    parser = argparse.ArgumentParser(description="新闻+舆情+事件分析")
    parser.add_argument("--input", required=True, help="输入 JSON 文件")
    parser.add_argument("--output", required=True, help="输出 JSON 文件")
    args = parser.parse_args()

    input_data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = run(input_data)

    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[news-sentiment] 输出: {args.output}")


if __name__ == "__main__":
    main()
