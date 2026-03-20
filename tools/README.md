# OpenClaw 工具链

所有工具统一接口: `python3 tools/X.py --input in.json --output out.json`

工作目录必须是 `openclaw-stock-analysis/` 根目录。

## 工具列表

### 1. market-data.py — 行情+基本面+K线+同业

**输入**: `{"stock_name": "比亚迪", "stock_code": "002594", "kline_days": 60}`

**输出**: `{stock_name, stock_code, quote, kline, technical, peers, pe_history}`

**依赖**: mx-findata API, baostock/东方财富, peer 模块

### 2. news-sentiment.py — 新闻+舆情+事件

**输入**: `{"stock_name": "比亚迪"}`

**输出**: `{sentiment{temperature, items}, events[], analyst_ratings[], news_count}`

**依赖**: mx-finsearch API, lib/sentiment.py

### 3. factor-engine.py — Z-score 多因子评分

**输入**: market-data.py 的输出 JSON

**输出**: `{total, label, growth{score, sub_factors}, value{...}, quality{...}, momentum{...}}`

**依赖**: lib/zscore.py, templates/factor-weights.json

### 4. risk-engine.py — VaR/CVaR/压力测试/Kelly/预警/防守建议

**输入**: market-data.py 的输出 JSON

**输出**: `{var_95_parametric, cvar_95, max_drawdown{}, volatility{regime}, stress_tests[], kelly{}, stop_loss, alerts[], defense{}}`

**依赖**: lib/var.py, lib/drawdown.py, lib/kelly.py

**新增**: `alerts[]` 阈值预警 + `defense{}` 防守建议（风险等级/建议行动/策略/最大仓位）

### 5. portfolio-signal.py — 买卖信号+仓位+调仓节奏+约束校验

**输入**: `--factor factor.json --risk risk.json [--sentiment sentiment.json]`

**输出**: `{action, conviction, entry_range, target, stop_loss, position_size_pct, risk_reward, event_adjustment, constraints[], pacing}`

**新增**: 事件影响调整 + 约束校验（高波降级/风险回报比过低/多重负面事件）+ 调仓节奏建议

### 6. report-pdf.py — 1页 Bloomberg 风格 PDF

**输入**: `--data combined.json --output report.pdf`

combined.json 需要包含所有上游工具的输出，结构:
```json
{
  "stock_name": "比亚迪",
  "stock_code": "002594.SZ",
  "factor_scores": {},
  "risk": {},
  "signal": {},
  "sentiment": {},
  "events": [],
  "kline": {"closes": []},
  "insights": "Claude 写的 2-3 句洞察"
}
```

## 典型调用链

```
market-data → factor-engine ──┐
                               ├→ portfolio-signal → report-pdf
market-data → risk-engine ────┘         ↑
news-sentiment ───────────────────────→ ┘ (事件/情绪调整)
market-data + news-sentiment ──→ report-pdf (催化剂/风险)
```

## 注意事项

- mx-findata 单次查询限制: 最多 5 个实体、3 个指标
- K线模块需要**股票代码**（如 002594），不接受名称
- baostock 数据延迟 1 个交易日
- PE 为负/空时 value 因子自动降级为绝对评分
- 情绪温度 >80 时提醒拥挤交易风险
