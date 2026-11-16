"""LaTeX 输出净化：题干、选项、答案、解析共用的一层机械修复。

模型输出常见三类渲染问题，全部在入库前修掉：
1 字面 "\\n"（JSON 转义泄漏）→ 真换行；
2 \\( \\) 与 \\[ \\] 定界 → $ 与 $$；
3 数学命令裸奔（如 \\underline{\\hspace{2cm}} 没有包 $）→ 白名单命令连同样式
  参数整体包上 $，让前端 KaTeX 与 Word 导出的公式转换都能识别。
"""
import re

# 常见数学命令白名单：出现在 $ 定界之外时整体包裹修复
_MATH_COMMANDS = (
    "underline", "hspace", "frac", "dfrac", "tfrac", "sqrt", "int", "oint", "sum",
    "prod", "lim", "infty", "times", "cdot", "div", "pm", "mp", "leq", "geq", "neq",
    "approx", "equiv", "propto", "alpha", "beta", "gamma", "delta", "theta", "lambda",
    "mu", "pi", "sigma", "phi", "omega", "Delta", "Sigma", "Omega", "Theta", "Lambda",
    "to", "rightarrow", "Rightarrow", "in", "subset", "cup", "cap", "forall",
    "exists", "nabla", "partial", "angle", "perp", "parallel", "sin", "cos", "tan",
    "cot", "sec", "csc", "log", "ln", "lg", "exp", "max", "min", "vec", "overrightarrow",
    "begin", "end", "text", "quad", "qquad", "left", "right", "ldots", "cdots",
    "vdots", "ddots", "binom", "overline", "mathrm", "mathbf", "mathcal", "lfloor",
    "rfloor", "lceil", "rceil", "langle", "rangle",
)

# \command 的名称部分（字母序列），白名单在 _MATH_COMMAND_SET
_LEADER_RE = re.compile(r"\\([a-zA-Z]+)")
_MATH_COMMAND_SET = set(_MATH_COMMANDS)

_ESCAPED_DOLLAR = re.compile(r"\\\$")
_SEGMENT_SPLIT = re.compile(r"(\$\$[^$]*\$\$|\$[^$]*\$)")


def _split_dollar_spans(text: str) -> list[tuple[str, bool]]:
    """按 $ / $$ 分段：返回 (片段, 是否公式区)。"""
    parts = _SEGMENT_SPLIT.split(text)
    out: list[tuple[str, bool]] = []
    for part in parts:
        if not part:
            continue
        if part.startswith("$"):
            out.append((part, True))
        else:
            out.append((part, False))
    return out


def _match_command(segment: str, start: int) -> int | None:
    """从 segment[start] 的 \\command 匹配完整 token（含连续参数组），返回结束下标。

    参数组为花括号平衡追踪；非白名单命令返回 None。
    """
    i = start + 1
    while i < len(segment) and segment[i].isalpha():
        i += 1
    if segment[start + 1:i] not in _MATH_COMMAND_SET:
        return None
    while i < len(segment) and segment[i] == "{":
        depth = 0
        j = i
        while j < len(segment):
            if segment[j] == "{":
                depth += 1
            elif segment[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if depth != 0:
            return i  # 未闭合：取到串尾
        i = j + 1
    return i


def _bare_command_spans(segment: str) -> list[tuple[int, int]]:
    """找出片段中所有裸数学命令的 (start, end) 区间。"""
    spans: list[tuple[int, int]] = []
    index = 0
    for m in _LEADER_RE.finditer(segment):
        if m.start() < index:
            continue
        end = _match_command(segment, m.start())
        if end is None:
            continue
        spans.append((m.start(), end))
        index = end
    return spans


def _wrap_bare_commands(segment: str) -> str:
    """把片段里裸露的数学命令（连同其参数）包上 $。"""
    result: list[str] = []
    index = 0
    for start, end in _bare_command_spans(segment):
        result.append(segment[index:start])
        result.append(f"${segment[start:end]}$")
        index = end
    result.append(segment[index:])
    return "".join(result)


def fix_delimiters(text: str) -> str:
    """对一段题干/答案/解析执行全部机械修复；定界不配对时保持原文交由上层重试。"""
    if not text:
        return text
    # 1 字面 \n 转真换行（JSON 转义泄漏；不影响真实换行）
    cleaned = text.replace("\\n", "\n")
    # 2 \( \) 与 \[ \] 定界
    cleaned = cleaned.replace(r"\(", "$").replace(r"\)", "$")
    cleaned = cleaned.replace(r"\[", "$$").replace(r"\]", "$$")
    if _ESCAPED_DOLLAR.search(cleaned):
        cleaned = _ESCAPED_DOLLAR.sub("＄", cleaned)  # 极少见：转义美元符占位避免分段错乱
    # 3 裸命令包裹：跳过公式区内部，只处理 $ 定界之外的文本
    parts = _split_dollar_spans(cleaned)
    if len([1 for _p, is_math in parts if is_math]) % 2 == 1:
        # $ 不配对：机械包裹会错位，保持原样交给上层重试
        return cleaned.replace("＄", "\\$")
    rebuilt = "".join(_wrap_bare_commands(seg) if not is_math else seg
                      for seg, is_math in parts)
    return rebuilt.replace("＄", "\\$")


def latex_issue(text: str) -> str | None:
    """与 fix_delimiters 配套的校验：返回首个仍无法机械修复的问题，无问题返回 None。"""
    if not text:
        return None
    if len(re.findall(r"(?<!\$)\$(?!\$)", text)) % 2 == 1:
        return "$ 定界不配对"
    for seg, is_math in _split_dollar_spans(text):
        if not is_math and _bare_command_spans(seg):
            return "存在未用 $ 包裹的数学命令"
    return None
