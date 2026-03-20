# Gotchas — 踩坑记录

使用 OpenClaw 工具链时需要注意的常见问题。

## 数据源

- **mx-findata 查询限制**: 每次最多 5 个实体、3 个指标。超出需分批查询。
- **K线需要代码不接受名称**: baostock/东方财富接口都需要纯数字代码（如 `002594`），不接受 `比亚迪`。从 mx-findata 返回的列名中可提取代码。
- **baostock 延迟 1 天**: baostock 数据 T+1 更新，当天数据需用东方财富接口。
- **东方财富接口无认证**: 公开 HTTP 接口偶尔限流，遇到 403/429 等 5s 后重试。

## 因子评分

- **PE 为负/空时跳过估值因子**: PE < 0（亏损股）或无数据时，value 因子的 pe_inverse 为 None，自动回退绝对评分 5.5。
- **无同业数据时降级**: 当 sector_metrics 为空（行业不在预定义映射中），全部使用绝对评分而非 z-score。方向应与旧系统一致，但数值不同。
- **z-score 使用 MAD 而非标准差**: MAD 对离群值更鲁棒。1.4826 是正态分布下的换算系数。

## 情绪分析

- **温度 >80 提醒拥挤交易风险**: 一致看多时反而危险，需在报告中明确提示。
- **温度 <-30 可能是逆向机会**: 恐慌性抛售后常有反弹。
- **反转模式优先级最高**: "利空出尽" 会被评为 positive，不受内部 "利空" 关键词影响。

## PDF 生成

- **reportlab 中文字体 fallback**: macOS 优先使用 Arial Unicode，不存在时依次尝试 STHeiti、Hiragino Sans GB。如果都没有，中文会显示为方框。
- **sparkline 依赖 matplotlib**: 如果 matplotlib 未安装，sparkline 区域会跳过（不会报错）。
- **1 页限制**: 新 report-pdf.py 强制 1 页 A4，内容过多时会溢出。控制 insights 在 2-3 句。

## 依赖

- **scipy 是新增依赖**: zscore.py 和 var.py 需要 `scipy.stats.norm`。如果 scipy 未安装，会降级使用近似 CDF（精度略低但可用）。
- **安装命令**: `pip3 install httpx pandas openpyxl reportlab numpy matplotlib baostock scipy`
