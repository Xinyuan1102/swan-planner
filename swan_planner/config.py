"""全局配置:配色、模型命名、层级定义。

配色沿用指挥控制台视觉规范:空(青)/ 地(琥珀)双色编码异构平台,
大模型/系统统一用蓝紫,状态色区分 ok / warn / alert。
"""

APP_NAME = "空地异构集群任务规划系统"
APP_SUBTITLE = "AIR-GROUND SWARM COMMAND · LLM PLANNER"
VERSION = "0.1.0"

# ---- 三层规划器所用模型 ----
MODEL_L1 = "Qwen3.6-27B"          # 顶层 · 全局任务规划
MODEL_L2 = "Qwen3.6-27B"          # 中层 · 分组协调
MODEL_L3 = "Qwen2.5-7B + VL-7B"   # 底层 · 单平台执行

# ---- 调色板 ----
class C:
    BG        = "#0B111B"
    PANEL     = "#111A28"
    PANEL2    = "#16212F"
    SURFACE   = "#1B2837"
    LINE      = "#243347"
    LINE_SOFT = "#1C2A3A"
    TEXT      = "#E4EBF5"
    MUTED     = "#8595AC"
    DIM       = "#5C6C82"

    AIR    = "#4FC3E8"   # 无人机 UAV
    GROUND = "#E0A23C"   # 无人车 UGV
    SYS    = "#7C86FF"   # 大模型 / 系统
    OK     = "#37D6A0"
    WARN   = "#F0B429"
    ALERT  = "#E5484D"

    # 分组配色
    GROUP = {"A": "#4FC3E8", "B": "#E0A23C", "C": "#B78BEF"}

# ---- 层级元信息(用于推理链与时间线) ----
LAYERS = [
    ("L1", "顶层 · 全局任务规划", MODEL_L1, C.SYS),
    ("L2", "中层 · 分组协调",     MODEL_L2, C.OK),
    ("L3", "底层 · 单平台执行",   MODEL_L3, C.AIR),
]

# 字体族(带回退,任意平台都能落地)
FONT_DISPLAY = '"Space Grotesk", "HarmonyOS Sans SC", "Microsoft YaHei", sans-serif'
FONT_BODY    = '"Inter", "HarmonyOS Sans SC", "Microsoft YaHei", sans-serif'
FONT_MONO    = '"IBM Plex Mono", "JetBrains Mono", "Consolas", monospace'
