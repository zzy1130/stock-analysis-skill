---
name: openclaw-stock-analysis
description: A 股量化分析工具箱。触发词：分析股票、投研报告、估值、风险评估、因子评分。输出多页详细 PDF 投研报告。仅用于研究学习，不构成投资建议。
metadata:
  {
    "openclaw": {
      "source": "https://github.com/zzy1130/stock-analysis-skill",
      "requires": {
        "env": ["EM_API_KEY"],
        "bins": ["python3"]
      },
      "install": [
        {
          "id": "pip-deps",
          "kind": "python",
          "package": "httpx pandas openpyxl reportlab numpy matplotlib Pillow baostock scipy",
          "label": "Install Python dependencies"
        }
      ],
      "env_help": {
        "EM_API_KEY": "东方财富 API Key，免费申请: https://ai.eastmoney.com/mxClaw"
      }
    }
  }
---

# OpenClaw 股票分析

> **语言要求**：本 Skill 的所有输出（包括 insights、section_insights、事件描述、控制台日志摘要、与用户的对话）**必须使用中文**，无论用户使用什么语言提问。PDF 报告面向中文读者。

量化工具箱，从数据采集到多页 PDF 投研报告。仅用于研究学习，不构成投资建议。

## 强制执行规则

**禁止自行编写报告。** 必须按以下流程依次调用 Python 工具，不可跳过任何步骤，不可用 LLM 直接生成 HTML/Markdown 替代：

```
步骤0（首次运行必须执行）: pip install httpx pandas openpyxl reportlab numpy matplotlib Pillow baostock scipy
步骤1: python3 tools/market-data.py --input in.json --output market.json
步骤2: python3 tools/news-sentiment.py --input in.json --output sentiment.json
步骤3: python3 tools/factor-engine.py --input market.json --output factor.json
步骤4: python3 tools/risk-engine.py --input market.json --output risk.json
步骤5: python3 tools/portfolio-signal.py --factor factor.json --risk risk.json --sentiment sentiment.json --output signal.json
步骤6: 撰写 insights JSON（见下方"撰写解读"章节）
步骤7: python3 tools/assemble.py --market market.json --factor factor.json --risk risk.json --signal signal.json --sentiment sentiment.json --insights insights.json --output combined.json
步骤8: python3 tools/report-pdf.py --data combined.json --output 报告.pdf
```

**最终产物必须是 PDF 文件**（由 `report-pdf.py` 生成），不是 HTML、不是 Markdown、不是纯文本。工作目录必须 `cd` 到本 skill 的根目录再执行。

## 首次使用

需要东方财富 EM API Key（免费申请）：

1. 访问 https://ai.eastmoney.com/mxClaw 注册并获取 API Key
2. 配置方式（任选一种）：
   - **环境变量**：`export EM_API_KEY='your_key'`
   - **配置文件**：复制 `config.example.json` 为 `config.json`，填入你的 key

## 工具

| 工具 | 用途 | 输入 |
|------|------|------|
| `tools/market-data.py` | 行情+K线+同业 | `{stock_name, stock_code}` |
| `tools/news-sentiment.py` | 新闻+舆情+事件 | `{stock_name}` |
| `tools/factor-engine.py` | z-score 多因子评分 | market-data 输出 |
| `tools/risk-engine.py` | VaR/CVaR/Kelly | market-data 输出 |
| `tools/portfolio-signal.py` | 买卖信号+仓位+调仓 | factor + risk + sentiment(可选) 输出 |
| `tools/assemble.py` | 合并所有输出 | 所有工具输出 |
| `tools/report-pdf.py` | 多页 PDF 报告 | 合并 JSON |

## 撰写解读（关键步骤）

组装 `combined.json` 时，必须为每个 section 撰写通俗易懂的解读，放入 `section_insights` 字段。读者是投资小白，不懂术语。

```json
{
  "insights": "顶部总结：2-3句核心投资逻辑",
  "section_insights": {
    "score": "解读评分含义——几分算好？为什么这个分？哪个因子拖后腿？",
    "risk": "用大白话解释VaR、回撤、Beta——这只股票跌起来有多疼？适合什么风险偏好的人？",
    "technical": "解读K线走势——最近涨了还是跌了？关键支撑/压力位在哪？信号矛盾点是什么？",
    "factors": "解释因子数据——为什么有些是missing？实际公司基本面如何？动量因子背后说明什么？",
    "sentiment": "市场情绪意味着什么——温度高是好是坏？低关注度是机会还是风险？新闻在说什么？"
  }
}
```

**撰写原则**：
- 每段 80-200 字中文，像给朋友解释一样
- 术语后面加括号解释（如"RSI超买（涨太快了）"）
- 必须引用 JSON 中的实际数据，不编造
- 指出数据矛盾（如"评分不高但情绪很热"说明什么）
- 给明确方向判断，不做墙头草

## 事件数据要求

`events` 数组中的每个事件**必须**包含 `chain` 字段（传导链路），否则 PDF 报告中事件卡片会缺失影响路径。

```json
{
  "event": "公司发布新产品线",
  "type": "产品发布",
  "impact": "正面",
  "duration": "中期",
  "chain": ["产品竞争力提升", "市场份额扩大", "营收增长预期", "估值重估"]
}
```

如果 `news-sentiment.py` 自动生成的事件缺少 chain，在 assemble 阶段手动补充 3-4 步传导逻辑。

## 参考

- **工具文档**: `tools/README.md` — 每个工具的输入/输出 schema + 示例
- **踩坑记录**: `gotchas.md` — 数据源限制、降级策略、常见问题
- **样例输出**: `examples/` — 真实数据的 JSON 样例
- **因子权重**: `templates/factor-weights.json` — 可自定义
- **计算库**: `lib/` — indicators, signals, zscore, var, drawdown, kelly, sentiment
