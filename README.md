# OpenClaw 股票分析 Skill

A 股量化分析工具箱，输入一只股票，自动生成多页 Bloomberg 风格 PDF 投研报告。

**仅用于研究学习，不构成投资建议。**

## 效果预览

报告包含 4 页：

| 页码 | 内容 |
|------|------|
| P1 | 综合评分卡 + 因子雷达图 + 风险面板 + 压力测试 + 防守建议 + 操作建议 |
| P2 | K线走势图 + 技术信号表 + 机会/风险信号列表 |
| P3 | 四因子子项拆解 + 回撤分析 + 事件影响传导链 |
| P4 | 市场情绪温度 + 新闻舆情列表 + 券商评级 + 免责声明 |

## 8 大分析模块

| 模块 | 功能 | 对应设计 |
|------|------|---------|
| 行情数据抓取 | 交易所行情 + K线 + 同业对比 | market-data-fetch |
| 基本面解析 | 财报指标 + 估值换算 | fundamentals-parser |
| 新闻舆情扫描 | 去噪 + 实体识别 + 情绪打分 | news-sentiment-scan |
| 因子评分引擎 | Z-score 标准化 + 行业中性化 + 1-10评分 | factor-score-engine |
| 事件冲击分析 | 事件分类 + 传导链路 + 短中长期判断 | event-impact-analyzer |
| 风控护栏 | VaR/CVaR + 压力测试 + 阈值预警 + 防守建议 | risk-guardrail |
| 组合建议 | 买卖信号 + 仓位 + 约束校验 + 调仓节奏 | portfolio-suggestion |
| 报告生成 | 多页 PDF + 结构化解读 + 图表 | report-generator |

## 安装

### Claude Code

```bash
/install-skill https://github.com/zzy1130/stock-analysis-skill
```

### OpenClaw

```bash
openclaw install zzy1130/stock-analysis-skill
```

## 配置

需要东方财富 EM API Key（免费）：

1. 前往 https://ai.eastmoney.com/mxClaw 注册申请
2. 配置（任选一种）：

```bash
# 方式一：环境变量
export EM_API_KEY='your_key'

# 方式二：配置文件
cp config.example.json config.json
# 编辑 config.json，填入你的 key
```

## 使用

对 Claude 说：

- "分析一下比亚迪"
- "帮我出一份贵州茅台的投研报告"
- "评估一下中国核电的风险"

Skill 会自动执行 8 步工具链，生成 PDF 报告。

## 工具链流程

```
market-data.py ──→ factor-engine.py ──┐
                                       ├→ portfolio-signal.py ──→ assemble.py ──→ report-pdf.py
market-data.py ──→ risk-engine.py ────┘         ↑
news-sentiment.py ──────────────────────────────┘
```

## 因子评分体系

四因子等权（各 25%），Z-score 行业中性化，CDF 映射到 1-10 分：

| 因子 | 子因子 | 说明 |
|------|--------|------|
| 成长 | 营收增速、利润增速、3年CAGR | 越高越好 |
| 价值 | 1/PE、1/PB、股息率、1/EV_EBITDA | 越便宜越好 |
| 质量 | ROE、毛利率、现金流/利润、ROE稳定性 | 越扎实越好 |
| 动量 | 20日收益、60日收益、RSI偏离、量能趋势 | 趋势延续性 |

评分标签：>=8 绩优白马 / >=6 潜力黑马 / >=4 待观察 / <4 风险警示

## 技术栈

- **数据源**：东方财富 API (mx-findata / mx-finsearch) + baostock
- **计算库**：numpy、scipy、pandas
- **PDF 生成**：ReportLab（自动下载中文字体，跨平台支持 macOS/Windows/Linux）
- **图表**：matplotlib（K线走势图 + 因子雷达图）

## 目录结构

```
├── SKILL.md              # Skill 入口定义 + 执行规则
├── config.example.json   # API Key 配置模板
├── tools/                # 7 个工具脚本
│   ├── market-data.py    # 行情+基本面+K线+同业
│   ├── news-sentiment.py # 新闻+舆情+事件
│   ├── factor-engine.py  # Z-score 多因子评分
│   ├── risk-engine.py    # VaR/CVaR/Kelly/预警
│   ├── portfolio-signal.py # 买卖信号+调仓
│   ├── assemble.py       # 合并所有输出
│   └── report-pdf.py     # 多页 PDF 报告
├── lib/                  # 计算库
│   ├── zscore.py         # Z-score + CDF 评分
│   ├── var.py            # VaR/CVaR/压力测试/预警
│   ├── drawdown.py       # 最大回撤分析
│   ├── kelly.py          # Kelly 仓位 + 止损
│   ├── sentiment.py      # 情绪评分 + 事件分析
│   ├── indicators.py     # MA/MACD/RSI/布林带
│   └── signals.py        # 技术信号检测
├── vendors/              # 数据源适配器
├── templates/            # 因子权重配置
└── examples/             # 样例输出 JSON
```

## 免责声明

本工具仅用于研究学习目的，不构成任何投资建议。所有评分、信号和建议均由算法自动生成，最终投资决策需人工复核。使用本工具产生的任何投资损失，开发者不承担责任。
