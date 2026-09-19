#!/usr/bin/env python3
"""Global closure matrix for the cpp-close wave (line 12 owned).

Aggregates the per-line capability declarations of the C++ closure wave
into one implemented / merged / wired / verified matrix, derived from
repository facts — never hand maintained:

* Per-line capability files -> ``docs/development/cpp-closure-wave/
  <line-dir>/capability-matrix.json`` (schema below). A line directory
  without the file is reported as *not registered* — absence stays
  visible instead of silently dropping out of the matrix.
* Wave scope -> the line directory names under
  ``docs/development/cpp-closure-wave/``.
* Optional coordination facts -> ``.git/codex-coordination/cpp-close-wave/
  *.json`` (branch / PR / heartbeat), included when the directory exists.

capability-matrix.json schema::

    {
      "line": "01",
      "title": "...",
      "capabilities": [
        {
          "capability": "工程生命周期生产服务绑定",
          "python_source": "paleo_workbench/...",
          "cpp_target": "libs/closure_catalog",
          "implemented": true,
          "merged": false,           # merged into main
          "wired": false,            # wired into the product entry points
          "verified": false,         # verification evidence exists
          "evidence": ["libs/...", "tests/..."]   # free-form pointers
        }
      ]
    }

Usage::

    python tools/migration/pwb_closure_matrix.py --repo-root . \
        --markdown-out docs/development/cpp-closure-wave/closure-matrix.md \
        [--json-out build/closure-matrix.json] [--check]

Exit codes: 0 = written (or --check matches), 1 = --check mismatch,
2 = repository facts missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

COLUMNS = ("implemented", "merged", "wired", "verified")

# Directory-name prefix of a wave line dir (12-product-integration -> "12").
LINE_PREFIXES = (
    "01", "02", "03", "04", "05", "06", "07", "08",
    "09", "10", "11", "12", "13", "14",
)


@dataclass
class Capability:
    line: str
    line_dir: str
    title: str
    name: str
    python_source: str
    cpp_target: str
    flags: Dict[str, bool] = field(default_factory=dict)
    evidence: List[str] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)


def load_capability_file(line_dir: Path) -> Optional[dict]:
    path = line_dir / "capability-matrix.json"
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_line_dir(line_dir: Path) -> List[Capability]:
    data = load_capability_file(line_dir)
    line_id = line_dir.name.split("-", 1)[0]
    if data is None:
        return [Capability(
            line=line_id, line_dir=line_dir.name,
            title="(capability-matrix.json 未登记)", name="(未登记)",
            python_source="", cpp_target="", flags={c: False for c in COLUMNS},
            evidence=[], problems=["capability-matrix.json missing"],
        )]
    problems: List[str] = []
    capabilities: List[Capability] = []
    raw_caps = data.get("capabilities")
    if not raw_caps:
        problems.append("capability-matrix.json: empty 'capabilities' — "
                        "register at least one capability or explain the "
                        "gap in the line ledger")
        return [Capability(
            line=str(data.get("line") or line_id),
            line_dir=line_dir.name,
            title=str(data.get("title") or ""),
            name="(空登记)", python_source="", cpp_target="",
            flags={c: False for c in COLUMNS}, evidence=[],
            problems=problems,
        )]
    for index, raw in enumerate(raw_caps):
        flags = {c: bool(raw.get(c, False)) for c in COLUMNS}
        cap_problems: List[str] = []
        if not raw.get("capability"):
            cap_problems.append(f"capabilities[{index}]: missing 'capability'")
        if not any(flags.values()):
            # All-false is a deliberate "registered gap" only when a note
            # explains the owning dependency; otherwise it is an accidental
            # empty row.
            if not (raw.get("note") or "").strip():
                cap_problems.append(
                    f"capabilities[{index}] '{raw.get('capability')}': "
                    "all four columns false — state the real stage, "
                    "add a dependency note, or drop it")
        # monotonic gates: wired implies implemented; verified implies
        # wired (+evidence). merge 状态由 PR/协调登记独立跟踪，不阻塞 wired。
        if flags["wired"] and not flags["implemented"]:
            cap_problems.append(
                f"capabilities[{index}]: wired requires implemented")
        if flags["verified"] and not flags["wired"]:
            cap_problems.append(
                f"capabilities[{index}]: verified requires wired")
        if flags["verified"] and not raw.get("evidence"):
            cap_problems.append(
                f"capabilities[{index}]: verified requires evidence")
        problems.extend(cap_problems)
        capabilities.append(Capability(
            line=str(data.get("line") or line_id),
            line_dir=line_dir.name,
            title=str(data.get("title") or ""),
            name=str(raw.get("capability") or ""),
            python_source=str(raw.get("python_source") or ""),
            cpp_target=str(raw.get("cpp_target") or ""),
            flags=flags,
            evidence=[str(e) for e in (raw.get("evidence") or [])],
            problems=cap_problems,
        ))
    return capabilities


def collect_wave_lines(wave_root: Path) -> List[Path]:
    if not wave_root.is_dir():
        return []
    dirs = [d for d in sorted(wave_root.iterdir())
            if d.is_dir() and d.name[:2] in LINE_PREFIXES]
    return dirs


def collect_coordination(coord_dir: Path) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    if not coord_dir.is_dir():
        return out
    for path in sorted(coord_dir.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            line_id = str(data.get("line") or path.stem.split("-")[0])
            out[line_id] = data
        except (OSError, ValueError):
            out[path.stem] = {"error": "unparsable coordination file"}
    return out


def render_markdown(lines: List[List[Capability]],
                    coordination: Dict[str, dict]) -> str:
    out: List[str] = []
    out.append("# C++ closure wave — 全局迁移矩阵（generated）")
    out.append("")
    out.append("Generated by `tools/migration/pwb_closure_matrix.py` from "
               "`docs/development/cpp-closure-wave/*/capability-matrix.json`. "
               "Do not hand-edit; re-run the generator.")
    out.append("")
    out.append("列含义：implemented=代码存在；merged=已入 main；"
               "wired=产品入口真实接线；verified=有验证证据。"
               "局部绿灯相加不等于全量通过。")
    out.append("")
    out.append("| 线 | 能力 | Python 源 | C++ 落点 | impl | merged | wired |"
               " verified | 证据 |")
    out.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for capabilities in lines:
        for cap in capabilities:
            def mark(flag: bool) -> str:
                return "✅" if flag else "—"
            out.append(
                "| {line} | {name} | {py} | {cpp} | {i} | {m} | {w} | {v} "
                "| {ev} |".format(
                    line=cap.line, name=cap.name or "(未登记)",
                    py=cap.python_source.replace("|", "\\|"),
                    cpp=cap.cpp_target.replace("|", "\\|"),
                    i=mark(cap.flags.get("implemented", False)),
                    m=mark(cap.flags.get("merged", False)),
                    w=mark(cap.flags.get("wired", False)),
                    v=mark(cap.flags.get("verified", False)),
                    ev="<br>".join(
                        e.replace("|", "\\|") for e in cap.evidence) or "—"))
    out.append("")

    problems = [(cap.line_dir, p) for caps in lines for cap in caps
                for p in cap.problems]
    if problems:
        out.append("## 结构问题（必须修复）")
        out.append("")
        for line_dir, problem in problems:
            out.append(f"- `{line_dir}`: {problem}")
        out.append("")

    unregistered = [caps[0].line_dir for caps in lines
                    if caps and caps[0].name == "(未登记)"]
    if unregistered:
        out.append("## 未登记线（矩阵缺口，如实呈现）")
        out.append("")
        for line_dir in unregistered:
            out.append(f"- `{line_dir}`")
        out.append("")

    if coordination:
        out.append("## 协调登记（branch / PR，来自 coordination 目录）")
        out.append("")
        out.append("| 线 | branch | PR | head | status |")
        out.append("| --- | --- | --- | --- | --- |")
        for line_id in sorted(coordination):
            data = coordination[line_id]
            out.append("| {line} | {branch} | {pr} | {head} | {status} |"
                       .format(line=line_id,
                               branch=str(data.get("branch", "—")),
                               pr=str(data.get("pr_url") or "—"),
                               head=str(data.get("head_sha", "—"))[:12],
                               status=str(data.get("status", "—"))))
        out.append("")
    return "\n".join(out) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--markdown-out",
                        default="docs/development/cpp-closure-wave/"
                                "closure-matrix.md")
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--check", action="store_true",
                        help="verify the generated file is current; "
                             "exit 1 on drift")
    args = parser.parse_args(argv)

    repo = Path(args.repo_root).resolve()
    wave_root = repo / "docs" / "development" / "cpp-closure-wave"
    if not wave_root.is_dir():
        print(f"closure-wave docs missing: {wave_root}", file=sys.stderr)
        return 2

    lines = [parse_line_dir(d) for d in collect_wave_lines(wave_root)]
    coordination = collect_coordination(
        repo / ".git" / "codex-coordination" / "cpp-close-wave")
    markdown = render_markdown(lines, coordination)

    structured = {
        "lines": [
            {
                "line": caps[0].line if caps else "",
                "dir": caps[0].line_dir if caps else "",
                "title": caps[0].title if caps else "",
                "capabilities": [
                    {
                        "capability": cap.name,
                        "python_source": cap.python_source,
                        "cpp_target": cap.cpp_target,
                        **cap.flags,
                        "evidence": cap.evidence,
                        "problems": cap.problems,
                    } for cap in caps
                ],
            } for caps in lines
        ],
        "coordination": coordination,
    }
    payload = json.dumps(structured, ensure_ascii=False, indent=2,
                         sort_keys=True) + "\n"

    markdown_path = repo / args.markdown_out
    if args.check:
        current = (markdown_path.read_text(encoding="utf-8")
                   if markdown_path.is_file() else "")
        if current != markdown:
            print(f"closure matrix drifted: {markdown_path}",
                  file=sys.stderr)
            return 1
        return 0
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown, encoding="utf-8")
    if args.json_out:
        json_path = Path(args.json_out)
        if not json_path.is_absolute():
            json_path = repo / json_path
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(payload, encoding="utf-8")
    print(f"closure matrix written: {markdown_path} "
          f"({sum(len(caps) for caps in lines)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
