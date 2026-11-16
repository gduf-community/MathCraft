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
