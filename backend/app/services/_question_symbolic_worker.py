"""Evaluate complete, restricted math requests inside the disposable worker."""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass
from typing import Literal

if __name__ == "__main__" and sys.platform != "win32":
    import resource

    # The parent enforces a wall deadline on every platform.
    _, hard = resource.getrlimit(resource.RLIMIT_AS)
    limit = 256 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit if hard < 0 else min(hard, limit), hard))

import sympy as sp  # noqa: E402

_VAR = r"[a-z]"
_NUMBER = r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)"
_TOKEN = re.compile(rf"{_NUMBER}|[A-Za-z]+|\*\*|[()+*/-]")
_CONSTANTS = {"pi": sp.pi, "e": sp.E, "E": sp.E}
_FUNCTIONS = {"sqrt": sp.sqrt, "sin": sp.sin, "cos": sp.cos, "exp": sp.exp}
_SYMBOLS = {name: sp.Symbol(name, real=True) for name in "abcdefghijklmnopqrstuvwxyz"
            if name not in _CONSTANTS}
_INFINITIES = {"oo": sp.oo, "-oo": -sp.oo, "+oo": sp.oo}
_IGNORED_LATEX = re.compile(r"\\(?:left|right|quad|qquad)(?![A-Za-z])|\\[,;! ]")
_MAX_DEGREE = 12
_MAX_NODES = 100
_INTEGRATION_CONSTANT = sp.Symbol("C", real=True)
_FULL_WIDTH = str.maketrans({chr(code): chr(code - 0xFEE0) for code in range(0xFF01, 0xFF5F)})
_SUPERSCRIPT = str.maketrans("⁺⁻⁰¹²³⁴⁵⁶⁷⁸⁹", "+-0123456789")


class Unsupported(ValueError):
    """The operation or its full domain is outside the supported grammar."""


@dataclass(frozen=True)
class Expression:
    value: sp.Expr
    denominators: tuple[sp.Expr, ...] = ()


@dataclass(frozen=True)
class Solution:
    mode: Literal["scalar", "expression", "primitive", "roots", "root_options", "matrix"]
    value: sp.Expr | sp.MatrixBase | tuple[sp.Expr, ...]
    variable: sp.Symbol | None = None

    def answer(self) -> str:
        if isinstance(self.value, tuple):
            return "{" + ", ".join(map(str, self.value)) + "}"
        if isinstance(self.value, sp.MatrixBase):
            return str(self.value.tolist())
        if self.mode == "primitive":
            return f"{self.value} + C" if self.value != 0 else "C"
        return str(self.value)


def _matrix_latex(match: re.Match[str]) -> str:
    rows = [row.split("&") for row in match[2].split("\\\\")]
    return "[" + ",".join("[" + ",".join(row) + "]" for row in rows) + "]"


def _normalize(text: str) -> str:
    text = text.translate(_FULL_WIDTH).strip().removesuffix("。").strip()
    text = re.sub(r"[⁺⁻⁰¹²³⁴⁵⁶⁷⁸⁹]+", lambda m: "^{" + m[0].translate(_SUPERSCRIPT) + "}", text)
    text = re.sub(r"\$\$([^$]+)\$\$|\$([^$]+)\$", lambda m: m[1] or m[2], text)
    text = re.sub(r"\\\((.*?)\\\)|\\\[(.*?)\\\]", lambda m: m[1] or m[2] or "", text)
    text = re.sub(r"\\begin\{([bp]?matrix)\}(.*?)\\end\{\1\}", _matrix_latex, text, flags=re.S)
    text = _IGNORED_LATEX.sub("", text)
    text = re.sub(r"\\(?:mathrm|text)\{d\}", "d", text)
    text = re.sub(r"\\(?:cdot|times)(?![A-Za-z])|[×·]", "*", text)
    text = re.sub(r"\\div(?![A-Za-z])|÷", "/", text)
    text = re.sub(r"\\(?:to|rightarrow)(?![A-Za-z])|→", "->", text)
    text = re.sub(r"\\infty(?![A-Za-z])|∞", "oo", text)
    text = re.sub(r"\\(lim|int|pi|sin|cos|exp)(?![A-Za-z])", r"\1", text)
    text = re.sub(r"\\pm(?![A-Za-z])", "±", text)
    text = re.sub(r"\\([{}])", r"\1", text)
    text = text.replace("−", "-").replace("√", "sqrt").replace("π", "pi")
    text = re.sub(r"\\(?:dfrac|tfrac)(?![A-Za-z])", lambda _: r"\frac", text)
    text = re.sub(r"\^\{\s*([+-]?[0-9]+)\s*\}", r"^(\1)", text)
    for _ in range(8):
        changed = re.sub(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"((\1)/(\2))", text)
        changed = re.sub(r"\\sqrt\s*\{([^{}]+)\}", r"sqrt(\1)", changed)
        if changed == text:
            break
        text = changed
    return " ".join(text.split())


def _parse(
    text: str, names: dict[str, sp.Expr] | None = None, *, max_degree: int = _MAX_DEGREE,
) -> Expression:
    names = names or {}
    text = text.strip().replace("^", "**")
    tokens: list[str] = []
    position = 0
    depth = 0
    division_depths: set[int] = set()
    while position < len(text):
        if text[position].isspace():
            position += 1
            continue
        match = _TOKEN.match(text, position)
        if not match or len(tokens) >= _MAX_NODES:
            raise Unsupported
        token = match[0]
        previous = tokens[-1] if tokens else ""
        if previous and (previous == ")" or previous[-1].isalnum() or previous[-1] == "."):
            implicit = token == "(" or token.isalpha() or (
                previous == ")" and bool(re.fullmatch(_NUMBER, token))
            )
            if implicit and previous not in _FUNCTIONS:
                if depth in division_depths:
                    raise Unsupported
                tokens.append("*")
        if token == "(":
            depth += 1
        elif token == ")":
            division_depths.discard(depth)
            depth -= 1
        elif token == "/":
            division_depths.add(depth)
        elif token == "*" or (
            token in {"+", "-"} and previous not in {"", "(", "/", "*", "**", "+", "-"}
        ):
            division_depths.discard(depth)
        tokens.append(token)
        position = match.end()

    source = " ".join(tokens)
    try:
        tree = ast.parse(source, mode="eval").body
    except SyntaxError as exc:
        raise Unsupported from exc
    if sum(1 for _ in ast.walk(tree)) > _MAX_NODES:
        raise Unsupported
    denominators: list[sp.Expr] = []

    def build(node: ast.AST) -> tuple[sp.Expr, int, int]:
        numerator_degree = denominator_degree = 0
        match node:
            case ast.Constant():
                raw = source[node.col_offset:node.end_col_offset]
                if len(raw) > 24 or not re.fullmatch(_NUMBER, raw):
                    raise Unsupported
                value = sp.Rational(raw)
            case ast.Name(id=name) if name in names:
                value = names[name]
                numerator_degree = 1
            case ast.Name(id=name) if name in _CONSTANTS:
                value = _CONSTANTS[name]
            case ast.UnaryOp(op=ast.UAdd(), operand=operand):
                value, numerator_degree, denominator_degree = build(operand)
            case ast.UnaryOp(op=ast.USub(), operand=operand):
                value, numerator_degree, denominator_degree = build(operand)
                value = -value
            case ast.BinOp(left=left, op=operator, right=right):
                lhs, left_num, left_den = build(left)
                rhs, right_num, right_den = build(right)
                match operator:
                    case ast.Add() | ast.Sub():
                        numerator_degree = max(left_num + right_den, right_num + left_den)
                        denominator_degree = left_den + right_den
                        value = lhs + rhs if isinstance(operator, ast.Add) else lhs - rhs
                    case ast.Mult():
                        numerator_degree = left_num + right_num
                        denominator_degree = left_den + right_den
                        value = lhs * rhs
                    case ast.Div():
                        numerator_degree = left_num + right_den
                        denominator_degree = left_den + right_num
                        _require_nonzero(rhs)
                        denominators.append(rhs)
                        value = lhs / rhs
                    case ast.Pow():
                        exponent = right.operand if isinstance(right, ast.UnaryOp) else right
                        if (not isinstance(exponent, ast.Constant)
                                or not isinstance(rhs, sp.Integer) or abs(rhs) > max_degree):
                            raise Unsupported
                        power = int(rhs)
                        if power <= 0:
                            _require_nonzero(lhs)
                            denominators.append(lhs)
                            left_num, left_den = left_den, left_num
                        numerator_degree = left_num * abs(power)
                        denominator_degree = left_den * abs(power)
                        if max(numerator_degree, denominator_degree) > max_degree:
                            raise Unsupported
                        value = lhs ** rhs
                    case _:
                        raise Unsupported
            case ast.Call(func=ast.Name(id=name), args=[argument], keywords=[]):
                arg, _, _ = build(argument)
                if (
                    name not in _FUNCTIONS or arg.free_symbols
                    or (name == "exp" and not -12 <= arg <= 12)
                ):
                    raise Unsupported
                value = _FUNCTIONS[name](arg)
            case _:
                raise Unsupported
        if (
            max(numerator_degree, denominator_degree) > max_degree
            or value.is_real is False
            or value.is_finite is False
        ):
            raise Unsupported
        if any(atom.p.bit_length() > 1024 or atom.q.bit_length() > 1024
               for atom in value.atoms(sp.Rational)):
            raise Unsupported
        return value, numerator_degree, denominator_degree

    value, _, _ = build(tree)
    return Expression(value, tuple(denominators))


def _require_nonzero(value: sp.Expr) -> None:
    if value.is_zero is True:
        raise Unsupported


def _variable(name: str) -> sp.Symbol:
    if name not in _SYMBOLS:
        raise Unsupported
    return _SYMBOLS[name]


def _expr(text: str, x: sp.Symbol) -> Expression:
    return _parse(text, {x.name: x})


def _number(text: str) -> sp.Expr:
    value = _parse(text).value
    if value.is_real is not True or value.is_finite is not True:
        raise Unsupported
    return value


def _poly(value: sp.Expr, x: sp.Symbol) -> sp.Poly:
    try:
        poly = sp.Poly(value, x, domain=sp.QQ)
    except (sp.PolynomialError, sp.CoercionFailed) as exc:
        raise Unsupported from exc
    if poly.degree() > _MAX_DEGREE:
        raise Unsupported
    return poly


def _defined_at(expr: Expression, x: sp.Symbol, point: sp.Expr) -> None:
    if any(denominator.subs(x, point).is_zero is not False for denominator in expr.denominators):
        raise Unsupported


def _has_real_zero(value: sp.Expr, x: sp.Symbol) -> bool:
    if not value.free_symbols and value.is_zero is False:
        return False
    numerator, _ = sp.cancel(value).as_numer_denom()
    poly = _poly(numerator, x)
    return poly.is_zero or (poly.degree() > 0 and poly.count_roots() != 0)


def _defined_everywhere(expr: Expression, x: sp.Symbol) -> None:
    if any(_has_real_zero(denominator, x) for denominator in expr.denominators):
        raise Unsupported


def _split(text: str, separators: str = ",") -> list[str]:
    parts = []
    openings = []
    pairs = {")": "(", "]": "[", "}": "{"}
    start = 0
    for index, char in enumerate(text):
        if char in "([{":
            openings.append(char)
        elif char in pairs:
            if not openings or openings.pop() != pairs[char]:
                raise Unsupported
        elif char in separators and not openings:
            parts.append(text[start:index].strip())
            start = index + 1
    if openings:
        raise Unsupported
    parts.append(text[start:].strip())
    if any(not part for part in parts):
        raise Unsupported
    return parts


def _function(expr_text: str, variable: str, point_text: str, *, derivative: bool) -> Solution:
    x = _variable(variable)
    expr = _expr(expr_text, x)
    if point_text:
        point = _number(point_text)
        _defined_at(expr, x, point)
        value = sp.diff(expr.value, x) if derivative else expr.value
        return Solution("scalar", value.subs(x, point))
    if not derivative:
        raise Unsupported
    _defined_everywhere(expr, x)
    return Solution("expression", sp.diff(expr.value, x), x)


def _variables(text: str) -> set[str]:
    return set(re.findall(r"(?<![a-z])[a-z](?![a-z])", text)) & _SYMBOLS.keys()


def _simplify(text: str) -> Solution:
    variables = _variables(text)
    if not variables:
        return Solution("scalar", _number(text))
    if len(variables) != 1:
        raise Unsupported
    x = _variable(variables.pop())
    expr = _expr(text, x)
    _defined_everywhere(expr, x)
    return Solution("expression", sp.cancel(expr.value), x)


def _equation(text: str, *, select_roots: bool = False) -> Solution:
    sides = _split(text, "=")
    names = _variables(text)
    if len(sides) != 2 or len(names) != 1:
        raise Unsupported
    x = _variable(names.pop())
    lhs, rhs = (_expr(side, x) for side in sides)
    diff = Expression(lhs.value - rhs.value, lhs.denominators + rhs.denominators)
    numerator, _ = sp.cancel(diff.value).as_numer_denom()
    poly = _poly(numerator, x)
    if poly.is_zero or poly.degree() > 4:
        raise Unsupported
    for denominator in diff.denominators:
        _poly(sp.cancel(denominator).as_numer_denom()[0], x)
    roots = []
    for root in poly.real_roots(radicals=True):
        if not isinstance(root, sp.Expr) or root.has(sp.CRootOf):
            raise Unsupported
        known_zeros = [
            denominator.subs(x, root).is_zero for denominator in diff.denominators
        ]
        if None in known_zeros:
            raise Unsupported
        if True not in known_zeros and root not in roots:
            roots.append(root)
    return Solution("root_options" if select_roots else "roots", tuple(roots), x)


def _limit(expr_text: str, variable: str, point_text: str, side: str = "") -> Solution:
    x = _variable(variable)
    expr = _expr(expr_text, x)
    for term in (expr.value, *expr.denominators):
        for factor in sp.cancel(term).as_numer_denom():
            _poly(factor, x)
    point_text = point_text.strip()
    point = _INFINITIES[point_text] if point_text in _INFINITIES else _number(point_text)
    if side not in {"", "+", "-"} or (point in (sp.oo, -sp.oo) and side):
        raise Unsupported
    if point in (sp.oo, -sp.oo):
        return Solution("scalar", sp.limit(expr.value, x, point))
    value = sp.limit(expr.value, x, point, dir=side or "+")
    if not side and value != sp.limit(expr.value, x, point, dir="-"):
        raise Unsupported
    return Solution("scalar", value)


def _integral(expr_text: str, variable: str, *bounds: str) -> Solution:
    x = _variable(variable)
    expr = _expr(expr_text, x)
    _defined_everywhere(expr, x)
    primitive = _poly(expr.value, x).integrate().as_expr()
    if not bounds:
        return Solution("primitive", primitive, x)
    if len(bounds) != 2:
        raise Unsupported
    lower, upper = (_number(bound) for bound in bounds)
    return Solution("scalar", primitive.subs(x, upper) - primitive.subs(x, lower))


def _matrix(text: str) -> sp.MatrixBase:
    if not text.startswith("[") or not text.endswith("]"):
        raise Unsupported
    rows = _split(text[1:-1])
    if len(rows) > 4:
        raise Unsupported
    entries = []
    for row in rows:
        if not row.startswith("[") or not row.endswith("]"):
            raise Unsupported
        entries.append([_number(entry) for entry in _split(row[1:-1])])
    if not (0 < len(entries[0]) <= 4 and all(len(row) == len(entries[0]) for row in entries)):
        raise Unsupported
    if any(not isinstance(entry, sp.Rational) for row in entries for entry in row):
        raise Unsupported
    return sp.ImmutableMatrix(entries)


def _matrix_operation(operation: str, arguments: list[str]) -> Solution:
    if operation in {"matadd", "matmul"}:
        if len(arguments) != 2:
            raise Unsupported
        left, right = map(_matrix, arguments)
        if operation == "matadd" and left.shape == right.shape:
            return Solution("matrix", left + right)
        if operation == "matmul" and left.cols == right.rows:
            return Solution("matrix", left * right)
        raise Unsupported
    if len(arguments) != 1:
        raise Unsupported
    matrix = _matrix(arguments[0])
    if operation in {"det", "inverse"} and not matrix.is_square:
        raise Unsupported
    match operation:
        case "det":
            determinant = matrix.det()
            if not isinstance(determinant, sp.Expr):
                raise Unsupported
            return Solution("scalar", determinant)
        case "rank":
            return Solution("scalar", sp.Integer(matrix.rank()))
        case "transpose":
            return Solution("matrix", matrix.T)
        case "inverse":
            if matrix.det() == 0:
                raise Unsupported
            return Solution("matrix", matrix.inv())
        case _:
            raise Unsupported


_FUNCTION_STEM = re.compile(
    rf"(?:求(?:函数)?\s*)?(?:f\(({_VAR})\)|y)\s*=\s*(.*?)"
    rf"(?:\s*在\s*({_VAR})\s*=\s*(.*?)\s*处)?\s*的(导数(?:值)?|(?:函?数)?值)"
)
_INTEGRAL_STEM = re.compile(
    rf"int\s*(?:_\s*(\{{[^{{}}]+\}}|[+-]?[0-9]+)\s*"
    rf"\^\s*(\{{[^{{}}]+\}}|\([+-]?[0-9]+\)|[+-]?[0-9]+))?\s*(.+?)\s*d\s*({_VAR})"
)
_MATRIX_OPERATIONS = {
    "行列式": "det", "秩": "rank", "逆矩阵": "inverse", "转置": "transpose",
}


def _operation_call(operation: str, text: str) -> Solution:
    arguments = _split(text)
    match operation, arguments:
        case "diff", [expr, variable]:
            return _function(expr, variable, "", derivative=True)
        case "diff", [expr, variable, point]:
            return _function(expr, variable, point, derivative=True)
        case "value", [expr, variable, point]:
            return _function(expr, variable, point, derivative=False)
        case "limit", [expr, variable, point, *side] if len(side) <= 1:
            return _limit(expr, variable, point, *side)
        case "integral", [expr, variable, *bounds]:
            return _integral(expr, variable, *bounds)
        case operation, _ if operation in (*_MATRIX_OPERATIONS.values(), "matadd", "matmul"):
            return _matrix_operation(operation, arguments)
        case _:
            raise Unsupported


def _solve(stem: str) -> Solution:
    text = _normalize(stem)
    if match := re.fullmatch(r"下列(?:哪些(?:选项)?|哪一项)是方程\s*(.+?)\s*的(?:实数)?解[?]?", text):
        return _equation(match[1], select_roots=True)
    if match := re.fullmatch(r"select_roots\((.+)\)", text):
        return _equation(match[1], select_roots=True)
    if match := re.fullmatch(r"(?:化简\s*|[Ss]implify\s+)(.+)", text):
        return _simplify(match[1])
    if match := _FUNCTION_STEM.fullmatch(text):
        variable, expr, point_variable, point, operation = match.groups()
        if operation == "导数值" and not point:
            raise Unsupported
        if variable is not None and point_variable is not None and variable != point_variable:
            raise Unsupported
        return _function(
            expr, variable or point_variable or "x", point or "",
            derivative=operation.startswith("导数"),
        )
    if match := re.fullmatch(rf"已知\s*f\(({_VAR})\)\s*=\s*(.*?),\s*求\s*f\((.*)\)\s*的值", text):
        return _function(match[2], match[1], match[3], derivative=False)
    text = re.sub(r"^(?:计算|求(?:解)?|Calculate\s+|Find\s+)\s*", "", text)
    if match := re.fullmatch(
        r"(diff|value|limit|integral|det|rank|transpose|inverse|matadd|matmul)\((.*)\)", text,
    ):
        return _operation_call(match[1], match[2])
    limit = re.fullmatch(
        rf"lim_\{{\s*({_VAR})\s*->\s*((?:[^{{}}]|\{{[+-]\}})+)\}}\s*(.+)",
        re.sub(r"^极限\s*", "", text),
    )
    if limit:
        point = re.fullmatch(r"(.*?)\s*\^\{?([+-])\}?", limit[2])
        if point:
            return _limit(limit[3], limit[1], point[1], point[2])
        return _limit(limit[3], limit[1], limit[2])
    integral_text = re.sub(r"^(?:定积分|不定积分|积分)\s*", "", text)
    if match := _INTEGRAL_STEM.fullmatch(integral_text):
        lower, upper, expr, variable = match.groups()
        if (text.startswith("不定积分") and lower is not None
                or text.startswith("定积分") and lower is None):
            raise Unsupported
        bounds = () if lower is None else (lower.strip("{}"), upper.strip("{}"))
        return _integral(expr, variable, *bounds)
    if match := re.fullmatch(r"矩阵\s*(\[.*\])\s*的(行列式|秩|逆矩阵|转置)", text):
        return _matrix_operation(_MATRIX_OPERATIONS[match[2]], [match[1]])
    if "=" in text:
        equation = re.sub(r"^(?:方程\s*|solve\s+)", "", text)
        equation = re.sub(r"\s*的(?:实数)?(?:解|解集)$", "", equation)
        return _equation(equation)
    return Solution("scalar", _number(re.sub(r"\s*的值$", "", text)))


def _equal(left: sp.Expr, right: sp.Expr) -> bool | None:
    if left == right:
        return True
    if left in (sp.oo, -sp.oo) or right in (sp.oo, -sp.oo):
        return False
    difference = sp.cancel(left - right)
    if difference.free_symbols:
        x, = difference.free_symbols
        return _poly(difference.as_numer_denom()[0], x).is_zero
    return difference.is_zero


def _root_answer(text: str, x: sp.Symbol) -> tuple[sp.Expr, ...]:
    if text in {"{}", "∅", "无解", "无实数解", "EmptySet"}:
        return ()
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1]
    roots = []
    for part in _split(text.replace("或", ","), ",;"):
        value = re.sub(rf"^{x.name}(?:_(?:[1-4]|\{{[1-4]\}}))?\s*=\s*", "", part)
        if value.startswith("±"):
            positive = _number(value[1:])
            roots.extend((-positive, positive))
        else:
            roots.append(_number(value))
    return tuple(roots)


def _contains(values: tuple[sp.Expr, ...], target: sp.Expr) -> bool | None:
    comparisons = [_equal(value, target) for value in values]
    if True in comparisons:
        return True
    return None if None in comparisons else False


def _compare_roots(expected: tuple[sp.Expr, ...], proposed: tuple[sp.Expr, ...]) -> bool | None:
    matches = [_contains(proposed, value) for value in expected]
    matches.extend(_contains(expected, value) for value in proposed)
    if False in matches:
        return False
    return None if None in matches else True


def _compare_primitive(text: str, expected: sp.Expr, x: sp.Symbol) -> bool:
    constant = _INTEGRATION_CONSTANT
    expr = _parse(text, {x.name: x, "C": constant}, max_degree=_MAX_DEGREE + 1)
    offset = sp.cancel(expr.value - expected)
    if x in offset.free_symbols or constant not in offset.free_symbols:
        return False

    for denominator in expr.denominators:
        if constant in denominator.free_symbols:
            if _has_real_zero(denominator, constant):
                return False
        elif _has_real_zero(denominator, x):
            raise Unsupported

    numerator, denominator = (
        sp.Poly(term, constant, domain=sp.EX) for term in offset.as_numer_denom()
    )
    for polynomial in (numerator, denominator):
        if polynomial.LC().is_zero is not False or any(
            coefficient.is_real is not True or coefficient.is_finite is not True
            for coefficient in polynomial.all_coeffs()
        ):
            raise Unsupported

    # A rational function without real poles covers R iff its ends diverge with opposite signs.
    degree_difference = numerator.degree() - denominator.degree()
    return bool(degree_difference > 0 and degree_difference % 2 == 1)


def _compare(solution: Solution, answer: str) -> bool | None:
    text = _normalize(answer)
    expected, x = solution.value, solution.variable
    if isinstance(expected, tuple) and x is not None:
        return _compare_roots(expected, _root_answer(text, x))
    if isinstance(expected, sp.MatrixBase):
        return bool(expected == _matrix(text))
    if not isinstance(expected, sp.Expr):
        raise Unsupported
    if x is None:
        proposed_value = _INFINITIES[text] if text in _INFINITIES else _number(text)
        return _equal(expected, proposed_value)
    text = re.sub(rf"^(?:y'?|f'?\({x.name}\))\s*=\s*", "", text)
    if solution.mode == "primitive":
        return _compare_primitive(text, expected, x)
    expr = _expr(text, x)
    _defined_everywhere(expr, x)
    return _equal(expected, expr.value)


def _try_compare(solution: Solution, text: str) -> bool | None:
    try:
        return _compare(solution, text)
    except Unsupported:
        return None


def _compare_root_options(
    solution: Solution, answer: str, options: list[str],
) -> tuple[bool | None, list[bool | None]]:
    if not isinstance(solution.value, tuple) or solution.variable is None:
        raise Unsupported
    correct = []
    option_matches = []
    for option in options:
        try:
            root, = _root_answer(_normalize(option), solution.variable)
        except ValueError:
            option_matches.append(None)
            continue
        match = _contains(solution.value, root)
        option_matches.append(match)
        if match:
            correct.append(root)
    matches = None
    if options and None not in option_matches:
        submitted = Solution("roots", tuple(correct), solution.variable)
        matches = _try_compare(submitted, answer)
    return matches, option_matches


def _process(stem: str, answer: str | None, options: list[str]) -> dict[str, object]:
    try:
        solution = _solve(stem)
        if solution.mode == "scalar" and isinstance(solution.value, sp.Expr):
            if solution.value not in (sp.oo, -sp.oo) and (
                solution.value.is_real is not True or solution.value.is_finite is not True
            ):
                raise Unsupported
    except Unsupported:
        return {"status": "unsupported"}
    outcome: dict[str, object] = {"status": "solved", "answer": solution.answer()}
    if len(str(outcome["answer"])) > 1024:
        return {"status": "unsupported"}
    if answer is not None:
        if solution.mode == "root_options":
            matches, option_matches = _compare_root_options(solution, answer, options)
        else:
            matches = _try_compare(solution, answer)
            option_matches = [_try_compare(solution, option) for option in options]
        outcome["answer_matches"] = matches
        if None not in option_matches and (options or solution.mode != "root_options"):
            outcome["true_option_indices"] = [i for i, match in enumerate(option_matches) if match]
        if matches is None or None in option_matches:
            outcome["status"] = "unsupported"
    return outcome


def _main() -> None:
    stem, answer, options = json.load(sys.stdin)
    print(json.dumps(_process(stem, answer, options)))


if __name__ == "__main__":
    _main()
