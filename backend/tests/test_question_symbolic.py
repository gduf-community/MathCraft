"""Check exact symbolic results, fail-closed inputs, and worker lifecycle."""

from pathlib import Path

import pytest

from app.services import question_symbolic as symbolic
from app.services._question_symbolic_worker import _process
from app.services.generation_cancellation import GenerationCanceled


@pytest.mark.parametrize(
    ("stem", "answer", "expected"),
    [
        ("计算 $0.1+0.2$ 的值。", "3/10", "3/10"),
        ("计算 $2³$ 的值。", "8", "8"),
        ("已知 $f(x)=x^2+1$，求 $f(2)$ 的值。", "5", "5"),
        (r"化简 $\frac{x^{2}+1}{x^2+1}$。", "1", "1"),
        ("求函数 $y=x^2$ 的导数。", "2x", "2*x"),
        ("求 $y=x^3$ 在 $x=1$ 处的导数。", "3", "3"),
        (r"求方程 $x^2=2$ 的实数解。", r"x=\pm\sqrt{2}", "{-sqrt(2), sqrt(2)}"),
        ("solve (x^2-1)/(x-1)=2", "无实数解", "{}"),
        (r"求极限 $\lim_{x\to 1}\frac{x^2-1}{x-1}$。", "2", "2"),
        (r"求极限 $\lim_{x\to 0^{+}}\frac{1}{x}$。", r"+\infty", "oo"),
        (r"计算定积分 $\int_0^1 x^2\,\mathrm{d}x$。", "1/3", "1/3"),
        (r"计算不定积分 $\int 2x\,dx$。", "x^2+C+3", "x**2 + C"),
        (r"求矩阵 $\begin{pmatrix}1&2\\3&4\end{pmatrix}$ 的行列式。", "-2", "-2"),
        ("inverse([[1,2],[3,4]])", "[[-2,1],[3/2,-1/2]]", "[[-2, 1], [3/2, -1/2]]"),
        ("matmul([[1,2]],[[3],[4]])", "[[11]]", "[[11]]"),
    ],
)
def test_exact_operation_families(stem: str, answer: str, expected: str) -> None:
    assert _process(stem, answer, []) == {
        "status": "solved",
        "answer": expected,
        "answer_matches": True,
        "true_option_indices": [],
    }


@pytest.mark.parametrize(
    "stem",
    [
        "已知 $x>0$，求函数 $y=x^2$ 的导数。",
        "计算 $1+2$，并计算 $3+4$。",
        "value(x/x,x,0)",
        "diff((x^2-1)/(x-1),x)",
        "求函数 $y=x^2$ 的导数值。",
        "limit(1/x,x,0)",
        "integral(1/x,x,-1,1)",
        "inverse([[1,2],[2,4]])",
        "solve (x-1)/(x-1)=1",
        "solve x+y=2",
        "1/2(3)",
        "2 3",
        "(9^12)^200",
        "limit(((x+1)^12)^12,x,1)",
        "abs(-2)",
        "sqrt.__call__(4)",
    ],
)
def test_unsupported_stems_fail_closed(stem: str) -> None:
    assert _process(stem, None, []) == {"status": "unsupported"}


def test_public_verification_compares_whole_solution_sets() -> None:
    result = symbolic.solve_symbolic("求方程 $x^2=4$ 的实数解。", "single")
    assert result.status == "solved"
    assert result.answer == "{-2, 2}"
    verified = symbolic.verify_symbolic(result, "2", ("2", "{2, -2}", "{-2, 2, 3}"))
    assert verified.status == "solved"
    assert verified.answer_matches is False
    assert verified.true_option_indices == (1,)


def test_explicit_selection_compares_individual_roots() -> None:
    stem = "下列哪些是方程 $x^2=4$ 的实数解？"
    result = symbolic.solve_symbolic(stem, "multiple")
    verified = symbolic.verify_symbolic(result, "x=±2", ("x=-2", "1", "2"))
    assert verified.status == "solved"
    assert verified.answer_matches is True
    assert verified.true_option_indices == (0, 2)

    # The choice list may contain only a proper subset of the real roots.
    partial = _process(stem, "2", ["1", "2"])
    assert partial["answer_matches"] is True
    assert partial["true_option_indices"] == [1]
    assert _process(stem, "2", [])["status"] == "unsupported"


def test_comparison_distinguishes_mismatch_and_unknown_option() -> None:
    result = _process("0.1 + 0.2", "0.300000000000000001", ["3/10", "以上都不是"])
    assert result == {
        "status": "unsupported",
        "answer": "3/10",
        "answer_matches": False,
    }
    assert _process("diff(x^2,x)", "2x*x/x", [])["answer_matches"] is None


@pytest.mark.parametrize(
    ("stem", "canonical"),
    [
        ("integral(0,x)", "C"),
        ("integral(x^12,x)", "x**13/13 + C"),
    ],
)
def test_indefinite_integral_canonical_answer_round_trips(stem: str, canonical: str) -> None:
    assert _process(stem, None, []) == {"status": "solved", "answer": canonical}
    assert _process(stem, canonical, [])["answer_matches"] is True


@pytest.mark.parametrize(
    ("answer", "matches"),
    [
        ("x^2-C/2+3", True),
        ("x^2+2*C+pi", True),
        ("x^2+C^3", True),
        ("x^2+C^3/(1+C^2)", True),
        ("x^2", False),
        ("x^2+3", False),
        ("x^2+C-C", False),
        ("x^2+C^2", False),
        ("x^2+C/(1+C^2)", False),
        ("x^2+1/C", False),
        ("x^2+(C^2-1)/(C-1)", False),
        ("x^2+C*x", False),
        ("x^2+Cx", None),
    ],
)
def test_indefinite_integral_requires_the_full_family(answer: str, matches: bool | None) -> None:
    result = _process("integral(2x,x)", answer, [])
    assert result["status"] == ("unsupported" if matches is None else "solved")
    assert result["answer_matches"] is matches


@pytest.mark.parametrize("stop", ["deadline", "callback", "exception"])
def test_timeout_and_cancellation_reap_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop: str,
) -> None:
    script = tmp_path / "slow_worker.py"
    script.write_text("import time\n\ntime.sleep(60)\n", encoding="utf-8")
    monkeypatch.setattr(symbolic, "_WORKER_PATH", script)
    monkeypatch.setattr(symbolic, "_TIMEOUT_SECONDS", 1.0)
    processes = []
    start_process = symbolic.subprocess.Popen

    def record_process(*args, **kwargs):
        process = start_process(*args, **kwargs)
        processes.append(process)
        return process

    def cancel_check() -> bool:
        if processes and stop == "exception":
            raise GenerationCanceled
        return bool(processes) and stop == "callback"

    monkeypatch.setattr(symbolic.subprocess, "Popen", record_process)
    if stop == "exception":
        with pytest.raises(GenerationCanceled):
            symbolic.solve_symbolic("1+2", "compute", cancel_check)
    else:
        assert symbolic.solve_symbolic("1+2", "compute", cancel_check).status == "timeout"
    assert len(processes) == 1
    assert processes[0].poll() is not None


def test_worker_failure_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "failed_worker.py"
    script.write_text("raise SystemExit(3)\n", encoding="utf-8")
    monkeypatch.setattr(symbolic, "_WORKER_PATH", script)
    assert symbolic.solve_symbolic("1+2", "compute").status == "error"
