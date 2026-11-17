"""LaTeX 输出净化：题干、选项、答案、解析共用的一层机械修复。

模型输出常见五类渲染问题，全部在入库前修掉：
1 JSON 转义吃掉单反斜杠：\\neq 落成「换行+eq」、\\frac 落成「换页+rac」、
  \\times 落成「制表+imes」、\\beta 落成「退格+eta」、\\right 落成「回车+ight」。
  这类破坏不报错，直接把公式写坏，必须按命令白名单还原控制字符。
2 过度转义：\\\\neq 这类双反斜杠泄漏，公式里会渲染成字面反斜杠。
3 字面 "\\n"（JSON 转义泄漏）→ 真换行，但 \\neq / \\nabla / \\nu 必须豁免。
4 \\( \\) 与 \\[ \\] 定界 → $ 与 $$。
5 数学命令裸奔（如 \\underline{\\hspace{2cm}} 没有包 $）→ 白名单命令连同样式
  参数整体包上 $，让前端 KaTeX 与 Word 导出的公式转换都能识别。
"""
import re

# 常见数学命令白名单：出现在 $ 定界之外时整体包裹修复，
# 同时充当反斜杠还原的判据（见 _ESCAPE_REPAIRS）
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
    # 以下补充以 n/t/f/r/b 开头的命令：这些正是被 JSON 控制字符吃掉的受害集合
    "notin", "ni", "nsubseteq", "ngeq", "nleq", "nu", "neq",
    "tau", "textbf", "textit", "textrm", "therefore", "tilde", "triangle",
    "forall", "flat", "footnotesize",
    "rho", "rightarrowtail", "rightleftharpoons", "rangle", "rvert", "rVert",
    "beta", "bmatrix", "Bmatrix", "bigcup", "bigcap", "bigoplus", "bigotimes",
    "bar", "because", "boldsymbol", "boxed", "bullet", "binom",
    "varepsilon", "varphi", "vartheta", "varnothing", "vspace",
    "displaystyle", "textstyle", "scriptstyle", "mathop", "operatorname",
    "mathbb", "mathfrak", "mathsf", "mathtt", "mathstrut",
    "circ", "star", "ast", "otimes", "oplus", "sim", "cong", "simeq",
    "ll", "gg", "lesssim", "gtrsim", "subsetneqq", "supset", "supseteq",
    "dot", "ddot", "hat", "widehat", "widetilde", "underbrace", "overbrace",
)

# \command 的名称部分（字母序列），白名单在 _MATH_COMMAND_SET
_LEADER_RE = re.compile(r"\\([a-zA-Z]+)")
_MATH_COMMAND_SET = set(_MATH_COMMANDS)

# JSON 允许的转义里，这五个控制字符会把 LaTeX 命令的首字母吃掉：
# \n→换行、\t→制表、\f→换页、\r→回车、\b→退格
_CONTROL_LEADS: dict[str, str] = {
    "\n": "n", "\t": "t", "\f": "f", "\r": "r", "\b": "b",
}
# 还原的最短命令长度：两字母命令（\nu \to \ni）误判成本高，不做还原
_MIN_REPAIR_LEN = 3


def _build_escape_repairs() -> list[tuple[str, str]]:
    """构造「控制字符+命令后缀 → \\命令」映射，长串优先避免前缀抢占。"""
    pairs: list[tuple[str, str]] = []
    for command in _MATH_COMMANDS:
        if len(command) < _MIN_REPAIR_LEN:
            continue
        head = command[0]
        for control, lead in _CONTROL_LEADS.items():
            if head == lead:
                pairs.append((control + command[1:], "\\" + command))
    pairs.sort(key=lambda item: len(item[0]), reverse=True)
    return pairs


_ESCAPE_REPAIRS = _build_escape_repairs()
_OVER_ESCAPE_RE = re.compile(
    r"(\\+)(?:(begin|end)\{([a-zA-Z]+\*?)\}|([a-zA-Z]+))?"
)
# 退格与换页在正常正文里不该出现，残留即说明还原未覆盖
_RESIDUAL_CONTROL = re.compile(r"[\x08\x0c]")


def _collapse_over_escaped(text: str, *, collapse_noncommands: bool = False) -> str:
    """折叠过转义，保留多行环境内的行分隔符与紧接其后的命令。"""
    environments: list[str] = []

    def repl(match: re.Match[str]) -> str:
        slashes, boundary, environment, command = match.groups()
        name = boundary or command
        count = len(slashes)
        row_command = (
            count >= 3 and count % 2 == 1 and name is not None
            and bool(environments) and environments[-1].removesuffix("*") in _ROW_ENVS
        )
        if not row_command:
            if count >= 2 and name in _MATH_COMMAND_SET:
                slashes = "\\"
            elif collapse_noncommands and count >= 3 and (
                name is not None or text[match.end():match.end() + 1] != "$"
            ):
                slashes = "\\\\"
        if boundary == "begin" and environment is not None:
            environments.append(environment)
        elif boundary == "end" and environments and environments[-1] == environment:
            environments.pop()
        return slashes + match.group(0)[count:]

    return _OVER_ESCAPE_RE.sub(repl, text)


def restore_escape_artifacts(text: str) -> str:
    """还原被 JSON 转义吃掉的反斜杠。

    json.loads 把 "\\neq" 解析成「换行 + eq」，把 "\\frac" 解析成「换页 + rac」，
    这类破坏不抛错也不易察觉。按命令白名单把「控制字符 + 命令后缀」还原成 \\命令，
    并要求命令名后不是字母，避免把真换行后的普通单词误判成命令。
    """
    if not text:
        return text
    restored = text
    for broken, fixed in _ESCAPE_REPAIRS:
        pattern = re.compile(re.escape(broken) + r"(?![a-zA-Z])")
        restored = pattern.sub(lambda _match, value=fixed: value, restored)
    return _collapse_over_escaped(restored)


# JSON 合法转义首字符：其余反斜杠序列在 json.loads 里要么报错，要么被吃掉
_JSON_ESCAPE_HEADS = frozenset('"\\/bfnrtu')


def escape_bare_commands_in_json(raw: str) -> str:
    """JSON 解析前，把裸写单反斜杠的 LaTeX 命令补成合法转义。

    模型经常在 JSON 字符串里直接写 \\neq 而不是 \\\\neq。json.loads 会把 \\n 当换行、
    \\f 当换页静默吃掉，\\l 这类则直接抛 Invalid \\escape，json_repair 同样救不回来。
    这里在解析前把已知命令和非法的反斜杠序列统一补成双反斜杠。

    只处理字符串内的反斜杠，已是 \\\\ 的形式成对跳过，不会重复加斜杠。
    """
    if not raw:
        return raw
    out: list[str] = []
    index = 0
    length = len(raw)
    while index < length:
        char = raw[index]
        if char != "\\":
            out.append(char)
            index += 1
            continue
        # 已成对的 \\ 原样保留，避免重复转义
        if index + 1 < length and raw[index + 1] == "\\":
            out.append("\\\\")
            index += 2
            continue
        end = index + 1
        while end < length and raw[end].isalpha():
            end += 1
        word = raw[index + 1:end]
        if word in _MATH_COMMAND_SET:
            out.append("\\\\" + word)
            index = end
            continue
        nxt = raw[index + 1] if index + 1 < length else ""
        if nxt and nxt not in _JSON_ESCAPE_HEADS:
            out.append("\\\\" + nxt)  # 非法转义，补成合法形式
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _dollar_tokens(text: str) -> list[tuple[int, str]]:
    """读取未转义的美元定界符，保留普通文本中的货币符号。"""
    tokens: list[tuple[int, str]] = []
    consumed = 0
    for match in re.finditer(r"\$", text):
        if match.start() < consumed:
            continue
        preceding = match.start() - 1
        while preceding >= 0 and text[preceding] == "\\":
            preceding -= 1
        if (match.start() - preceding - 1) % 2 == 0:
            delimiter = "$$" if text.startswith("$$", match.start()) else "$"
            tokens.append((match.start(), delimiter))
            consumed = match.start() + len(delimiter)
    return tokens


def _delimiter_issue(text: str) -> str | None:
    """校验行内与展示定界符严格同类配对。"""
    opened = ""
    for _start, delimiter in _dollar_tokens(text):
        if not opened:
            opened = delimiter
        elif opened == delimiter:
            opened = ""
        else:
            return "$ 定界不配对"
    return f"{opened} 定界不配对" if opened else None


def _split_dollar_spans(text: str) -> list[tuple[str, bool]]:
    """按 $ / $$ 分段：返回 (片段, 是否公式区)。"""
    out: list[tuple[str, bool]] = []
    tokens = _dollar_tokens(text)
    previous = 0
    for index in range(0, len(tokens) - 1, 2):
        start, _delimiter = tokens[index]
        end_start, end_delimiter = tokens[index + 1]
        end = end_start + len(end_delimiter)
        out.append((text[previous:start], False))
        out.append((text[start:end], True))
        previous = end
    out.append((text[previous:], False))
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


def _match_environment(segment: str, start: int) -> int | None:
    """从 \\begin{env} 匹配到配对的 \\end{env}，返回结束下标。

    模型常把 \\begin{aligned}...\\end{aligned} 整段裸写在 $ 之外。只包 \\begin{aligned}
    会把环境拆散，必须连同环境体一起包。同名环境按深度计数，嵌套不同环境互不干扰。
    """
    head = re.match(r"\\begin\{([a-zA-Z]+\*?)\}", segment[start:])
    if not head:
        return None
    env = head.group(1)
    begin_token = "\\begin{" + env + "}"
    end_token = "\\end{" + env + "}"
    depth = 0
    index = start
    while index < len(segment):
        if segment.startswith(begin_token, index):
            depth += 1
            index += len(begin_token)
        elif segment.startswith(end_token, index):
            depth -= 1
            index += len(end_token)
            if depth == 0:
                return index
        else:
            index += 1
    return None


def _bare_command_spans(segment: str) -> list[tuple[int, int]]:
    """找出片段中所有裸数学命令的 (start, end) 区间。

    环境优先于单命令：能配对到 \\end 的环境整段算一个区间，
    否则 \\begin{pmatrix} 会被单独包成 $$ 并把矩阵内容留成纯文本。
    """
    spans: list[tuple[int, int]] = []
    index = 0
    for m in _LEADER_RE.finditer(segment):
        if m.start() < index:
            continue
        env_end = _match_environment(segment, m.start())
        if env_end is not None:
            spans.append((m.start(), env_end))
            index = env_end
            continue
        end = _match_command(segment, m.start())
        if end is None:
            continue
        spans.append((m.start(), end))
        index = end
    return spans


# 多行环境单独占一行更接近排版本意，用 $$ 定界；矩阵类留在行内
_DISPLAY_ENVS = frozenset({
    "aligned", "align", "align*", "alignedat", "gather", "gather*",
    "gathered", "split", "cases", "array", "eqnarray", "multline",
})
_ROW_ENVS = _DISPLAY_ENVS | frozenset({
    "matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix", "smallmatrix",
    "alignat", "flalign", "dcases", "rcases",
})


def _wrap_bare_commands(segment: str) -> str:
    """把片段里裸露的数学命令（连同其参数）包上 $，环境体整体包裹。"""
    result: list[str] = []
    index = 0
    for start, end in _bare_command_spans(segment):
        result.append(segment[index:start])
        body = segment[start:end]
        head = re.match(r"\\begin\{([a-zA-Z]+\*?)\}", body)
        delimiter = "$$" if head and head.group(1) in _DISPLAY_ENVS else "$"
        result.append(f"{delimiter}{body}{delimiter}")
        index = end
    result.append(segment[index:])
    return "".join(result)


def fix_delimiters(text: str) -> str:
    """对一段题干/答案/解析执行全部机械修复；定界不配对时保持原文交由上层重试。"""
    if not text:
        return text
    cleaned = restore_escape_artifacts(text)
    cleaned = _collapse_over_escaped(cleaned, collapse_noncommands=True)
    # 字面换行转换保留矩阵行分隔符和以 n 开头的命令。
    cleaned = re.sub(r"(?<!\\)\\n(?![a-zA-Z])", "\n", cleaned)
    # 2 \( \) 与 \[ \] 定界
    cleaned = cleaned.replace(r"\(", "$").replace(r"\)", "$")
    cleaned = cleaned.replace(r"\[", "$$").replace(r"\]", "$$")
    if _delimiter_issue(cleaned):
        return cleaned
    # 3 裸命令包裹：跳过公式区内部，只处理 $ 定界之外的文本
    parts = _split_dollar_spans(cleaned)
    rebuilt = "".join(_wrap_bare_commands(seg) if not is_math else seg
                      for seg, is_math in parts)
    return rebuilt


def latex_issue(text: str) -> str | None:
    """与 fix_delimiters 配套的校验：返回首个仍无法机械修复的问题，无问题返回 None。"""
    if not text:
        return None
    if _RESIDUAL_CONTROL.search(text):
        return "残留控制字符（反斜杠转义损坏）"
    issue = _delimiter_issue(text)
    if issue:
        return issue
    for seg, is_math in _split_dollar_spans(text):
        if not is_math and _bare_command_spans(seg):
            return "存在未用 $ 包裹的数学命令"
    return None
