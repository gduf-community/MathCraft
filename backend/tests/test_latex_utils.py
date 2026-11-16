import pytest

from app.schemas.question import Question, QuestionType
from app.services.latex_utils import fix_delimiters, latex_issue


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
