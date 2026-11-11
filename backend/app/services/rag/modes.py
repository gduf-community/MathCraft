"""对话模式常量：分段控制器的四个模式与提示词模板一一对应。"""

MODES = ("generate", "creative", "qa", "data")
MODE_LABELS = {"generate": "快速出题", "creative": "创新命题", "qa": "知识答疑", "data": "数据管理"}
DEFAULT_MODE = "generate"


def mode_label(mode: str) -> str:
    return MODE_LABELS.get(mode, mode)
