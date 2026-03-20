#!/usr/bin/env python3
"""
多页投行级 PDF 投研报告。

布局:
  P1: 综合评分卡 + 风险提示 + 操作建议 + 洞察
  P2: K线 sparkline + 技术信号表 + 风险指标面板
  P3: 因子详情（4因子子项拆解）+ 催化剂与风险事件
  P4: 舆情分析 + 新闻列表 + 券商评级 + 免责声明

用法:
    python3 tools/report-pdf.py --data combined.json --output report.pdf
"""

import argparse
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image, PageBreak, KeepTogether,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── 字体注册 ──
_FONT_CANDIDATES = [
    # macOS
    ('/Library/Fonts/Arial Unicode.ttf', 'ArialUnicode'),
    ('/System/Library/Fonts/Supplemental/Arial Unicode.ttf', 'ArialUnicode'),
    ('/System/Library/Fonts/STHeiti Medium.ttc', 'STHeiti'),
    ('/System/Library/Fonts/Hiragino Sans GB.ttc', 'HiraginoSans'),
    # Windows
    ('C:/Windows/Fonts/msyh.ttc', 'MicrosoftYaHei'),
    ('C:/Windows/Fonts/simsun.ttc', 'SimSun'),
    ('C:/Windows/Fonts/simhei.ttf', 'SimHei'),
    # Linux
    ('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc', 'WenQuanYi'),
    ('/usr/share/fonts/truetype/wqy/wqy-microhei.ttc', 'WenQuanYiMicro'),
    ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 'NotoSansCJK'),
    ('/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc', 'NotoSansCJK'),
    ('/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc', 'NotoSansCJK'),
]
CN_FONT = 'Helvetica'
for font_path, font_name in _FONT_CANDIDATES:
    if Path(font_path).exists():
        try:
            pdfmetrics.registerFont(TTFont(font_name, font_path))
            CN_FONT = font_name
            break
        except Exception:
            continue

# 如果系统没有中文字体，尝试下载开源字体
if CN_FONT == 'Helvetica':
    _FONT_DIR = Path(__file__).resolve().parent.parent / 'fonts'
    _LOCAL_FONT = _FONT_DIR / 'NotoSansSC-Regular.ttf'
    if _LOCAL_FONT.exists():
        try:
            pdfmetrics.registerFont(TTFont('NotoSansSC', str(_LOCAL_FONT)))
            CN_FONT = 'NotoSansSC'
        except Exception:
            pass
    else:
        # 尝试自动下载 Noto Sans SC（~8MB，Google 开源字体）
        _NOTO_URL = 'https://github.com/google/fonts/raw/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf'
        try:
            import urllib.request
            _FONT_DIR.mkdir(parents=True, exist_ok=True)
            print(f'[report-pdf] 未检测到中文字体，正在下载 Noto Sans SC...')
            urllib.request.urlretrieve(_NOTO_URL, str(_LOCAL_FONT))
            pdfmetrics.registerFont(TTFont('NotoSansSC', str(_LOCAL_FONT)))
            CN_FONT = 'NotoSansSC'
            print(f'[report-pdf] 字体下载成功: {_LOCAL_FONT}')
        except Exception as e:
            print(f'[report-pdf] 警告: 无法下载中文字体 ({e})，PDF 中文可能显示异常')
            print(f'[report-pdf] 请手动安装中文字体，或将 .ttf 文件放入 {_FONT_DIR}/')

# ── 配色 ──
DARK_BLUE = colors.HexColor('#1B2A4A')
MEDIUM_BLUE = colors.HexColor('#2C5F8A')
ACCENT_GOLD = colors.HexColor('#C4A35A')
LIGHT_GRAY = colors.HexColor('#F4F5F7')
MEDIUM_GRAY = colors.HexColor('#8E9196')
TEXT_BLACK = colors.HexColor('#2D2D2D')
WHITE = colors.white
RED = colors.HexColor('#D64045')
GREEN = colors.HexColor('#2E8B57')

PAGE_W = A4[0] - 30 * mm


def _s(name, **kw):
    defaults = {"fontName": CN_FONT, "fontSize": 9, "leading": 14, "textColor": TEXT_BLACK}
    defaults.update(kw)
    return ParagraphStyle(name, **defaults)


def _section(text):
    return Paragraph(
        f'<font color="{ACCENT_GOLD.hexval()}">|</font> {text}',
        _s('sec', fontSize=13, leading=18, textColor=DARK_BLUE, spaceBefore=5*mm, spaceAfter=3*mm)
    )


def _page_hr():
    return HRFlowable(width='100%', thickness=1.2, color=MEDIUM_BLUE, spaceAfter=2*mm)


def _color_for_score(score):
    if score >= 8: return GREEN
    if score >= 6: return ACCENT_GOLD
    if score >= 4: return colors.HexColor('#E8A317')
    return RED


def _insight_block(data, key):
    """渲染某个 section 的解读文字（如果存在）。"""
    section_insights = data.get('section_insights', {})
    text = section_insights.get(key, '')
    if not text:
        return []
    text = text.replace('\n', '<br/>')
    return [
        Paragraph(text, _s(f'insight_{key}', fontSize=9, leading=14, textColor=TEXT_BLACK,
                           spaceBefore=2*mm, spaceAfter=3*mm)),
    ]


# ── Sparkline ──
def _render_sparkline(closes, width_mm=160, height_mm=40):
    if not closes or len(closes) < 5:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        fig, ax = plt.subplots(figsize=(width_mm / 25.4, height_mm / 25.4))
        x = range(len(closes))
        ax.plot(x, closes, color="#2C5F8A", linewidth=1.5)
        ax.fill_between(x, closes, min(closes), alpha=0.08, color="#2C5F8A")

        # MA20 if enough data
        if len(closes) >= 20:
            ma20 = [sum(closes[max(0,i-19):i+1])/min(i+1,20) for i in range(len(closes))]
            ax.plot(x, ma20, color="#C4A35A", linewidth=1, linestyle='--', alpha=0.7)

        ax.set_xlim(0, len(closes)-1)
        ax.set_ylabel('Price', fontsize=7, color='#8E9196')
        ax.tick_params(axis='both', labelsize=6, colors='#8E9196')
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#E0E0E0')
        ax.spines['bottom'].set_color('#E0E0E0')
        fig.subplots_adjust(left=0.08, right=0.98, top=0.95, bottom=0.1)

        tmpfile = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        fig.savefig(tmpfile.name, dpi=150, bbox_inches="tight", pad_inches=0.02)
        plt.close(fig)
        return tmpfile.name
    except Exception as e:
        print(f'[report-pdf] Sparkline 渲染失败: {e}')
        return None


def _render_factor_radar(factor_scores, width_mm=75, height_mm=75):
    """雷达图"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        labels = ['Growth', 'Value', 'Quality', 'Momentum']
        values = [
            factor_scores.get('growth', {}).get('score', 5),
            factor_scores.get('value', {}).get('score', 5),
            factor_scores.get('quality', {}).get('score', 5),
            factor_scores.get('momentum', {}).get('score', 5),
        ]
        values += values[:1]
        angles = np.linspace(0, 2*np.pi, len(labels), endpoint=False).tolist()
        angles += angles[:1]

        fig, ax = plt.subplots(figsize=(width_mm/25.4, height_mm/25.4), subplot_kw=dict(polar=True))
        ax.fill(angles, values, color='#2C5F8A', alpha=0.15)
        ax.plot(angles, values, color='#2C5F8A', linewidth=1.5)
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(labels, fontsize=7, color='#1B2A4A')
        ax.set_ylim(0, 10)
        ax.set_yticks([2, 4, 6, 8, 10])
        ax.set_yticklabels(['2','4','6','8','10'], fontsize=5, color='#8E9196')
        ax.spines['polar'].set_color('#E0E0E0')

        tmpfile = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        fig.savefig(tmpfile.name, dpi=150, bbox_inches="tight", pad_inches=0.02)
        plt.close(fig)
        return tmpfile.name
    except Exception as e:
        print(f'[report-pdf] 雷达图渲染失败: {e}')
        return None


# ═══════════════════════ PAGE 1: Overview ═══════════════════════

def _build_page1(data, story):
    s_body = _s('p1body')
    s_small = _s('p1small', fontSize=8, leading=12, textColor=MEDIUM_GRAY)

    stock = data.get('stock_name', '未知')
    code = data.get('stock_code', '')
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    factor = data.get('factor_scores', {})
    risk = data.get('risk', {})
    signal = data.get('signal', {})
    insights = data.get('insights', '')

    total = factor.get('total', 5.0)
    label = factor.get('label', '-')

    # ── Header ──
    header = Table(
        [[Paragraph(f'{stock} ({code})', _s('h_title', fontSize=22, leading=30, textColor=WHITE, alignment=TA_CENTER))],
         [Paragraph(f'投研分析报告  |  {now}  |  OpenClaw Stock Analysis', _s('h_sub', fontSize=10, textColor=colors.HexColor("#B8C4D8"), alignment=TA_CENTER))]],
        colWidths=[PAGE_W],
    )
    header.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), DARK_BLUE),
        ('TOPPADDING', (0,0), (-1,0), 10*mm),
        ('BOTTOMPADDING', (0,-1), (-1,-1), 6*mm),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
    ]))
    story.extend([header, Spacer(1, 5*mm)])

    # ── Score Summary ──
    story.append(_section('一、综合评分'))

    sc = _color_for_score(total)
    score_cell = Paragraph(f'<font color="{sc.hexval()}" size="32">{total}</font>', _s('sc', fontSize=32, alignment=TA_CENTER, textColor=sc))
    label_cell = Paragraph(f'<font size="10">/ 10</font><br/><font color="{sc.hexval()}">{label}</font>', _s('sc2', fontSize=10, alignment=TA_CENTER))

    score_left = Table([[score_cell], [label_cell]], colWidths=[38*mm])
    score_left.setStyle(TableStyle([('ALIGN',(0,0),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'MIDDLE')]))

    def _stars(score):
        n = max(1, min(5, round(score / 2)))
        return '\u2605' * n + '\u2606' * (5-n)

    factor_names = {'growth': '成长因子', 'value': '价值因子', 'quality': '质量因子', 'momentum': '动量因子'}
    f_header = [Paragraph(h, s_small) for h in ['因子', '得分', '评级']]
    f_rows = [f_header]
    for key, name in factor_names.items():
        f = factor.get(key, {'score': 5})
        fs = f.get('score', 5)
        fc = _color_for_score(fs)
        f_rows.append([
            Paragraph(name, s_body),
            Paragraph(f'<font color="{fc.hexval()}">{fs:.1f}</font>', s_body),
            Paragraph(_stars(fs), s_body),
        ])
    f_table = Table(f_rows, colWidths=[28*mm, 16*mm, 24*mm])
    f_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), LIGHT_GRAY),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E0E0E0')),
        ('TOPPADDING', (0,0), (-1,-1), 2*mm),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2*mm),
        ('LEFTPADDING', (0,0), (-1,-1), 2*mm),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('FONTNAME', (0,0), (-1,-1), CN_FONT),
    ]))

    # Radar or text fallback
    radar_path = _render_factor_radar(factor)
    if radar_path:
        radar_img = Image(radar_path, width=55*mm, height=55*mm)
        combo = Table([[score_left, f_table, radar_img]], colWidths=[40*mm, 72*mm, PAGE_W - 112*mm])
    else:
        # 文字版因子条形图 fallback
        def _bar(score, max_w=10):
            filled = int(round(score))
            return '█' * filled + '░' * (max_w - filled)

        bar_lines = []
        for key, name in factor_names.items():
            fs = factor.get(key, {}).get('score', 5)
            fc = _color_for_score(fs)
            bar_lines.append(f'<font color="{fc.hexval()}">{_bar(fs)}</font> {name} {fs:.1f}')
        radar_text = Paragraph('<br/>'.join(bar_lines), _s('radar_fb', fontSize=8, leading=13, fontName=CN_FONT))
        combo = Table([[score_left, f_table, radar_text]], colWidths=[40*mm, 72*mm, PAGE_W - 112*mm])

    combo.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOX', (0,0), (-1,-1), 1, MEDIUM_BLUE),
        ('BACKGROUND', (0,0), (0,0), colors.HexColor('#FAFBFD')),
        ('LEFTPADDING', (0,0), (-1,-1), 2*mm),
        ('RIGHTPADDING', (0,0), (-1,-1), 2*mm),
    ]))
    story.extend([combo, Spacer(1, 4*mm)])

    # ── Insight ──
    if insights:
        story.append(Paragraph(insights.replace('\n', '<br/>'), s_body))
        story.append(Spacer(1, 4*mm))

    # ── Score insight ──
    story.extend(_insight_block(data, 'score'))

    # ── Risk ──
    story.append(_section('二、风险提示'))

    var95 = risk.get('var_95_parametric', 0)
    cvar95 = risk.get('cvar_95', 0)
    max_dd = risk.get('max_drawdown', {}).get('max_dd_pct', 0)
    vol = risk.get('volatility', {})
    vol_regime = vol.get('regime', '-')
    vol_pct = vol.get('current_vol', 0)
    kelly = risk.get('kelly', {})
    stress = risk.get('stress_tests', [])

    vol_color = RED if vol_regime == 'HIGH' else (ACCENT_GOLD if vol_regime == 'MEDIUM' else GREEN)
    risk_items = [
        ('VaR95(参数)', f'{var95}%'), ('VaR95(历史)', f"{risk.get('var_95_historical', 0)}%"),
        ('CVaR(ES)', f'{cvar95}%'), ('最大回撤', f'{max_dd}%'),
        ('年化波动率', f'{vol_pct}%'), ('波动率状态', f'<font color="{vol_color.hexval()}">{vol_regime}</font>'),
    ]
    r_rows = []
    for i in range(0, len(risk_items), 3):
        row = []
        for j in range(3):
            if i+j < len(risk_items):
                lbl, val = risk_items[i+j]
                row.append(Paragraph(f'<font color="{MEDIUM_GRAY.hexval()}">{lbl}</font><br/><b>{val}</b>', _s(f'ri{i+j}', fontSize=9, leading=14)))
            else:
                row.append(Paragraph('', s_body))
        r_rows.append(row)

    risk_table = Table(r_rows, colWidths=[PAGE_W/3]*3)
    risk_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), LIGHT_GRAY),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E0E0E0')),
        ('TOPPADDING', (0,0), (-1,-1), 2*mm),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2*mm),
        ('LEFTPADDING', (0,0), (-1,-1), 3*mm),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.extend([risk_table, Spacer(1, 2*mm)])

    # Stress tests
    if stress:
        beta_val = stress[0].get('beta', 1.0) if stress else 1.0
        story.append(Paragraph(
            f'<font color="{MEDIUM_GRAY.hexval()}">估算 Beta = {beta_val}（基于个股/市场波动率比值）</font>',
            _s('beta_note', fontSize=8, leading=11, textColor=MEDIUM_GRAY, spaceAfter=1*mm)
        ))
        st_header = [Paragraph(h, s_small) for h in ['压力场景', '市场冲击', f'预期损失 (Beta={beta_val})']]
        st_rows = [st_header]
        for s in stress:
            st_rows.append([
                Paragraph(s.get('scenario', ''), s_body),
                Paragraph(f"{s.get('market_shock_pct', 0)}%", s_body),
                Paragraph(f'<font color="{RED.hexval()}">{s.get("expected_loss_pct", 0)}%</font>', s_body),
            ])
        st_table = Table(st_rows, colWidths=[80*mm, 45*mm, 45*mm])
        st_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), LIGHT_GRAY),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E0E0E0')),
            ('TOPPADDING', (0,0), (-1,-1), 1.5*mm),
            ('BOTTOMPADDING', (0,0), (-1,-1), 1.5*mm),
            ('LEFTPADDING', (0,0), (-1,-1), 2*mm),
            ('FONTNAME', (0,0), (-1,-1), CN_FONT),
        ]))
        story.extend([st_table, Spacer(1, 3*mm)])

    # ── Risk Alerts ──
    alerts = risk.get('alerts', [])
    if alerts:
        for a in alerts:
            lvl_c = RED if a['level'] == 'HIGH' else ACCENT_GOLD
            story.append(Paragraph(
                f'<font color="{lvl_c.hexval()}">&#9888; [{a.get("metric", "")}] {a.get("message", "")}</font>',
                _s(f'alert_{id(a)}', fontSize=8.5, leading=13, spaceBefore=1*mm)
            ))
        story.append(Spacer(1, 2*mm))

    # ── Defense Suggestions ──
    defense = risk.get('defense', {})
    if defense and defense.get('risk_level'):
        rl = defense['risk_level']
        rl_c = RED if '高' in rl else (ACCENT_GOLD if '中' in rl else GREEN)
        def_text = (
            f'<font color="{rl_c.hexval()}"><b>风险等级: {rl}</b></font>　　'
            f'<b>建议最大仓位:</b> {defense.get("max_position_pct", "-")}%<br/>'
            f'<b>策略:</b> {defense.get("strategy", "-")}<br/>'
        )
        actions = defense.get("actions", [])
        if actions:
            def_text += '<b>建议行动:</b> ' + ' / '.join(actions)
        def_box = Table([[Paragraph(def_text, s_body)]], colWidths=[PAGE_W - 4*mm])
        def_box.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1), colors.HexColor('#FFF8E7')),
            ('BOX',(0,0),(-1,-1), 0.5, ACCENT_GOLD),
            ('TOPPADDING',(0,0),(-1,-1), 2*mm), ('BOTTOMPADDING',(0,0),(-1,-1), 2*mm),
            ('LEFTPADDING',(0,0),(-1,-1), 3*mm),
        ]))
        story.extend([def_box, Spacer(1, 3*mm)])

    # ── Risk insight ──
    story.extend(_insight_block(data, 'risk'))

    # ── Action ──
    story.append(_section('三、操作建议'))

    action = signal.get('action', 'HOLD')
    conviction = signal.get('conviction', '-')
    entry = signal.get('entry_range', [0, 0])
    target = signal.get('target', 0)
    stop = signal.get('stop_loss', 0)
    pos_pct = signal.get('position_size_pct', 0)
    rr = signal.get('risk_reward', 0)

    ac = GREEN if 'BUY' in action else (RED if action in ('SELL', 'REDUCE') else ACCENT_GOLD)
    badge = Paragraph(f'<font color="{WHITE.hexval()}" size="16">{action}</font>', _s('badge', fontSize=16, textColor=WHITE, alignment=TA_CENTER))
    badge_t = Table([[badge]], colWidths=[26*mm], rowHeights=[11*mm])
    badge_t.setStyle(TableStyle([('BACKGROUND',(0,0),(0,0), ac), ('ALIGN',(0,0),(0,0),'CENTER'), ('VALIGN',(0,0),(0,0),'MIDDLE')]))

    detail_text = (
        f'<b>信心:</b> {conviction}　　'
        f'<b>入场区间:</b> {entry[0]}-{entry[1]}　　'
        f'<b>目标价:</b> {target}<br/>'
        f'<b>止损价:</b> {stop}　　'
        f'<b>建议仓位:</b> {pos_pct}%　　'
        f'<b>风险回报比:</b> {rr}x　　'
        f'<b>Kelly/2:</b> {kelly.get("kelly_half", "-")}'
    )
    action_row = Table([[badge_t, Paragraph(detail_text, s_body)]], colWidths=[30*mm, PAGE_W-30*mm])
    action_row.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'), ('LEFTPADDING',(1,0),(1,0),4*mm)]))
    story.extend([action_row, Spacer(1, 2*mm)])

    # ── Constraints & Pacing ──
    constraints = signal.get('constraints', [])
    pacing = signal.get('pacing', '')
    if constraints:
        story.append(Paragraph(
            f'<font color="{RED.hexval()}"><b>约束触发:</b> {" | ".join(constraints)}</font>',
            _s('constraints', fontSize=8.5, leading=13, spaceAfter=1*mm)
        ))
    if pacing:
        story.append(Paragraph(f'<b>调仓节奏:</b> {pacing}', s_body))
    story.append(Spacer(1, 3*mm))


# ═══════════════════════ PAGE 2: Technical ═══════════════════════

def _build_page2(data, story):
    s_body = _s('p2body')
    s_small = _s('p2small', fontSize=8, leading=12, textColor=MEDIUM_GRAY)

    kline = data.get('kline', {})
    technical = data.get('factor_scores', {}).get('_technical') or data.get('_technical', {})
    # technical may be passed separately
    if not technical:
        technical = data.get('technical', {})

    story.extend([Spacer(1, 3*mm), _page_hr(), Spacer(1, 2*mm)])

    # ── K-line Sparkline ──
    story.append(_section('四、K线走势'))
    closes = kline.get('closes', [])
    dates = kline.get('dates', [])
    sparkline_path = _render_sparkline(closes)
    if sparkline_path:
        story.append(Image(sparkline_path, width=PAGE_W, height=45*mm))
        if dates:
            story.append(Paragraph(
                f'<font color="{MEDIUM_GRAY.hexval()}">{dates[0]} ~ {dates[-1]}  |  {len(closes)} 交易日  |  蓝线=收盘价  金线=MA20</font>',
                _s('cap', fontSize=7.5, textColor=MEDIUM_GRAY, alignment=TA_CENTER)
            ))
        story.append(Spacer(1, 4*mm))
    elif closes and len(closes) >= 5:
        # Fallback: 文字版K线摘要
        hi, lo = max(closes), min(closes)
        cur = closes[-1]
        chg = (closes[-1] / closes[0] - 1) * 100 if closes[0] else 0
        chg_c = RED if chg > 0 else (GREEN if chg < 0 else MEDIUM_GRAY)
        date_range = f'{dates[0]} ~ {dates[-1]}' if dates else f'{len(closes)} 交易日'
        kline_text = (
            f'<font color="{MEDIUM_GRAY.hexval()}">[图表未能渲染，以下为数据摘要]</font><br/>'
            f'<b>区间:</b> {date_range}　　<b>数据点:</b> {len(closes)} 天<br/>'
            f'<b>最高:</b> {hi:.2f}　　<b>最低:</b> {lo:.2f}　　<b>当前:</b> {cur:.2f}　　'
            f'<b>区间涨跌:</b> <font color="{chg_c.hexval()}">{chg:+.2f}%</font>'
        )
        kline_box = Table([[Paragraph(kline_text, s_body)]], colWidths=[PAGE_W - 4*mm])
        kline_box.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1), LIGHT_GRAY),
            ('BOX',(0,0),(-1,-1), 0.5, colors.HexColor('#E0E0E0')),
            ('TOPPADDING',(0,0),(-1,-1), 3*mm), ('BOTTOMPADDING',(0,0),(-1,-1), 3*mm),
            ('LEFTPADDING',(0,0),(-1,-1), 3*mm),
        ]))
        story.extend([kline_box, Spacer(1, 4*mm)])

    # ── Technical Signals ──
    story.append(_section('五、技术信号'))

    trend = technical.get('trend', '-')
    momentum = technical.get('momentum', '-')
    trend_c = GREEN if '多头' in trend else (RED if '空头' in trend else MEDIUM_GRAY)
    mom_c = GREEN if momentum == '强' else (RED if momentum == '弱' else MEDIUM_GRAY)
    story.append(Paragraph(
        f'<b>趋势:</b> <font color="{trend_c.hexval()}">{trend}</font>　　'
        f'<b>动量:</b> <font color="{mom_c.hexval()}">{momentum}</font>',
        s_body
    ))
    story.append(Spacer(1, 2*mm))

    # Latest indicators
    ind = technical.get('latest_indicators', {})
    if ind:
        ind_items = [
            ('收盘', f"{ind.get('close', '-')}"),
            ('MA5', f"{ind.get('MA5', '-'):.2f}" if ind.get('MA5') else '-'),
            ('MA20', f"{ind.get('MA20', '-'):.2f}" if ind.get('MA20') else '-'),
            ('MA60', f"{ind.get('MA60', '-'):.2f}" if ind.get('MA60') else '-'),
            ('RSI', f"{ind.get('RSI', '-'):.1f}" if ind.get('RSI') else '-'),
            ('MACD', f"{ind.get('MACD', '-'):.3f}" if ind.get('MACD') else '-'),
        ]
        ind_cells = [Paragraph(f'<font color="{MEDIUM_GRAY.hexval()}">{l}</font><br/><b>{v}</b>', _s(f'ind{i}', fontSize=8, leading=12, alignment=TA_CENTER)) for i, (l,v) in enumerate(ind_items)]
        ind_table = Table([ind_cells], colWidths=[PAGE_W/len(ind_items)]*len(ind_items))
        ind_table.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1), LIGHT_GRAY),
            ('GRID',(0,0),(-1,-1), 0.5, colors.HexColor('#E0E0E0')),
            ('TOPPADDING',(0,0),(-1,-1), 2*mm), ('BOTTOMPADDING',(0,0),(-1,-1), 2*mm),
            ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ]))
        story.extend([ind_table, Spacer(1, 3*mm)])

    # Recent signals table
    signals = technical.get('recent_signals', [])
    if signals:
        sig_header = [Paragraph(h, s_small) for h in ['日期', '收盘价', '涨跌幅', '信号']]
        sig_rows = [sig_header]
        for s in signals[-8:]:
            sig_list = s.get('signals', [])
            sig_text = ' | '.join(sig_list)
            has_bull = any(k in sig_text for k in ['金叉','多头','突破上轨','底背离','放量突破','站上','超卖反弹'])
            has_bear = any(k in sig_text for k in ['死叉','空头','跌破','顶背离','超买','放量下跌'])
            sig_c = GREEN if has_bull and not has_bear else (RED if has_bear and not has_bull else (ACCENT_GOLD if has_bull and has_bear else TEXT_BLACK))
            chg = s.get('change_pct', 0)
            chg_c = RED if chg > 0 else (GREEN if chg < 0 else TEXT_BLACK)
            sig_rows.append([
                Paragraph(str(s.get('date', '-')), s_body),
                Paragraph(f"{s.get('close', '-')}", s_body),
                Paragraph(f'<font color="{chg_c.hexval()}">{chg:+.2f}%</font>', s_body),
                Paragraph(f'<font color="{sig_c.hexval()}">{sig_text}</font>', s_body),
            ])
        sig_table = Table(sig_rows, colWidths=[26*mm, 22*mm, 22*mm, PAGE_W-70*mm])
        sig_table.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0), LIGHT_GRAY),
            ('GRID',(0,0),(-1,-1), 0.5, colors.HexColor('#E0E0E0')),
            ('TOPPADDING',(0,0),(-1,-1), 1.5*mm), ('BOTTOMPADDING',(0,0),(-1,-1), 1.5*mm),
            ('LEFTPADDING',(0,0),(-1,-1), 2*mm),
            ('FONTNAME',(0,0),(-1,-1), CN_FONT), ('FONTSIZE',(0,0),(-1,-1), 8),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ]))
        story.extend([sig_table, Spacer(1, 3*mm)])

    # Technical insight
    story.extend(_insight_block(data, 'technical'))

    # Opportunity / Risk signals summary
    opp = technical.get('opportunity_signals', [])
    rsk = technical.get('risk_signals', [])
    if opp or rsk:
        sig_text = ''
        if opp:
            sig_text += f'<font color="{GREEN.hexval()}"><b>机会信号:</b></font><br/>'
            for o in opp[-5:]:
                sig_text += f'　+ {o}<br/>'
        if rsk:
            sig_text += f'<font color="{RED.hexval()}"><b>风险信号:</b></font><br/>'
            for r in rsk[-5:]:
                sig_text += f'　- {r}<br/>'
        story.append(Paragraph(sig_text, s_body))
        story.append(Spacer(1, 3*mm))


# ═══════════════════════ PAGE 3: Factor Detail + Events ═══════════════════════

def _build_page3(data, story):
    s_body = _s('p3body')
    s_small = _s('p3small', fontSize=8, leading=12, textColor=MEDIUM_GRAY)

    factor = data.get('factor_scores', {})
    events = data.get('events', [])
    risk = data.get('risk', {})

    story.extend([_page_hr(), Paragraph('因子详情与事件分析', _s('p3h', fontSize=9, textColor=MEDIUM_BLUE)), Spacer(1, 3*mm)])

    # ── Factor Detail ──
    story.append(_section('六、因子评分详情'))

    # Data availability warning
    data_avail = factor.get('_data_availability', {})
    note = data_avail.get('note', '')
    if note:
        story.append(Paragraph(
            f'<font color="{RED.hexval()}">⚠ {note}</font>',
            _s('avail_warn', fontSize=8, leading=12, textColor=RED, spaceBefore=0, spaceAfter=2*mm)
        ))

    factor_map = {'growth': '成长因子', 'value': '价值因子', 'quality': '质量因子', 'momentum': '动量因子'}
    sub_factor_names = {
        'revenue_yoy': '营收增速', 'profit_yoy': '利润增速', 'revenue_3y_cagr': '3年CAGR',
        'pe_inverse': '1/PE', 'pb_inverse': '1/PB', 'dividend_yield': '股息率', 'ev_ebitda_inverse': '1/EV_EBITDA',
        'roe': 'ROE', 'gross_margin': '毛利率', 'ocf_to_profit': '现金流/利润', 'roe_stability': 'ROE稳定性',
        'return_20d': '20日收益', 'return_60d': '60日收益', 'rsi_distance': 'RSI偏离', 'volume_trend': '量能趋势',
    }

    for fkey, fname in factor_map.items():
        fdata = factor.get(fkey, {})
        fscore = fdata.get('score', 5)
        fc = _color_for_score(fscore)
        story.append(Paragraph(
            f'<b>{fname}</b>: <font color="{fc.hexval()}" size="11">{fscore:.1f}</font>  (权重 {fdata.get("weight", 0.25)*100:.0f}%)',
            _s(f'f_{fkey}', fontSize=10, leading=15, spaceBefore=2*mm)
        ))

        subs = fdata.get('sub_factors', {})
        if subs:
            sub_header = [Paragraph(h, s_small) for h in ['子因子', '得分', 'Z值', '原始值', '方法', '权重']]
            sub_rows = [sub_header]
            for sk, sv in subs.items():
                sc = _color_for_score(sv.get('score', 5))
                z_val = f"{sv['z']:.2f}" if sv.get('z') is not None else '-'
                raw_val = f"{sv['value']:.2f}" if sv.get('value') is not None else '-'
                method = sv.get('method', '-')
                weight = f"{sv.get('weight', 0)*100:.0f}%"
                sub_rows.append([
                    Paragraph(sub_factor_names.get(sk, sk), s_body),
                    Paragraph(f'<font color="{sc.hexval()}">{sv.get("score", 5.5):.1f}</font>', s_body),
                    Paragraph(z_val, s_body),
                    Paragraph(raw_val, s_body),
                    Paragraph(method, s_small),
                    Paragraph(weight, s_body),
                ])
            sub_table = Table(sub_rows, colWidths=[30*mm, 16*mm, 16*mm, 22*mm, 18*mm, 16*mm])
            sub_table.setStyle(TableStyle([
                ('BACKGROUND',(0,0),(-1,0), LIGHT_GRAY),
                ('GRID',(0,0),(-1,-1), 0.5, colors.HexColor('#E0E0E0')),
                ('TOPPADDING',(0,0),(-1,-1), 1*mm), ('BOTTOMPADDING',(0,0),(-1,-1), 1*mm),
                ('LEFTPADDING',(0,0),(-1,-1), 2*mm),
                ('FONTNAME',(0,0),(-1,-1), CN_FONT), ('FONTSIZE',(0,0),(-1,-1), 8),
                ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ]))
            story.extend([sub_table, Spacer(1, 2*mm)])

    # ── Drawdown Detail ──
    dd = risk.get('max_drawdown', {})
    if dd.get('max_dd_pct'):
        story.append(_section('七、回撤分析'))
        dd_text = (
            f'<b>最大回撤:</b> {dd["max_dd_pct"]}%　　'
            f'<b>高点:</b> {dd.get("peak_date", "-")}　　'
            f'<b>低点:</b> {dd.get("trough_date", "-")}　　'
            f'<b>恢复:</b> {dd.get("recovery_date", "未恢复")} ({dd.get("recovery_days", "-")}天)<br/>'
            f'<b>当前回撤:</b> {dd.get("current_dd_pct", 0)}%'
        )
        story.extend([Paragraph(dd_text, s_body), Spacer(1, 3*mm)])

    # Factor insight
    story.extend(_insight_block(data, 'factors'))

    # ── Events ──
    if events:
        story.append(_section('八、事件影响分析'))
        for evt in events:
            if not isinstance(evt, dict):
                continue
            impact = evt.get('impact', '中性')
            imp_c = GREEN if '正面' in impact else (RED if '负面' in impact else ACCENT_GOLD)
            chain = evt.get('chain', [])
            # 如果 chain 为空，尝试从事件类型匹配模板 chain
            if not chain:
                etype = evt.get('type', '')
                from lib.sentiment import EVENT_TEMPLATES
                if etype in EVENT_TEMPLATES:
                    chain = list(EVENT_TEMPLATES[etype]['chain'])
            chain_line = ''
            if chain:
                chain_text = ' \u2192 '.join(chain)
                chain_line = f'<br/><font color="{ACCENT_GOLD.hexval()}">\u2192</font> {chain_text}'
            card_text = (
                f'<font color="{MEDIUM_BLUE.hexval()}"><b>[ {evt.get("event", "")} ]</b></font>　'
                f'<font color="{imp_c.hexval()}">{impact}</font>　'
                f'<font color="{MEDIUM_GRAY.hexval()}">{evt.get("duration", "")}</font>'
                f'{chain_line}'
            )
            card = Table([[Paragraph(card_text, s_body)]], colWidths=[PAGE_W - 4*mm])
            card.setStyle(TableStyle([
                ('BACKGROUND',(0,0),(-1,-1), LIGHT_GRAY),
                ('BOX',(0,0),(-1,-1), 0.5, colors.HexColor('#E0E0E0')),
                ('TOPPADDING',(0,0),(-1,-1), 2*mm), ('BOTTOMPADDING',(0,0),(-1,-1), 2*mm),
                ('LEFTPADDING',(0,0),(-1,-1), 3*mm),
            ]))
            story.extend([card, Spacer(1, 1.5*mm)])


# ═══════════════════════ PAGE 4: Sentiment + Ratings ═══════════════════════

def _build_page4(data, story):
    s_body = _s('p4body')
    s_small = _s('p4small', fontSize=8, leading=12, textColor=MEDIUM_GRAY)

    sentiment = data.get('sentiment', {})
    events = data.get('events', [])
    analyst_ratings = data.get('analyst_ratings', [])

    story.extend([_page_hr(), Paragraph('舆情与评级', _s('p4h', fontSize=9, textColor=MEDIUM_BLUE)), Spacer(1, 3*mm)])

    # ── Sentiment ──
    story.append(_section('九、市场情绪'))

    temp = sentiment.get('temperature', 0)
    pos = sentiment.get('positive_count', 0)
    neg = sentiment.get('negative_count', 0)
    neu = sentiment.get('neutral_count', 0)

    if temp >= 70: temp_c = RED
    elif temp >= 40: temp_c = ACCENT_GOLD
    else: temp_c = GREEN

    warning = ''
    if temp > 80:
        warning = f'<br/><font color="{RED.hexval()}"><b>⚠ 情绪极度过热，警惕拥挤交易风险</b></font>'
    elif temp < -30:
        warning = f'<br/><font color="{GREEN.hexval()}"><b>✦ 恐慌情绪，关注逆向机会</b></font>'

    temp_text = (
        f'<font color="{DARK_BLUE.hexval()}"><b>情绪温度:</b></font> '
        f'<font color="{temp_c.hexval()}" size="18">{temp}</font> / 100　　'
        f'<font color="{GREEN.hexval()}">\u25cf</font> 利好: {pos}　　'
        f'<font color="{MEDIUM_GRAY.hexval()}">\u25cf</font> 中性: {neu}　　'
        f'<font color="{RED.hexval()}">\u25cf</font> 利空: {neg}'
        f'{warning}'
    )
    story.extend([Paragraph(temp_text, s_body), Spacer(1, 3*mm)])

    # Sentiment insight
    story.extend(_insight_block(data, 'sentiment'))

    # ── News List ──
    items = sentiment.get('items', [])
    if items:
        story.append(_section('十、新闻舆情'))
        tag_colors = {'利好': GREEN, '正面': GREEN, '利空': RED, '负面': RED, '中性': MEDIUM_GRAY}
        n_header = [Paragraph(h, s_small) for h in ['标题', '情绪', '得分']]
        n_rows = [n_header]
        for item in items[:12]:
            tag = item.get('sentiment', '中性')
            tc = tag_colors.get(tag, MEDIUM_GRAY)
            title = str(item.get('title', '-'))
            if len(title) > 50:
                title = title[:50] + '...'
            n_rows.append([
                Paragraph(title, s_body),
                Paragraph(f'<font color="{tc.hexval()}"><b>{tag}</b></font>', s_body),
                Paragraph(f"{item.get('score', 0):.2f}", s_body),
            ])
        n_table = Table(n_rows, colWidths=[PAGE_W - 50*mm, 24*mm, 26*mm])
        n_table.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0), LIGHT_GRAY),
            ('GRID',(0,0),(-1,-1), 0.5, colors.HexColor('#E0E0E0')),
            ('TOPPADDING',(0,0),(-1,-1), 1.5*mm), ('BOTTOMPADDING',(0,0),(-1,-1), 1.5*mm),
            ('LEFTPADDING',(0,0),(-1,-1), 2*mm),
            ('FONTNAME',(0,0),(-1,-1), CN_FONT), ('FONTSIZE',(0,0),(-1,-1), 8),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('ROWBACKGROUNDS',(0,1),(-1,-1), [WHITE, LIGHT_GRAY]),
        ]))
        story.extend([n_table, Spacer(1, 4*mm)])

    # ── Analyst Ratings ──
    if analyst_ratings:
        story.append(_section('十一、券商评级'))
        a_header = [Paragraph(h, s_small) for h in ['机构', '评级', '目标价']]
        a_rows = [a_header]
        for ar in analyst_ratings[:10]:
            rating = ar.get('rating', '-')
            rc = GREEN if rating in ('买入','增持','强推','强烈推荐','推荐') else (RED if rating in ('卖出','减持') else TEXT_BLACK)
            a_rows.append([
                Paragraph(str(ar.get('firm', '-')), s_body),
                Paragraph(f'<font color="{rc.hexval()}">{rating}</font>', s_body),
                Paragraph(str(ar.get('target', '-')), s_body),
            ])
        a_table = Table(a_rows, colWidths=[60*mm, 40*mm, 40*mm])
        a_table.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0), MEDIUM_BLUE),
            ('TEXTCOLOR',(0,0),(-1,0), WHITE),
            ('GRID',(0,0),(-1,-1), 0.5, colors.HexColor('#E0E0E0')),
            ('TOPPADDING',(0,0),(-1,-1), 1.5*mm), ('BOTTOMPADDING',(0,0),(-1,-1), 1.5*mm),
            ('LEFTPADDING',(0,0),(-1,-1), 2*mm),
            ('FONTNAME',(0,0),(-1,-1), CN_FONT), ('FONTSIZE',(0,0),(-1,-1), 9),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ]))
        story.extend([a_table, Spacer(1, 4*mm)])

    # ── Footer ──
    story.append(Spacer(1, 5*mm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=MEDIUM_GRAY, spaceAfter=2*mm))
    story.append(Paragraph(
        '本报告仅用于研究学习，不构成投资建议。数据来源: 东方财富 / baostock  |  分析框架: OpenClaw Stock Analysis  |  '
        '报告由 AI 自动生成，所有评分和建议仅供参考，最终判断需人工复核。',
        _s('disclaimer', fontSize=7.5, leading=11, textColor=MEDIUM_GRAY, alignment=TA_CENTER),
    ))


# ═══════════════════════ Main ═══════════════════════

def build_report(data: dict, output_path: str) -> str:
    stock = data.get('stock_name', '未知')

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        topMargin=10*mm, bottomMargin=10*mm,
        leftMargin=15*mm, rightMargin=15*mm,
        title=f'{stock} 投研分析报告', author='OpenClaw Stock Analysis',
    )

    # Pass technical data through if available
    story = []

    _build_page1(data, story)
    _build_page2(data, story)
    _build_page3(data, story)
    _build_page4(data, story)

    doc.build(story)
    return output_path


def main():
    parser = argparse.ArgumentParser(description='多页投行级 PDF 投研报告')
    parser.add_argument('--data', required=True, help='合并后的 JSON 数据')
    parser.add_argument('--output', required=True, help='输出 PDF 路径')
    args = parser.parse_args()

    data = json.loads(Path(args.data).read_text(encoding='utf-8'))
    pdf_path = build_report(data, args.output)
    print(f'[report-pdf] PDF 已生成: {pdf_path}')


if __name__ == '__main__':
    main()
