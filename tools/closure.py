"""Static import-closure and dangling-reference reporter.

Used by the extraction workflow to answer two questions without installing
dependencies and without importing anything:

1. Given one or more root modules, which files does the graph reach?
2. Which ``MathCraft.*`` modules are referenced by the surviving tree but
   no longer exist?  Those references are exactly the points that need a stub,
   an adapter, or deletion.

Usage::

    python tools/closure.py roots MathCraft.api.main MathCraft.knowledge.manager
    python tools/closure.py dangling
    python tools/closure.py dangling --json out.json
    python tools/closure.py stats
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "backend"
PACKAGE_NAME = "MathCraft"
CODE_ROOT = SOURCE_ROOT / PACKAGE_NAME


def module_name_for(path: Path) -> str:
    rel = path.relative_to(SOURCE_ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def build_index() -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in CODE_ROOT.rglob("*.py"):
        index[module_name_for(path)] = path
    return index


def resolve_relative(module: str, level: int, name: str | None, *, is_package: bool) -> str:
    """Resolve ``from ..x import y`` given the importing module's name.

    ``from .`` (level 1) inside a package's ``__init__`` refers to the package
    itself; inside a plain module it refers to that module's package. Each extra
    level walks one package further up.
    """
    parts = module.split(".")
    if is_package:
        base_len = len(parts) - (level - 1) if level > 1 else len(parts)
    else:
        base_len = len(parts) - level
    prefix = ".".join(parts[: max(base_len, 0)])
    if name:
        return f"{prefix}.{name}" if prefix else name
    return prefix


@dataclass
class FileInfo:
    module: str
    path: Path
    loc: int
    imports: set[str] = field(default_factory=set)


def parse_file(module: str, path: Path, include_nested: bool, *, is_package: bool) -> FileInfo:
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source)
    info = FileInfo(module=module, path=path, loc=source.count("\n") + 1)

    def add(name: str) -> None:
        if name.startswith(PACKAGE_NAME):
            info.imports.add(name)
            parts = name.split(".")
            for i in range(len(parts), 1, -1):
                info.imports.add(".".join(parts[:i]))

    stack = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = resolve_relative(module, node.level, node.module, is_package=is_package)
            else:
                base = node.module or ""
            if base.startswith(PACKAGE_NAME):
                add(base)
                for alias in node.names:
                    if alias.name != "*":
                        add(f"{base}.{alias.name}")
        if include_nested:
            stack.extend(ast.iter_child_nodes(node))
        else:
            # Module level only: descend into blocks but skip function bodies.
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                stack.append(child)
    return info


def load_tree(include_nested: bool) -> dict[str, FileInfo]:
    infos: dict[str, FileInfo] = {}
    for path in CODE_ROOT.rglob("*.py"):
        module = module_name_for(path)
        try:
            infos[module] = parse_file(
                module, path, include_nested, is_package=path.name == "__init__.py"
            )
        except SyntaxError as exc:  # pragma: no cover - defensive
            print(f"SKIP {module}: {exc}", file=sys.stderr)
    return infos


def closure(infos: dict[str, FileInfo], roots: list[str]) -> set[str]:
    seen: set[str] = set()
    queue = list(roots)
    while queue:
        module = queue.pop()
        if module in seen or module not in infos:
            continue
        seen.add(module)
        queue.extend(infos[module].imports - seen)
    return seen


def cmd_roots(args: argparse.Namespace) -> int:
    infos = load_tree(include_nested=args.full)
    reached = closure(infos, args.roots)
    total = 0
    for module in sorted(reached):
        info = infos[module]
        total += info.loc
        if args.verbose:
            print(f"{info.loc:6d}  {module}")
    print(f"modules={len(reached)} loc={total}")
    if args.json:
        payload = {
            "roots": args.roots,
            "full": args.full,
            "modules": {m: {"path": str(infos[m].path), "loc": infos[m].loc} for m in sorted(reached)},
        }
        Path(args.json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


def cmd_dangling(args: argparse.Namespace) -> int:
    infos = load_tree(include_nested=True)
    existing = set(infos)
    # Also treat namespace packages (dirs with no __init__) as existing.
    for path in CODE_ROOT.rglob("*"):
        if path.is_dir() and any(path.glob("*.py")):
            existing.add(module_name_for(path / "__init__.py").removesuffix(".__init__"))

    missing: dict[str, set[str]] = defaultdict(set)
    for module, info in infos.items():
        for ref in info.imports:
            if ref in existing:
                continue
            # ``from pkg import name`` where name is an attribute, not a module.
            parent = ref.rsplit(".", 1)[0]
            if parent in existing:
                continue
            missing[ref].add(module)

    rows = sorted(missing.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    for ref, importers in rows:
        sample = ", ".join(sorted(importers)[:3])
        more = "" if len(importers) <= 3 else f" (+{len(importers) - 3})"
        print(f"{ref}\n    <- {sample}{more}")
    print(f"dangling={len(rows)}")
    if args.json:
        Path(args.json).write_text(
            json.dumps({k: sorted(v) for k, v in rows}, indent=2), encoding="utf-8"
        )
    return 0 if not rows else 1


def cmd_stats(args: argparse.Namespace) -> int:
    infos = load_tree(include_nested=False)
    by_top: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    for module, info in infos.items():
        top = ".".join(module.split(".")[:2])
        by_top[top] += info.loc
        counts[top] += 1
    total = sum(by_top.values())
    for top in sorted(by_top, key=lambda k: -by_top[k]):
        print(f"{by_top[top]:8d}  {counts[top]:4d}  {top}")
    print(f"TOTAL {total} loc in {len(infos)} modules")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_roots = sub.add_parser("roots", help="compute the import closure of root modules")
    p_roots.add_argument("roots", nargs="+")
    p_roots.add_argument("--full", action="store_true", help="include function-local imports")
    p_roots.add_argument("--json", help="write the result as JSON")
    p_roots.add_argument("-v", "--verbose", action="store_true")
    p_roots.set_defaults(func=cmd_roots)

    p_dangling = sub.add_parser("dangling", help="list references to modules that no longer exist")
    p_dangling.add_argument("--json", help="write the result as JSON")
    p_dangling.set_defaults(func=cmd_dangling)

    p_stats = sub.add_parser("stats", help="module counts and LOC by top-level package")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
