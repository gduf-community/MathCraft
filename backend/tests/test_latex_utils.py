import json

import pytest

from app.schemas.question import Question, QuestionType
from app.services.latex_utils import (
    escape_bare_commands_in_json,
    fix_delimiters,
    latex_issue,
    restore_escape_artifacts,
)


def test_literal_newline():
    out = fix_delimiters("设 A = 矩阵。\\n (1) 计算 |A|; \\n (2) 计算 tr(A)。")
    assert "\\n" not in out and "\n" in out


def test_bare_blank_command():
    out = fix_delimiters(r"r(A) = \underline{\hspace{2cm}}。")
    assert out == r"r(A) = $\underline{\hspace{2cm}}$。"
    assert latex_issue(out) is None


def test_paren_delimiters():
    assert fix_delimiters(r"已知 \(x=2\) 可得。") == r"已知 $x=2$ 可得。"


def test_normal_formulas_untouched():
    text = "由 $x=2$ 与 $y=3$ 联立，得 $x+y=5$。"
    assert fix_delimiters(text) == text


def test_display_formula_untouched():
    text = "$$S=\\int_0^{+\\infty}xe^{-x}\\,dx=1$$ 分部积分即得。"
    assert fix_delimiters(text) == text
    assert latex_issue(text) is None


def test_inline_in_mixed_text():
    text = "解析：先求 $f'(x)=3x^2$，代入 $x=1$ 得 $3$。"
    assert fix_delimiters(text) == text


def test_matrix_command_wrapped():
    out = fix_delimiters(r"设 A = \begin{pmatrix}1&2\\3&4\end{pmatrix}。")
    assert "$" in out and latex_issue(out) is None


def test_unpaired_dollar_preserved():
    text = "奇数个 $ 符号"
    assert fix_delimiters(text) == text
    assert latex_issue(text) == "$ 定界不配对"


def test_fraction_wrapped():
    out = fix_delimiters(r"结果为 \frac{1}{2}。")
    assert out == r"结果为 $\frac{1}{2}$。"


def test_newline_repair_preserves_commands_starting_with_n():
    text = r"由 $\nabla f\neq 0$。\n（1）计算。"
    assert fix_delimiters(text) == "由 $\\nabla f\\neq 0$。\n（1）计算。"
    assert fix_delimiters(r"\nabla 与 \neq") == r"$\nabla$ 与 $\neq$"


def test_bare_commands_next_to_one_complete_formula_are_repaired():
    assert fix_delimiters(r"已知 $x=1$，结果为 \frac{1}{2}。") == (
        r"已知 $x=1$，结果为 $\frac{1}{2}$。"
    )


def test_matrix_environment_is_wrapped_as_one_formula():
    matrix = r"\begin{pmatrix}1&2\\3&4\end{pmatrix}"
    assert fix_delimiters("设 A=" + matrix) == "设 A=$" + matrix + "$"


@pytest.mark.parametrize("text", [r"费用 \$5 与 $x=1$", r"费用 \$5 与 \$6"])
def test_escaped_currency_is_preserved(text):
    assert fix_delimiters(text) == text
    assert latex_issue(text) is None


@pytest.mark.parametrize("text", ["$$x=1", "$x=1$$", "$$x$", "$$x$$ 与 $y"])
def test_unpaired_display_or_mixed_delimiters_are_rejected(text):
    assert fix_delimiters(text) == text
    assert latex_issue(text) is not None


def test_question_normalizes_all_option_input_forms_without_dropping_invalid_fields():
    question = Question(
        type=QuestionType.single, stem=r"由 $\nabla f\neq 0$。\n计算",
        options=["A. \\frac{1}{2}", {"label": "B", "text": r"\sqrt{2}"}],
        answer=r"\frac{1}{2}", analysis=r"由 \(x=1\) 可得。",
    )
    assert question.options[0].text == r"$\frac{1}{2}$"
    assert question.options[1].text == r"$\sqrt{2}$"
    assert question.answer == r"$\frac{1}{2}$"
    assert r"\nabla" in question.stem and r"\neq" in question.stem
    assert "\n" in question.stem
    assert question.analysis == "由 $x=1$ 可得。"


def test_question_rejects_invalid_option_instead_of_silently_removing_it():
    with pytest.raises(ValueError):
        Question(type=QuestionType.single, stem="题干", options=[{"label": "A", "text": None}])


@pytest.mark.parametrize(
    "raw, expected",
    [
        (r'{"text":"$\neq \frac{1}{2} \times \beta \right)$"}',
         r"$\neq \frac{1}{2} \times \beta \right)$"),
        (r'{"text":"$\\neq \\frac{1}{2}$"}', r"$\neq \frac{1}{2}$"),
        (r'{"text":"\nu \to \ni \sqrt{2} \custom{3}"}',
         r"\nu \to \ni \sqrt{2} \custom{3}"),
        (r'{"text":"费用 \$5，结果 $\frac{1}{2}$"}', r"费用 \$5，结果 $\frac{1}{2}$"),
        (r'{"text":"第一行\n第二行\t制表\u4e2d，\"引用\""}',
         '第一行\n第二行\t制表中，"引用"'),
    ],
)
def test_raw_json_repairs_commands_without_damaging_valid_escapes(raw, expected):
    repaired = escape_bare_commands_in_json(raw)
    assert json.loads(repaired)["text"] == expected
    assert escape_bare_commands_in_json(repaired) == repaired


@pytest.mark.parametrize("command", ["neq", "frac", "times", "beta", "right"])
def test_control_characters_are_restored_after_json_decoding(command):
    damaged = json.loads('{"text":"$\\' + command + ' {x}$"}')["text"]
    expected = "$\\" + command + " {x}$"
    assert restore_escape_artifacts(damaged) == expected
    assert fix_delimiters(damaged) == expected
    assert latex_issue(expected) is None


def test_restore_preserves_real_whitespace_and_command_boundaries():
    text = "第一行\nexample\timetable\rightward"
    assert restore_escape_artifacts(text) == text
    assert restore_escape_artifacts(r"$\\neq$ 与 $\\frac{1}{2}$") == (
        r"$\neq$ 与 $\frac{1}{2}$"
    )


@pytest.mark.parametrize("control", ["\b", "\f"])
def test_unrepairable_control_characters_are_rejected(control):
    assert latex_issue(f"内容{control}unknown") == "残留控制字符（反斜杠转义损坏）"


@pytest.mark.parametrize("environment, delimiter", [("aligned", "$$"), ("pmatrix", "$")])
def test_raw_json_environment_repair_combines_with_currency_and_existing_formula(
    environment, delimiter,
):
    body = r"\begin{" + environment + r"}x&=\frac{1}{2}\\3&=4\end{" + environment + "}"
    text = r"费用 \$5 与 $x=1$，" + body
    raw = '{"text":"' + text.replace(r"\\", r"\\\\") + '"}'
    parsed = json.loads(escape_bare_commands_in_json(raw))["text"]
    expected = r"费用 \$5 与 $x=1$，" + delimiter + body + delimiter
    assert fix_delimiters(parsed) == expected
    assert fix_delimiters(expected) == expected
    assert latex_issue(expected) is None


def test_nested_environments_are_wrapped_together():
    body = r"\begin{aligned}x&=\begin{pmatrix}1\\2\end{pmatrix}\\y&=3\end{aligned}"
    assert fix_delimiters(body) == "$$" + body + "$$"


@pytest.mark.parametrize("delimiters", ["$$x", "$x$$", "$$x$", "$$x$$ 与 $y"])
def test_json_command_repair_does_not_hide_invalid_delimiters(delimiters):
    raw = r'{"text":"费用 \$5，\frac{1}{2}，' + delimiters + '"}'
    parsed = json.loads(escape_bare_commands_in_json(raw))["text"]
    assert fix_delimiters(parsed) == parsed
    assert latex_issue(parsed) is not None


def test_escaped_currency_inside_formulas_does_not_split_math_spans():
    text = r"＄：\$5，$\text{费用 \$5}+\frac{1}{2}$，$$\text{费用 \$6}$$，\sqrt{2}"
    expected = text.removesuffix(r"\sqrt{2}") + r"$\sqrt{2}$"
    assert fix_delimiters(text) == expected
    assert latex_issue(expected) is None


@pytest.mark.parametrize("count", [1, 3])
def test_odd_backslashes_keep_currency_escaped(count):
    text = "费用 " + "\\" * count + "$5，" + r"\frac{1}{2}"
    expected = text.removesuffix(r"\frac{1}{2}") + r"$\frac{1}{2}$"
    assert fix_delimiters(text) == expected
    assert latex_issue(expected) is None


@pytest.mark.parametrize("count", [2, 4])
def test_even_backslashes_leave_dollar_as_a_delimiter(count):
    text = "\\" * count + "$x"
    assert fix_delimiters(text) == text
    assert latex_issue(text) == "$ 定界不配对"


def test_escaped_dollar_adjacent_to_inline_formula_is_preserved():
    text = r"费用 \$$x$，\frac{1}{2}"
    expected = r"费用 \$$x$，$\frac{1}{2}$"
    assert fix_delimiters(text) == expected
    assert latex_issue(expected) is None


@pytest.mark.parametrize(
    "environment, delimiter",
    [("pmatrix", "$"), ("bmatrix", "$"), ("aligned", "$$"), ("cases", "$$")],
)
@pytest.mark.parametrize("command", [r"\frac{1}{2}", r"\nabla f", r"\custom{x}"])
@pytest.mark.parametrize("count", [3, 5])
def test_environment_row_separator_before_command_is_preserved(
    environment: str, delimiter: str, command: str, count: int,
) -> None:
    body = (
        r"\begin{" + environment + "}1&2" + "\\" * (count - 1)
        + command + r"&4\end{" + environment + "}"
    )
    expected = delimiter + body + delimiter
    assert restore_escape_artifacts(body) == body
    assert fix_delimiters(body) == expected
    assert fix_delimiters(expected) == expected
    assert latex_issue(expected) is None


def test_nested_row_environments_preserve_separators_before_begin_and_end() -> None:
    body = (
        r"\begin{aligned}x&=1\\\begin{pmatrix}1\\\sqrt{2}\\\end{pmatrix}"
        r"\\\frac{1}{2}&=y\end{aligned}"
    )
    assert restore_escape_artifacts(body) == body
    assert fix_delimiters(body) == "$$" + body + "$$"
    assert fix_delimiters("$$" + body + "$$") == "$$" + body + "$$"


@pytest.mark.parametrize("count", [2, 3, 4])
def test_agent_overescaped_commands_are_still_repaired_outside_row_environments(count: int) -> None:
    text = "$" + "\\" * count + "frac{1}{2}$"
    expected = r"$\frac{1}{2}$"
    assert restore_escape_artifacts(text) == expected
    assert fix_delimiters(text) == expected


def test_environment_context_ends_before_agent_overescaped_commands() -> None:
    text = r"$\begin{pmatrix}1\\\sqrt{2}\end{pmatrix}+\\\frac{1}{2}$"
    expected = r"$\begin{pmatrix}1\\\sqrt{2}\end{pmatrix}+\frac{1}{2}$"
    assert restore_escape_artifacts(text) == expected
    assert fix_delimiters(text) == expected


def test_json_and_question_normalization_preserve_matrix_rows_and_repair_overescaping() -> None:
    matrix = r"\begin{pmatrix}1&2\\\frac{1}{2}&\\sqrt{2}\end{pmatrix}"
    raw = json.dumps({"stem": matrix, "answer": r"$\\frac{1}{2}$"})
    parsed = json.loads(escape_bare_commands_in_json(raw))
    question = Question(type=QuestionType.compute, **parsed)
    expected = r"$\begin{pmatrix}1&2\\\frac{1}{2}&\sqrt{2}\end{pmatrix}$"
    assert question.stem == expected
    assert question.answer == r"$\frac{1}{2}$"
    assert fix_delimiters(question.stem) == expected


@pytest.mark.parametrize("count", [2, 4])
def test_agent_overescaped_commands_inside_repaired_environment(count: int) -> None:
    text = (
        r"\\begin{pmatrix}1&" + "\\" * count
        + r"sqrt{2}\\3&4\\end{pmatrix}"
    )
    expected = r"\begin{pmatrix}1&\sqrt{2}\\3&4\end{pmatrix}"
    assert restore_escape_artifacts(text) == expected
    assert fix_delimiters(text) == "$" + expected + "$"
