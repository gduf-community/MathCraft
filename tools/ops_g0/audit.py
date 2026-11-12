"""Audit tracked source at pinned local refs without importing business configuration."""

import argparse
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HOOKS = {
    "backend/app/api/generate.py": ("start_generation", "generate_sync"),
    "backend/app/api/chat.py": ("send_message", "cancel_generation"),
    "backend/app/services/generation.py": ("run_generation_task", "persist_batch"),
    "backend/app/services/question_review.py": ("review_questions", "_solve_all", "_regen"),
}


def git(*arguments: str) -> str:
    """Read local Git metadata or tracked non-secret source."""
    return subprocess.check_output(["git", *arguments], cwd=ROOT).decode("utf-8")


def audit_ref(ref: str) -> dict:
    """Return SDK usage and handoff locations; absence is scoped to the audited ref."""
    paths = git("ls-tree", "-r", "--name-only", "-z", ref, "backend/app").split("\0")
    sdk_imports: list[dict] = []
    runner_calls: list[dict] = []
    hooks: list[dict] = []
    count = 0
    for path in paths:
        if not path.endswith(".py") or Path(path).name == "local_secrets.py":
            continue
        source = git("show", f"{ref}:{path}")
        tree = ast.parse(source, filename=path)
        count += 1
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "agents":
                sdk_imports.append({"path": path, "line": node.lineno, "module": node.module})
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "agents":
                        sdk_imports.append(
                            {"path": path, "line": node.lineno, "module": alias.name}
                        )
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"run", "run_sync", "run_streamed"}:
                    receiver = ast.unparse(node.func.value)
                    if receiver.endswith("Runner"):
                        runner_calls.append(
                            {"path": path, "line": node.lineno, "receiver": receiver}
                        )
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in HOOKS.get(
                path, ()
            ):
                hooks.append({"path": path, "line": node.lineno, "function": node.name})
    return {
        "ref": ref,
        "commit": git("rev-parse", ref).strip(),
        "audited_python_files": count,
        "sdk_imports": sdk_imports,
        "sdk_runner_calls": runner_calls,
        "candidate_handoff_locations": hooks,
        "actual_sdk_business_path_status": "NEEDS_EXECUTION_PROOF"
        if runner_calls
        else "NOT_FOUND_IN_AUDITED_REF",
    }


def main() -> None:
    """Write an exclusive, configuration-free A0 source audit."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    destination = args.output.resolve()
    allowed = ROOT / ".scratch/ops-g0-20261112"
    if not destination.is_relative_to(allowed):
        raise ValueError("Output must stay inside the isolated G0 evidence directory")
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "tracked local refs only; no runtime configuration or user data read",
        "refs": [audit_ref("main"), audit_ref("agent")],
        "a0_local_inventory": "COMPLETE",
        "external_handoff": "PENDING",
        "g0_business_entry_acceptance": "BLOCKED_EXTERNAL",
        "required_handoff": [
            "SDK implementation ref/commit and both actual business entry points",
            "authoritative execution events and cancellation acknowledgement",
            "async/thread/tool context propagation and run/trace association",
            "committed final delivery set and version/scoped review evidence",
            "fake model/tool injection seam for actual entry-point tests",
        ],
        "real_model_calls": 0,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"evidence": str(destination), **report}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
