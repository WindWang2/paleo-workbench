"""#1028 — anti-mirage guard for the E2E suite.

`tests/test_issue_940_misc.py` already bans `skipif(True)` placeholders; the
2026-08 audit still found `assert True` padding, `or True` tautologies and
`importorskip` calls on modules that can never exist (permanently-skipped
tests verifying nothing). This guard scans the E2E tree so those shapes
cannot quietly return.
"""

from __future__ import annotations

import re
from pathlib import Path

E2E_DIR = Path(__file__).resolve().parent

# importorskip on a module that can never exist → a test that only ever skips
_FORBIDDEN_IMPORTORSKIP = re.compile(
    r"importorskip\(\s*[\"'](?:non_existent_|completely_unknown_)"
)


def _python_files():
    # this guard itself mentions the forbidden shapes in prose/regex
    return [p for p in sorted(E2E_DIR.glob("test_*.py")) if p.name != Path(__file__).name]


def test_no_tautological_assert_true():
    offenders = []
    for path in _python_files():
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if line.strip() == "assert True":
                offenders.append(f"{path.name}:{lineno}")
    assert not offenders, f"tautological `assert True` padding: {offenders}"


def test_no_or_true_tautologies():
    offenders = []
    for path in _python_files():
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if re.search(r"\bor True\b", line):
                offenders.append(f"{path.name}:{lineno}")
    assert not offenders, f"`or True` makes the assertion unfalsifiable: {offenders}"


def test_no_importorskip_on_impossible_modules():
    offenders = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        for match in _FORBIDDEN_IMPORTORSKIP.finditer(text):
            lineno = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.name}:{lineno}")
    assert not offenders, (
        "importorskip on a never-existing module is a permanently-skipped "
        f"test: {offenders}"
    )


def test_no_local_preview_settings_shadow_class():
    """The production PreviewSettings must not be shadowed by local copies."""
    offenders = []
    for path in _python_files():
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if re.search(r"class PreviewSettings\b", line):
                offenders.append(f"{path.name}:{lineno}")
    assert not offenders, (
        "shadow the real paleo_workbench.resources.preview_settings class "
        f"instead of redefining it locally: {offenders}"
    )
