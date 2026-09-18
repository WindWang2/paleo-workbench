#!/usr/bin/env python3
"""pwb_artifact_hygiene.py — build artifact hygiene scanner for paleo-workbench.

This is a static, evidence-based audit tool. Every finding it reports is derived
from facts it can re-derive deterministically from the repository:

  * which files git actually tracks   (``git ls-files``; falls back to a full
    working-tree walk when git is unavailable, in which case the reported set is
    "everything on disk" and ``git_available`` is false),
  * the on-disk byte size of each tracked file,
  * the SHA-256 of fixture file contents (for duplicate detection),
  * the contents of ``.gitignore`` (parsed to decide coverage),
  * the count of translation units under each ``libs/<lib>/src`` directory.

What it is NOT: it does not build anything, does not run the compiler, and does
not guess whether an artifact is "stale". It only reports what is *tracked* and
*large* or *duplicated* or *generated into a source dir*, then proposes the
concrete ``.gitignore`` edits and PCH/unity measurement that follow from those
facts. PCH / unity / compiler-cache are explicitly NOT recommended for enabling;
the tool only lists libraries big enough to be *candidates that need measuring*.

Pure Python 3 standard library. Runs on Windows and Linux. Deterministic, sorted
output. Exit code 0 on success, 2 when ``--repo-root`` is not a directory.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

MiB = 1 << 20

# --- artifact categories -----------------------------------------------------

OBJECT_EXTS = (".obj", ".o")
LIB_EXTS = (".lib", ".a", ".so", ".dylib", ".pyd", ".dll")
MSVC_EXTS = (".pdb", ".ilk", ".exp", ".tlog", ".idb")
CMAKE_BASENAME_RESIDUE = {
    "CMakeCache.txt",
    "cmake_install.cmake",
    "compile_commands.json",
}
CMAKE_DIR_RESIDUE = ("CMakeFiles/", "build/")
CMAKE_FILE_RESIDUE = (".ninja", ".ninja_deps", ".ninja_log")

# translation-unit extensions used by the PCH/unity candidate count
TU_EXTS = (".cpp", ".cc", ".cxx", ".c")


@dataclass
class Finding:
    path: str
    size_bytes: int
    category: str
    reason: str
    gitignore_covered: Optional[bool] = None


# --- gitignore parsing -------------------------------------------------------

def parse_gitignore(repo_root: str) -> list[tuple[bool, str]]:
    """Return a list of (negated, raw_pattern) tuples, root-relative.

    Comments and blank lines are dropped. A leading ``!`` marks a negation.
    """
    gi_path = os.path.join(repo_root, ".gitignore")
    out: list[tuple[bool, str]] = []
    if not os.path.isfile(gi_path):
        return out
    with open(gi_path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            negated = stripped.startswith("!")
            pat = stripped.lstrip("!").strip()
            out.append((negated, pat))
    return out


def _matches_pattern(rel_path: str, pat: str) -> bool:
    rel = rel_path.replace(os.sep, "/")
    # Directory pattern (trailing slash): matches a path segment / prefix.
    if pat.endswith("/"):
        p = pat.rstrip("/")
        if "/" in p:
            return fnmatch.fnmatch(rel, p + "/*") or fnmatch.fnmatch(rel, p + "*/**")
        return rel == p or rel.startswith(p + "/")
    # Anchored at repo root.
    if pat.startswith("/"):
        sub = pat[1:]
        return fnmatch.fnmatch(rel, sub) or fnmatch.fnmatch(rel, sub + "/*")
    # Contains a slash somewhere in the middle -> full-path match.
    if "/" in pat:
        return fnmatch.fnmatch(rel, pat)
    # Otherwise match against the basename anywhere.
    return fnmatch.fnmatch(os.path.basename(rel), pat)


def is_ignored(rel_path: str, patterns: list[tuple[bool, str]]) -> bool:
    ignored = False
    for negated, pat in patterns:
        if _matches_pattern(rel_path, pat):
            ignored = not negated
    return ignored


# --- tracked file enumeration ------------------------------------------------

def git_ls_files(repo_root: str) -> tuple[list[str], bool]:
    """Return (tracked_relative_paths, git_available)."""
    try:
        proc = subprocess.run(
            ["git", "ls-files"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, "git ls-files")
        files = [ln for ln in proc.stdout.splitlines() if ln]
        return files, True
    except (OSError, subprocess.CalledProcessError):
        # Fallback: full working-tree walk (no .git or git unusable).
        files: list[str] = []
        for dirpath, _dirnames, names in os.walk(repo_root):
            for name in names:
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, repo_root).replace(os.sep, "/")
                if ".git/" in rel or rel.startswith(".git/"):
                    continue
                files.append(rel)
        return files, False


def file_size(repo_root: str, rel: str) -> int:
    try:
        return os.path.getsize(os.path.join(repo_root, rel))
    except OSError:
        return 0


# --- classification helpers --------------------------------------------------

def classify_build_output(rel: str) -> Optional[str]:
    low = rel.lower()
    base = os.path.basename(rel)
    if low.endswith(OBJECT_EXTS):
        return "object_file"
    if low.endswith(LIB_EXTS):
        return "library"
    if base in CMAKE_BASENAME_RESIDUE:
        return "cmake_residue"
    # directory-residue patterns (CMakeFiles/, build/)
    parts = rel.split("/")
    for d in CMAKE_DIR_RESIDUE:
        dname = d.rstrip("/")
        if dname in parts or rel.startswith(d):
            return "cmake_residue"
    if low.endswith(CMAKE_FILE_RESIDUE):
        return "cmake_residue"
    if low.endswith(MSVC_EXTS):
        return "msvc_residue"
    return None


def is_fixture(rel: str) -> bool:
    parts = rel.split("/")
    # libs/**/fixtures/...  and  tests/cpp/**/fixtures/...
    if "fixtures" in parts:
        idx = parts.index("fixtures")
        if idx >= 1 and parts[0] == "libs":
            return True
        if idx >= 2 and parts[0] == "tests" and parts[1] == "cpp":
            return True
    return False


def is_oracle_fixture(rel: str) -> bool:
    """A generated oracle fixture: a golden `*_oracle.json`, or anything under a
    library's `oracle/fixtures/` directory. These are the dedup candidates;
    broad test-data payloads (e.g. corrupt_db copies) are intentionally
    duplicated and are excluded from the dedup scan."""
    return rel.endswith("_oracle.json") or "/oracle/fixtures/" in rel


# --- the six checks ----------------------------------------------------------

def check_tracked_build_outputs(tracked: list[str], repo_root: str,
                                patterns: list[tuple[bool, str]]) -> list[Finding]:
    out: list[Finding] = []
    for rel in tracked:
        cat = classify_build_output(rel)
        if cat is None:
            continue
        size = file_size(repo_root, rel)
        covered = is_ignored(rel, patterns)
        reason = {
            "object_file": "compiler/linker object output tracked in git",
            "library": "static/shared library output tracked in git",
            "cmake_residue": "CMake/Ninja build residue tracked in git",
            "msvc_residue": "MSVC incremental-build residue tracked in git",
        }[cat]
        out.append(Finding(rel, size, cat, reason, gitignore_covered=covered))
    out.sort(key=lambda f: (f.category, f.path))
    return out


def check_giant_files(tracked: list[str], repo_root: str,
                      large_bytes: int, top_n: int) -> list[dict]:
    rows: list[tuple[int, str]] = []
    for rel in tracked:
        size = file_size(repo_root, rel)
        if size > large_bytes:
            rows.append((size, rel))
    rows.sort(reverse=True)
    out: list[dict] = []
    for size, rel in rows[:top_n]:
        out.append({
            "path": rel,
            "size_bytes": size,
            "is_fixture": is_fixture(rel),
        })
    return out


def check_duplicate_fixtures(tracked: list[str], repo_root: str) -> tuple[list[dict], list[dict]]:
    fixture_paths = [rel for rel in tracked if is_oracle_fixture(rel)]
    # group by content sha256
    by_hash: dict[str, list[str]] = {}
    size_of: dict[str, int] = {}
    for rel in fixture_paths:
        full = os.path.join(repo_root, rel)
        try:
            h = hashlib.sha256()
            with open(full, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            digest = h.hexdigest()
        except OSError:
            continue
        by_hash.setdefault(digest, []).append(rel)
        size_of.setdefault(digest, file_size(repo_root, rel))
    duplicates = [
        {"sha256": d, "size_bytes": size_of[d], "paths": sorted(v)}
        for d, v in by_hash.items() if len(v) > 1
    ]
    duplicates.sort(key=lambda g: (-len(g["paths"]), g["sha256"]))

    # near-duplicate names in different dirs
    by_name: dict[str, list[str]] = {}
    for rel in fixture_paths:
        by_name.setdefault(os.path.basename(rel), []).append(rel)
    near: list[dict] = []
    for name, paths in by_name.items():
        dirs = sorted({os.path.dirname(p) for p in paths})
        if len(dirs) > 1:
            near.append({"name": name, "dirs": dirs, "paths": sorted(paths)})
    near.sort(key=lambda g: (g["name"]))
    return duplicates, near


def check_incremental_rebuild_risks(tracked: list[str], repo_root: str,
                                    oracle_scripts: list[str]) -> list[dict]:
    """Find generated *.inc/*.hpp under libs/*/src that are tracked AND produced
    by a tools/oracle generator. Report the generator->generated pairing."""
    generated_exts = (".inc", ".hpp")
    out: list[dict] = []
    for rel in tracked:
        low = rel.lower()
        if not low.endswith(generated_exts):
            continue
        parts = rel.split("/")
        # libs/<lib>/src/... generated header
        if len(parts) >= 3 and parts[0] == "libs" and parts[2] == "src":
            base = os.path.basename(rel)
            generators = []
            for script in oracle_scripts:
                try:
                    txt = open(os.path.join(repo_root, script),
                               encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                if base in txt or rel in txt or ("/" + base) in txt:
                    generators.append(script)
            if not generators:
                # No oracle generator produces this header: it is a normal
                # hand-written source header, not an incremental-rebuild risk.
                continue
            out.append({
                "generated_file": rel,
                "tracked": True,
                "generators": sorted(generators),
                "note": (
                    "tracked generated header under libs/*/src; must be "
                    "regenerated by the oracle generator, not hand-edited"
                ),
            })
    out.sort(key=lambda d: d["generated_file"])
    return out


def check_pch_unity(tracked: list[str], repo_root: str, tu_threshold: int) -> dict:
    """Count translation units per library; flag libraries >= threshold as
    candidates that need measurement (NOT enabled)."""
    tu_count: dict[str, int] = {}
    for rel in tracked:
        parts = rel.split("/")
        if len(parts) >= 3 and parts[0] == "libs" and parts[2] == "src":
            if rel.lower().endswith(TU_EXTS):
                lib = parts[1]
                tu_count[lib] = tu_count.get(lib, 0) + 1
    libs = [
        {"name": lib, "tu_count": n, "candidate": n >= tu_threshold}
        for lib, n in tu_count.items()
    ]
    libs.sort(key=lambda d: (-d["tu_count"], d["name"]))
    candidates = [d["name"] for d in libs if d["candidate"]]
    return {
        "enabled": False,
        "tu_threshold": tu_threshold,
        "total_translation_units": sum(tu_count.values()),
        "libraries": libs,
        "candidate_libraries": candidates,
        "note": (
            "PCH / unity builds / compiler caches are NOT enabled. The "
            "libraries below exceed the translation-unit threshold and are "
            "only candidates for a future, measured opt-in. Do not enable "
            "without a before/after wall-clock measurement on CI."
        ),
    }


def gitignore_coverage(findings: list[Finding],
                       patterns: list[tuple[bool, str]]) -> dict:
    """Per category: is the artifact type already covered by .gitignore, and
    what concrete patterns are still needed?"""
    cats = sorted({f.category for f in findings})
    coverage: dict[str, dict] = {}
    needed: list[str] = []
    for cat in cats:
        cat_findings = [f for f in findings if f.category == cat]
        covered_all = all(f.gitignore_covered for f in cat_findings)
        any_covered = any(f.gitignore_covered for f in cat_findings)
        # Build suggested patterns for findings that are NOT ignored.
        sugg: list[str] = []
        for f in cat_findings:
            if not f.gitignore_covered:
                ext = os.path.splitext(f.path)[1].lower()
                if ext and ext not in sugg:
                    sugg.append("*" + ext)
        sugg = sorted(set(sugg))
        if sugg and sugg not in needed:
            needed.extend(sugg)
        coverage[cat] = {
            "present_in_gitignore": any_covered,
            "all_findings_covered": covered_all,
            "tracked_count": len(cat_findings),
            "suggested_patterns": sugg,
            "action": (
                "tracked-but-ignored: force-added; run `git rm --cached <path>` "
                "to stop tracking" if covered_all and cat_findings
                else ("add the suggested patterns to .gitignore" if sugg else "none")
            ),
        }
    return {"per_category": coverage, "suggested_additions": sorted(set(needed))}


# --- driver ------------------------------------------------------------------

def run_scan(repo_root: str, large_bytes: int, top_n: int,
             tu_threshold: int) -> dict:
    tracked, git_available = git_ls_files(repo_root)
    patterns = parse_gitignore(repo_root)
    oracle_scripts = sorted(
        f for f in tracked if f.startswith("tools/oracle/") and f.endswith(".py")
    )

    build_outputs = check_tracked_build_outputs(tracked, repo_root, patterns)
    giant = check_giant_files(tracked, repo_root, large_bytes, top_n)
    dupes, near = check_duplicate_fixtures(tracked, repo_root)
    risks = check_incremental_rebuild_risks(tracked, repo_root, oracle_scripts)
    pch = check_pch_unity(tracked, repo_root, tu_threshold)
    coverage = gitignore_coverage(build_outputs, patterns)

    summary = {
        "git_available": git_available,
        "tracked_file_count": len(tracked),
        "tracked_build_outputs": len(build_outputs),
        "tracked_build_outputs_by_category": _count_by(build_outputs),
        "giant_tracked_files": len(giant),
        "giant_fixtures": sum(1 for g in giant if g["is_fixture"]),
        "duplicate_fixture_groups": len(dupes),
        "near_duplicate_fixture_names": len(near),
        "incremental_rebuild_risks": len(risks),
        "pch_candidate_libraries": len(pch["candidate_libraries"]),
    }

    return {
        "tool": "pwb_artifact_hygiene",
        "repo_root": os.path.abspath(repo_root),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_available": git_available,
        "summary": summary,
        "tracked_build_outputs": [_as_dict(f) for f in build_outputs],
        "giant_tracked_files": giant,
        "duplicate_fixtures": dupes,
        "near_duplicate_fixture_names": near,
        "incremental_rebuild_risks": risks,
        "gitignore_coverage": coverage,
        "pch_unity_recommendation": pch,
    }


def _count_by(findings: list[Finding]) -> dict:
    out: dict[str, int] = {}
    for f in findings:
        out[f.category] = out.get(f.category, 0) + 1
    return dict(sorted(out.items()))


def _as_dict(f: Finding) -> dict:
    return {
        "path": f.path,
        "size_bytes": f.size_bytes,
        "category": f.category,
        "reason": f.reason,
        "gitignore_covered": f.gitignore_covered,
    }


# --- reporting ---------------------------------------------------------------

def human(n: int) -> str:
    if n >= MiB:
        return f"{n / MiB:.2f} MiB"
    if n >= 1024:
        return f"{n / 1024:.1f} KiB"
    return f"{n} B"


def write_markdown(report: dict, fh) -> None:
    s = report["summary"]
    fh.write("# Build Artifact Hygiene Report\n\n")
    fh.write(f"- Repo root: `{report['repo_root']}`\n")
    fh.write(f"- Generated (UTC): {report['generated_at']}\n")
    fh.write(f"- Git available: {report['git_available']}\n")
    fh.write(f"- Tracked files scanned: {s['tracked_file_count']}\n\n")

    fh.write("## Summary\n\n")
    fh.write(f"- Tracked build outputs: **{s['tracked_build_outputs']}** "
             f"({s['tracked_build_outputs_by_category']})\n")
    fh.write(f"- Giant tracked files (> threshold): **{s['giant_tracked_files']}** "
             f"({s['giant_fixtures']} are fixtures)\n")
    fh.write(f"- Duplicate fixture groups (by SHA-256): **{s['duplicate_fixture_groups']}**\n")
    fh.write(f"- Near-duplicate fixture names (different dirs): "
             f"**{s['near_duplicate_fixture_names']}**\n")
    fh.write(f"- Incremental rebuild risks: **{s['incremental_rebuild_risks']}**\n")
    fh.write(f"- PCH/unity candidate libraries (>= threshold): "
             f"**{s['pch_candidate_libraries']}**\n\n")

    fh.write("## 1. Tracked build outputs\n\n")
    if report["tracked_build_outputs"]:
        fh.write("| path | size | category | .gitignore |\n")
        fh.write("|---|---|---|---|\n")
        for f in report["tracked_build_outputs"]:
            cov = "covered" if f["gitignore_covered"] else "NOT covered"
            fh.write(f"| `{f['path']}` | {human(f['size_bytes'])} | "
                     f"{f['category']} | {cov} |\n")
    else:
        fh.write("_None._\n")
    fh.write("\n")

    fh.write("## 2. Giant tracked files\n\n")
    if report["giant_tracked_files"]:
        fh.write("| path | size | fixture |\n")
        fh.write("|---|---|---|\n")
        for g in report["giant_tracked_files"]:
            flag = "FIXTURE" if g["is_fixture"] else ""
            fh.write(f"| `{g['path']}` | {human(g['size_bytes'])} | {flag} |\n")
    else:
        fh.write("_None above threshold._\n")
    fh.write("\n")

    fh.write("## 3. Duplicate / near-duplicate oracle fixtures\n\n")
    if report["duplicate_fixtures"]:
        fh.write("### 3a. Exact duplicates (same SHA-256)\n\n")
        for g in report["duplicate_fixtures"]:
            fh.write(f"- `{g['sha256'][:12]}…` ({human(g['size_bytes'])}): "
                     + ", ".join(f"`{p}`" for p in g["paths"]) + "\n")
    else:
        fh.write("_No exact-duplicate fixture groups._\n")
    if report["near_duplicate_fixture_names"]:
        fh.write("\n### 3b. Near-duplicate names in different dirs\n\n")
        for g in report["near_duplicate_fixture_names"]:
            fh.write(f"- `{g['name']}` in: " + ", ".join(f"`{d}`" for d in g["dirs"]) + "\n")
    fh.write("\n")

    fh.write("## 4. Incremental rebuild invalidation risks\n\n")
    if report["incremental_rebuild_risks"]:
        for r in report["incremental_rebuild_risks"]:
            gens = ", ".join(r["generators"]) or "(none found)"
            fh.write(f"- `{r['generated_file']}` <- generator(s): {gens}\n"
                     f"  - {r['note']}\n")
    else:
        fh.write("_No tracked generated *.inc/*.hpp under libs/*/src detected._\n")
    fh.write("\n")

    fh.write("## 5. .gitignore coverage & suggested additions\n\n")
    cov = report["gitignore_coverage"]
    for cat, info in cov["per_category"].items():
        fh.write(f"- `{cat}`: tracked={info['tracked_count']}, "
                 f"present_in_gitignore={info['present_in_gitignore']}, "
                 f"action={info['action']}\n")
        if info["suggested_patterns"]:
            fh.write(f"  - add: " + ", ".join(info["suggested_patterns"]) + "\n")
    if cov["suggested_additions"]:
        fh.write("\nConcrete patterns to add:\n\n```gitignore\n")
        fh.write("\n".join(cov["suggested_additions"]) + "\n```\n")
    else:
        fh.write("\nNo additional .gitignore patterns needed for uncovered outputs.\n")
    fh.write("\n")

    fh.write("## 6. PCH / unity / compiler-cache recommendation\n\n")
    rec = report["pch_unity_recommendation"]
    fh.write(f"- Enabled: **{rec['enabled']}** (must stay false)\n")
    fh.write(f"- TU threshold: {rec['tu_threshold']}; total TUs: "
             f"{rec['total_translation_units']}\n")
    fh.write(f"- Candidate libraries: " +
             (", ".join(f"`{n}`" for n in rec["candidate_libraries"])
              if rec["candidate_libraries"] else "_none_") + "\n")
    if rec["libraries"]:
        fh.write("\n| library | TUs | candidate |\n|---|---|---|\n")
        for lib in rec["libraries"]:
            fh.write(f"| `{lib['name']}` | {lib['tu_count']} | "
                     f"{'yes' if lib['candidate'] else ''} |\n")
    fh.write("\n" + rec["note"] + "\n")


# --- CLI ---------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Static build-artifact hygiene scanner for paleo-workbench.")
    ap.add_argument("--repo-root", required=True, help="repository root to scan")
    ap.add_argument("--json-out", help="path to write machine-readable JSON")
    ap.add_argument("--markdown-out", help="path to write Markdown report")
    ap.add_argument("--quiet", action="store_true", help="suppress stdout summary")
    ap.add_argument("--large-bytes", type=int, default=MiB,
                    help="giant-file threshold in bytes (default 1 MiB)")
    ap.add_argument("--top-n", type=int, default=25,
                    help="max giant files to list (default 25)")
    ap.add_argument("--tu-threshold", type=int, default=20,
                    help="TUs per lib to flag as PCH/unity candidate (default 20)")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.repo_root):
        sys.stderr.write(f"error: --repo-root is not a directory: {args.repo_root}\n")
        return 2

    report = run_scan(args.repo_root, args.large_bytes, args.top_n, args.tu_threshold)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(report, fh, indent=2, sort_keys=True, ensure_ascii=False)
            fh.write("\n")
    if args.markdown_out:
        with open(args.markdown_out, "w", encoding="utf-8", newline="\n") as fh:
            write_markdown(report, fh)
    if not args.quiet:
        s = report["summary"]
        print(f"[pwb_artifact_hygiene] tracked={s['tracked_file_count']} "
              f"build_outputs={s['tracked_build_outputs']} "
              f"({s['tracked_build_outputs_by_category']}) "
              f"giant={s['giant_tracked_files']} "
              f"dupe_groups={s['duplicate_fixture_groups']} "
              f"rebuild_risks={s['incremental_rebuild_risks']} "
              f"pch_candidates={s['pch_candidate_libraries']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
