"""#1028 — anti-mirage guard for the test tree.

`tests/test_issue_940_misc.py` already bans always-true skip markers; the
2026-08 audit still found assert-True padding, or-True tautologies and
`importorskip` calls on modules that can never exist (permanently-skipped
tests verifying nothing). This guard parses the test tree with the AST so
trivial rewrites of the same shapes (`assert (True)`, `assert not not True`,
`assert all([True])`, trailing comments) cannot evade it.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1]

# importorskip on a module that can never exist → a test that only ever skips
_FORBIDDEN_IMPORTORSKIP = (
    "non_existent_",
    "completely_unknown_",
)


def _python_files():
    # whole test tree (not just e2e); skip this guard itself
    return [
        p
        for p in sorted(TESTS_DIR.rglob("*.py"))
        if p.name != Path(__file__).name and "__pycache__" not in p.parts
    ]


def _is_truthy_constant(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return bool(node.value)
    return False


def _assert_tautologies(tree: ast.AST) -> list[str]:
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            if _is_truthy_constant(node.test):
                findings.append(f"line {node.lineno}: assert <truthy constant>")
            elif (
                isinstance(node.test, ast.UnaryOp)
                and isinstance(node.test.op, ast.Not)
            ):
                inner = node.test.operand
                if (
                    isinstance(inner, ast.UnaryOp)
                    and isinstance(inner.op, ast.Not)
                    and _is_truthy_constant(inner.operand)
                ):
                    findings.append(f"line {node.lineno}: assert not not <truthy>")
            elif isinstance(node.test, ast.BoolOp):
                for value in node.test.values:
                    if _is_truthy_constant(value):
                        findings.append(
                            f"line {node.lineno}: `or/and True` tautology operand"
                        )
                        break
            elif isinstance(node.test, ast.Call):
                func = node.test.func
                if (
                    isinstance(func, ast.Name)
                    and func.id == "all"
                    and node.test.args
                    and isinstance(node.test.args[0], ast.List)
                    and node.test.args[0].elts
                    and all(_is_truthy_constant(e) for e in node.test.args[0].elts)
                ):
                    findings.append(f"line {node.lineno}: assert all([truthy...])")
    return findings


def test_no_tautological_assertions():
    offenders = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue  # non-test helper artifacts are not our concern here
        for finding in _assert_tautologies(tree):
            offenders.append(f"{path.relative_to(TESTS_DIR)}:{finding}")
    assert not offenders, f"tautological assertions: {offenders}"


def test_no_importorskip_on_impossible_modules():
    offenders = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "importorskip"):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            module = str(node.args[0].value)
            if module.startswith(_FORBIDDEN_IMPORTORSKIP):
                line = node.lineno
                offenders.append(f"{path.relative_to(TESTS_DIR)}:{line} ({module})")
    assert not offenders, (
        "importorskip on a never-existing module is a permanently-skipped "
        f"test: {offenders}"
    )


def test_no_local_preview_settings_shadow_class():
    """The production PreviewSettings must not be shadowed by local copies."""
    offenders = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "PreviewSettings":
                offenders.append(f"{path.relative_to(TESTS_DIR)}:{node.lineno}")
    assert not offenders, (
        "shadow the real paleo_workbench.resources.preview_settings class "
        f"instead of redefining it locally: {offenders}"
    )
