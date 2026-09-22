#!/usr/bin/env python3
"""pwb_python_dependency_audit.py — audit that no Python runtime sneaks into the
native C++ product of paleo-workbench.

This is a static, evidence-based scanner. Every finding is derived from facts in
the tree:

  * the set of tracked files                       (``git ls-files``; falls back
    to a working-tree walk when git is unavailable),
  * the literal lines of every ``CMakeLists.txt`` / ``*.cmake`` that mention
    ``python`` (matched against the exact tokens the build system uses to shell
    out to an interpreter),
  * the contents of every ``pyproject.toml`` and packaging script,
  * the presence of pybind11 under ``libs/mapping_bind`` and any
    ``paleo_workbench/**/native_bind.py`` facade that catches ``ImportError``
    and falls back to the pure-Python implementation,
  * the ``from/import`` graph of ``tools/oracle/*.py`` vs the production
    ``paleo_workbench/`` package (to find modules used ONLY by oracle tooling).

The project rule this enforces: the native product must not depend on a Python
interpreter at build or run time, and a Python fallback seam must never be
reported as "native complete". Use ``--fail-on`` to gate CI: the process exits
non-zero when any *effective* finding of the chosen categories exists.

Pure Python 3 standard library. Windows + Linux. Deterministic sorted output.
Exit code 0 on success, 2 when ``--repo-root`` is not a directory.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Optional

DEV_TOOLING_PREFIXES = ("tests/", "tools/oracle/")

EXIT_OK = 0
EXIT_FAIL_ON = 1
EXIT_REPO = 2
EXIT_USAGE = 64

# Categories accepted by --fail-on. Anything else is rejected, because a typo
# would otherwise produce a gate that can never fire.
FAIL_ON_CATEGORIES = frozenset({
    "native_test_depends_on_python",
    "packaging_python_requirement",
    "python_fallback_seam",
    "oracle_only_module",
})

# CMake tokens that actually invoke / require a Python interpreter.
RE_FIND_PACKAGE = re.compile(r"find_package\s*\(\s*Python", re.IGNORECASE)
RE_COMMAND_PY = re.compile(r"COMMAND\s+(python|python3|\$\{PYTHON)", re.IGNORECASE)
RE_ADD_TEST_PY = re.compile(r"add_test\s*\([^)]*python", re.IGNORECASE)
RE_PY_EXEC = re.compile(r"Python3_EXECUTABLE", re.IGNORECASE)
RE_PYTHON3 = re.compile(r"\bpython3\b", re.IGNORECASE)
RE_WITH_PYTHON_OFF = re.compile(r"WITH_PYTHON\s*=\s*OFF", re.IGNORECASE)

IMPORT_RE = re.compile(r"(?:from|import)\s+([A-Za-z_][\w.]*)")


# --- git tracked enumeration -------------------------------------------------

def git_ls_files(repo_root: str) -> tuple[list[str], bool]:
    try:
        proc = subprocess.run(
            ["git", "ls-files"], cwd=repo_root,
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, "git ls-files")
        return [ln for ln in proc.stdout.splitlines() if ln], True
    except (OSError, subprocess.CalledProcessError):
        files: list[str] = []
        for dp, _dn, names in os.walk(repo_root):
            for nm in names:
                rel = os.path.relpath(os.path.join(dp, nm), repo_root).replace(os.sep, "/")
                if ".git/" in rel or rel.startswith(".git/"):
                    continue
                files.append(rel)
        return files, False


ARCHIVE_PRODUCT_PREFIX = "legacy/python_reference/product/"


def tracked_rel(path: str) -> str:
    """Normalize archived product paths back to their pre-retirement form so
    the audit keeps reasoning about ``paleo_workbench/...`` uniformly (the
    package was retired to legacy/python_reference/product; see
    docs/development/python-retirement/)."""
    if path.startswith(ARCHIVE_PRODUCT_PREFIX):
        return path[len(ARCHIVE_PRODUCT_PREFIX):]
    return path


def resolve_repo_path(repo_root: str, rel: str) -> str:
    """Map a normalized product path to its on-disk location (active tree,
    else the retirement archive)."""
    if rel.startswith("paleo_workbench/"):
        archived = os.path.join(repo_root, ARCHIVE_PRODUCT_PREFIX, rel)
        if os.path.exists(archived):
            return archived
    return os.path.join(repo_root, rel)


def read_lines(repo_root: str, rel: str) -> list[str]:
    try:
        with open(resolve_repo_path(repo_root, rel), encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()
    except OSError:
        return []


def classify_path(rel: str) -> str:
    if rel.startswith(DEV_TOOLING_PREFIXES):
        return "dev_tooling"
    return "native_test_depends_on_python"


# --- check 1: CMake shell-outs ----------------------------------------------

def check_cmake_python(tracked: list[str], repo_root: str) -> list[dict]:
    cmake_files = [f for f in tracked
                   if f.endswith(".cmake") or os.path.basename(f) == "CMakeLists.txt"]
    out: list[dict] = []
    for rel in cmake_files:
        for i, line in enumerate(read_lines(repo_root, rel), 1):
            low = line.lower()
            if "python" not in low:
                continue
            is_comment = line.strip().startswith("#")
            # decide the sub-kind
            if RE_FIND_PACKAGE.search(line):
                kind = "find_package"
            elif RE_COMMAND_PY.search(line):
                kind = "command"
            elif RE_ADD_TEST_PY.search(line):
                kind = "add_test"
            elif RE_PY_EXEC.search(line):
                kind = "python3_executable_ref"
            elif RE_PYTHON3.search(line):
                kind = "python3_ref"
            else:
                kind = "reference"
            # effective = a real build/test dependency, not a comment or a disable
            disable = bool(RE_WITH_PYTHON_OFF.search(line))
            effective = (not is_comment) and (not disable) and kind in (
                "find_package", "command", "add_test", "python3_executable_ref")
            finding = {
                "path": rel,
                "line": i,
                "text": line.strip(),
                "kind": kind,
                "classification": classify_path(rel),
                "vendored": rel.startswith("third_party/"),
                "is_comment": is_comment,
                "disables_python": disable,
                "effective": effective,
            }
            out.append(finding)
    out.sort(key=lambda d: (d["path"], d["line"]))
    return out


# --- check 2: packaging hard-requires Python --------------------------------

def check_packaging_python(tracked: list[str], repo_root: str) -> list[dict]:
    out: list[dict] = []

    def severity_for(rel: str) -> str:
        if rel.startswith("third_party/"):
            return "vendored_third_party"
        if rel.startswith(DEV_TOOLING_PREFIXES):
            return "dev_tooling"
        return "product_packaging_reference"

    pyproject = [f for f in tracked if os.path.basename(f) == "pyproject.toml"]
    for rel in pyproject:
        for i, line in enumerate(read_lines(repo_root, rel), 1):
            if "requires-python" in line:
                out.append({
                    "path": rel, "line": i, "text": line.strip(),
                    "severity": "dev_tooling" if rel.startswith(DEV_TOOLING_PREFIXES)
                    else "product_hard_requirement",
                    "note": "declares requires-python for the package",
                })
            if re.search(r"(install_requires|dependencies)\s*=.*python", line, re.I):
                out.append({
                    "path": rel, "line": i, "text": line.strip(),
                    "severity": "product_hard_requirement",
                    "note": "dependency list references python",
                })
    # packaging cmake / NSIS / CPack scripts referencing Python
    for rel in tracked:
        if not (rel.endswith(".cmake") or "packaging" in rel.lower()
                or rel.lower().endswith(".nsi")):
            continue
        if not any(p in rel for p in ("cmake/", "packaging", "CPack", ".nsi")):
            continue
        for i, line in enumerate(read_lines(repo_root, rel), 1):
            if "python" in line.lower() and "WITH_PYTHON=OFF" not in line:
                out.append({
                    "path": rel, "line": i, "text": line.strip(),
                    "severity": severity_for(rel),
                    "note": "packaging script references Python",
                })
    out.sort(key=lambda d: (d["path"], d["line"]))
    return out


# --- check 3: pybind / fallback seams ---------------------------------------

def check_pybind_seams(tracked: list[str], repo_root: str) -> dict:
    pybind_files = [f for f in tracked
                    if "pybind11" in f.lower() or "mapping_bind" in f.lower()]
    bind_locations = sorted({f.split("/")[0] + "/" + f.split("/")[1]
                             for f in pybind_files if f.startswith("libs/mapping_bind")})
    fallback_seams: list[dict] = []
    native_binds = sorted(f for f in tracked
                          if f.startswith("paleo_workbench/")
                          and os.path.basename(f) == "native_bind.py")
    for rel in native_binds:
        lines = read_lines(repo_root, rel)
        native_module = None
        try_except_lines: list[int] = []
        for i, line in enumerate(lines, 1):
            if re.search(r"except\s+ImportError", line):
                try_except_lines.append(i)
                # look back for the native import
                for j in range(max(0, i - 4), i):
                    m = re.search(r"\bimport\s+([A-Za-z_][\w.]*)", lines[j - 1])
                    if m and not m.group(1).startswith("paleo_workbench"):
                        native_module = m.group(1)
        has_cpp_dispatch = any("is None" in ln or "HAS_CPP" in ln for ln in lines)
        evidence = [ln.strip() for ln in lines
                    if re.search(r"except\s+ImportError|HAS_CPP|_kernel\s+is\s+None|"
                                 r"import\s+pwb_|ImportError", ln)]
        fallback_seams.append({
            "path": rel,
            "native_module": native_module,
            "try_except_lines": try_except_lines,
            "has_cpp_dispatch": has_cpp_dispatch,
            "evidence": evidence[:12],
            "rule": ("project rule: a Python fallback must never be reported as "
                     "native complete"),
        })
    return {
        "pybind_location": bind_locations,
        "pybind11_vendored": any("pybind11" in f for f in pybind_files),
        "fallback_seams": fallback_seams,
    }


# --- check 4: oracle-only modules -------------------------------------------

def check_oracle_only_modules(tracked: list[str], repo_root: str) -> list[dict]:
    oracle_files = [f for f in tracked
                    if f.startswith("tools/oracle/") and f.endswith(".py")]
    oracle_mods: dict[str, list[str]] = {}
    for rel in oracle_files:
        for m in IMPORT_RE.findall("\n".join(read_lines(repo_root, rel))):
            if m == "paleo_workbench" or m.startswith("paleo_workbench."):
                oracle_mods.setdefault(m, []).append(rel)
    prod_files = [f for f in tracked
                  if f.startswith("paleo_workbench/") and f.endswith(".py")
                  and not f.startswith("tools/oracle/")]
    prod_mods: set[str] = set()
    for rel in prod_files:
        for m in IMPORT_RE.findall("\n".join(read_lines(repo_root, rel))):
            if m == "paleo_workbench" or m.startswith("paleo_workbench."):
                prod_mods.add(m)
    only = sorted(set(oracle_mods) - prod_mods)
    out = [{"module": mod, "imported_by": sorted(oracle_mods[mod])} for mod in only]
    return out


# --- driver ------------------------------------------------------------------

def run_scan(repo_root: str) -> dict:
    tracked, git_available = git_ls_files(repo_root)
    tracked = [tracked_rel(t) for t in tracked]  # archived product paths -> pre-retirement form
    cmake = check_cmake_python(tracked, repo_root)
    packaging = check_packaging_python(tracked, repo_root)
    pybind = check_pybind_seams(tracked, repo_root)
    oracle_only = check_oracle_only_modules(tracked, repo_root)

    bad_cmake = [c for c in cmake if c["classification"] == "native_test_depends_on_python"]
    dev_cmake = [c for c in cmake if c["classification"] == "dev_tooling"]
    effective_bad = [c for c in bad_cmake if c["effective"]]
    comment_cmake = [c for c in cmake if c["is_comment"]]
    pkg_by_sev: dict[str, int] = {}
    for p in packaging:
        pkg_by_sev[p["severity"]] = pkg_by_sev.get(p["severity"], 0) + 1

    summary = {
        "git_available": git_available,
        "tracked_file_count": len(tracked),
        "cmake_python_total": len(cmake),
        "cmake_python_bad": len(bad_cmake),
        "cmake_python_bad_effective": len(effective_bad),
        "cmake_python_bad_vendored": sum(1 for c in bad_cmake if c["vendored"]),
        "cmake_python_comment_only": len(comment_cmake),
        "cmake_python_dev_tooling": len(dev_cmake),
        "packaging_python_requirements": len(packaging),
        "packaging_python_by_severity": dict(sorted(pkg_by_sev.items())),
        "python_fallback_seams": len(pybind["fallback_seams"]),
        "pybind_locations": len(pybind["pybind_location"]),
        "oracle_only_modules": len(oracle_only),
    }

    return {
        "tool": "pwb_python_dependency_audit",
        "repo_root": os.path.abspath(repo_root),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_available": git_available,
        "summary": summary,
        "cmake_python_shellouts": cmake,
        "packaging_python_requirements": packaging,
        "pybind_seams": pybind,
        "oracle_only_modules": oracle_only,
    }


# --- reporting ---------------------------------------------------------------

def write_markdown(report: dict, fh) -> None:
    s = report["summary"]
    fh.write("# Python Dependency Audit (native product must not need Python)\n\n")
    fh.write(f"- Repo root: `{report['repo_root']}`\n")
    fh.write(f"- Generated (UTC): {report['generated_at']}\n")
    fh.write(f"- Git available: {report['git_available']}\n\n")

    fh.write("## Summary\n\n")
    fh.write(f"- Tracked files: {s['tracked_file_count']}\n")
    fh.write(f"- CMake python references: {s['cmake_python_total']} total "
             f"(bad={s['cmake_python_bad']}, effective-bad="
             f"{s['cmake_python_bad_effective']}, vendored="
             f"{s['cmake_python_bad_vendored']}, comment-only="
             f"{s['cmake_python_comment_only']}, dev_tooling="
             f"{s['cmake_python_dev_tooling']})\n")
    fh.write(f"- Packaging python requirements: {s['packaging_python_requirements']} "
             f"by severity {s['packaging_python_by_severity']}\n")
    fh.write(f"- Python fallback seams: {s['python_fallback_seams']} "
             f"(pybind locations: {s['pybind_locations']})\n")
    fh.write(f"- Oracle-only modules: {s['oracle_only_modules']}\n\n")

    fh.write("## 1. CMake that shells out to Python\n\n")
    fh.write("Only **effective** (non-comment, non-disable) references are listed "
             "below; comment-only references are counted in the summary. "
             "`effective` rows are what `--fail-on native_test_depends_on_python` "
             "gates on.\n\n")
    eff = [c for c in report["cmake_python_shellouts"] if c["effective"]]
    if eff:
        fh.write("| path | line | kind | class | vendored | text |\n")
        fh.write("|---|---|---|---|---|---|\n")
        for c in eff:
            txt = c["text"].replace("|", "\\|")
            if len(txt) > 80:
                txt = txt[:80] + "…"
            fh.write(f"| `{c['path']}` | {c['line']} | {c['kind']} | "
                     f"{c['classification']} | {c['vendored']} | {txt} |\n")
    else:
        fh.write("_No effective CMake python dependencies._\n")
    fh.write("\n")

    fh.write("## 2. Packaging that hard-requires Python\n\n")
    by_sev: dict[str, list[dict]] = {}
    for p in report["packaging_python_requirements"]:
        by_sev.setdefault(p["severity"], []).append(p)
    if by_sev:
        for sev in sorted(by_sev):
            items = by_sev[sev]
            fh.write(f"### {sev} ({len(items)})\n\n")
            if sev == "product_hard_requirement":
                for p in items:
                    fh.write(f"- `{p['path']}:{p['line']}` {p['note']}: "
                             f"`{p['text']}`\n")
            else:
                # summarize: distinct files + one example
                files = sorted({p["path"] for p in items})
                fh.write(f"- distinct files: {len(files)} — "
                         + ", ".join(f"`{f}`" for f in files[:12])
                         + (" …" if len(files) > 12 else "") + "\n")
                ex = items[0]
                fh.write(f"- example: `{ex['path']}:{ex['line']}` `{ex['text'][:70]}`\n")
            fh.write("\n")
    else:
        fh.write("_None._\n")
    fh.write("\n")

    fh.write("## 3. pybind11 / native fallback seams\n\n")
    ps = report["pybind_seams"]
    fh.write(f"- pybind11 vendored: {ps['pybind11_vendored']}\n")
    fh.write(f"- binding locations: " +
             (", ".join(f"`{p}`" for p in ps["pybind_location"])
              if ps["pybind_location"] else "_none_") + "\n")
    if ps["fallback_seams"]:
        for seam in ps["fallback_seams"]:
            fh.write(f"- `{seam['path']}`: native_module="
                     f"`{seam['native_module']}`, try/except lines="
                     f"{seam['try_except_lines']}, has_cpp_dispatch="
                     f"{seam['has_cpp_dispatch']}\n")
            for ev in seam["evidence"][:6]:
                fh.write(f"    - `{ev}`\n")
            fh.write(f"  - RULE: {seam['rule']}\n")
    else:
        fh.write("_No native_bind.py fallback seams found._\n")
    fh.write("\n")

    fh.write("## 4. Modules imported ONLY by oracle tooling\n\n")
    if report["oracle_only_modules"]:
        for m in report["oracle_only_modules"]:
            fh.write(f"- `{m['module']}` imported by: "
                     + ", ".join(f"`{f}`" for f in m["imported_by"]) + "\n")
    else:
        fh.write("_None — every paleo_workbench module imported by oracle tooling is "
                 "also imported by the production package._\n")
    fh.write("\n")


# --- CLI ---------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Audit that no Python runtime sneaks into the native product.")
    ap.add_argument("--repo-root", required=True, help="repository root to scan")
    ap.add_argument("--json-out", help="path to write machine-readable JSON")
    ap.add_argument("--markdown-out", help="path to write Markdown report")
    ap.add_argument("--quiet", action="store_true", help="suppress stdout summary")
    ap.add_argument("--fail-on", default="",
                    help="comma/space-separated categories that must exit non-zero "
                         "if any EFFECTIVE finding exists (e.g. "
                         "'native_test_depends_on_python,python_fallback_seam')")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.repo_root):
        sys.stderr.write(f"error: --repo-root is not a directory: {args.repo_root}\n")
        return 2

    report = run_scan(args.repo_root)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(report, fh, indent=2, sort_keys=True, ensure_ascii=False)
            fh.write("\n")
    if args.markdown_out:
        with open(args.markdown_out, "w", encoding="utf-8", newline="\n") as fh:
            write_markdown(report, fh)

    # --- CI gate ---
    gate_cats = [c.strip() for c in re.split(r"[,\s]+", args.fail_on) if c.strip()]
    # An unrecognised category would otherwise silently never fire, which is the
    # worst possible failure mode for a gate.
    unknown = [c for c in gate_cats if c not in FAIL_ON_CATEGORIES]
    if unknown:
        sys.stderr.write(
            "error: unknown --fail-on categor(y|ies): " + ", ".join(unknown)
            + "\n       known categories: " + ", ".join(sorted(FAIL_ON_CATEGORIES))
            + "\n")
        return EXIT_USAGE
    exit_code = 0
    if gate_cats:
        s = report["summary"]
        triggered: list[str] = []
        if "native_test_depends_on_python" in gate_cats and s["cmake_python_bad_effective"]:
            triggered.append("native_test_depends_on_python")
        if "packaging_python_requirement" in gate_cats and s["packaging_python_requirements"]:
            triggered.append("packaging_python_requirement")
        if "python_fallback_seam" in gate_cats and s["python_fallback_seams"]:
            triggered.append("python_fallback_seam")
        if "oracle_only_module" in gate_cats and s["oracle_only_modules"]:
            triggered.append("oracle_only_module")
        if triggered:
            exit_code = 1
            sys.stderr.write("fail-on triggered: " + ", ".join(triggered) + "\n")

    if not args.quiet:
        s = report["summary"]
        print(f"[pwb_python_dependency_audit] cmake_bad={s['cmake_python_bad']} "
              f"(effective={s['cmake_python_bad_effective']}, "
              f"vendored={s['cmake_python_bad_vendored']}) dev_tooling="
              f"{s['cmake_python_dev_tooling']} packaging="
              f"{s['packaging_python_requirements']} fallback_seams="
              f"{s['python_fallback_seams']} oracle_only="
              f"{s['oracle_only_modules']}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
