"""全局 QSS 样式表。集中管理暗色指挥控制台主题。"""
from .config import C, FONT_BODY, FONT_MONO


def stylesheet() -> str:
    return f"""
    QWidget {{
        background: {C.BG};
        color: {C.TEXT};
        font-family: {FONT_BODY};
        font-size: 13px;
    }}
    QToolTip {{
        background: {C.SURFACE}; color: {C.TEXT};
        border: 1px solid {C.LINE}; padding: 5px 8px; border-radius: 4px;
    }}

    /* 卡片容器 */
    #Card {{
        background: {C.PANEL};
        border: 1px solid {C.LINE};
        border-radius: 10px;
    }}
    #CardHeader {{
        border-bottom: 1px solid {C.LINE_SOFT};
    }}
    #CardTitle {{ font-weight: 600; font-size: 13px; }}
    #CardSub   {{ color: {C.DIM}; font-size: 10px; }}
    #TierTag {{
        color: {C.SYS};
        background: rgba(124,134,255,0.08);
        border: 1px solid rgba(124,134,255,0.20);
        border-radius: 5px; padding: 2px 7px;
        font-size: 10px; font-weight: 600;
    }}

    /* 头部 */
    #Header {{
        background: {C.PANEL2};
        border-bottom: 1px solid {C.LINE};
    }}
    #Brand      {{ font-weight: 600; font-size: 15px; }}
    #BrandSub   {{ color: {C.DIM}; font-size: 10px; }}
    #MissionBox {{
        background: #0E1826; border: 1px solid {C.LINE}; border-radius: 8px;
    }}
    #MissionLabel {{ color: {C.DIM}; font-size: 10px; }}
    #MissionName  {{ font-weight: 600; font-size: 14px; }}
    #Clock {{ font-family: {FONT_MONO}; font-size: 14px; }}
    #Pill {{
        color: {C.OK}; background: rgba(55,214,160,0.10);
        border: 1px solid rgba(55,214,160,0.30);
        border-radius: 12px; padding: 3px 10px; font-weight: 600; font-size: 11px;
    }}
    #Alert {{
        color: {C.ALERT}; background: rgba(229,72,77,0.08);
        border: 1px solid rgba(229,72,77,0.30);
        border-radius: 8px; padding: 5px 11px; font-weight: 600;
    }}

    /* 通用按钮 */
    QPushButton#Primary {{
        background: {C.SYS}; color: white; border: none; border-radius: 8px;
        font-weight: 600; padding: 9px 14px;
    }}
    QPushButton#Primary:hover  {{ background: #8b93ff; }}
    QPushButton#Primary:pressed {{ background: #6b74e0; }}
    QPushButton#Ghost {{
        background: {C.PANEL2}; color: {C.MUTED};
        border: 1px solid {C.LINE}; border-radius: 8px; padding: 9px 14px;
    }}
    QPushButton#Ghost:hover {{ color: {C.TEXT}; border-color: {C.SYS}; }}

    /* Chip 标签按钮 */
    QPushButton#Chip {{
        background: transparent; color: {C.MUTED};
        border: 1px solid {C.LINE}; border-radius: 12px; padding: 4px 10px; font-size: 11px;
    }}
    QPushButton#Chip:hover {{ color: {C.TEXT}; border-color: {C.SYS}; }}

    /* 地图视图切换 */
    QPushButton#MapTab {{
        background: transparent; color: {C.MUTED};
        border: none; border-radius: 6px; padding: 5px 12px; font-weight: 500; font-size: 12px;
    }}
    QPushButton#MapTab:checked {{ background: {C.SURFACE}; color: {C.TEXT}; }}
    #MapTabs {{ background: #0D1622; border: 1px solid {C.LINE_SOFT}; border-radius: 8px; }}

    /* 文本输入 */
    QTextEdit#Cmd {{
        background: #0D1723; border: 1px solid {C.LINE}; border-radius: 8px;
        padding: 8px; font-size: 13px; selection-background-color: {C.SYS};
    }}
    QTextEdit#Cmd:focus {{ border-color: {C.SYS}; }}

    /* 滚动条 */
    QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: #28384C; border-radius: 4px; min-height: 24px; }}
    QScrollBar::handle:vertical:hover {{ background: #34465c; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QScrollArea {{ border: none; }}
    """
