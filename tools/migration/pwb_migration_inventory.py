#!/usr/bin/env python3
"""C++ migration inventory for the Paleo Workbench Python -> C++ conversion.

The inventory is *derived from repository facts*, never hand maintained:

* C++ conversion units   -> ``libs/*`` directory trees (sources + public headers)
* Python origin surface  -> ``paleo_workbench/...`` references recorded in the
  C++ headers/sources and in the CMake ``# BEGIN CONV-xx`` blocks
* Gating switches        -> ``option(PWB_BUILD_*)`` declarations plus the
  ``if(...)`` nesting that guards each ``add_subdirectory()``
* Oracle coverage        -> ``tools/oracle/generate_*_fixtures.py`` generators and
  the frozen ``*_oracle.json`` fixtures they produce
* Application wiring     -> ``Pwb::<Alias>`` links and ``PWB_WITH_CONV_xx``
  compile definitions in ``apps/`` (conditional links are reported separately
  from unconditional ones)

It emits a machine-readable JSON document and a Markdown roll-up.

Usage::

    python tools/migration/pwb_migration_inventory.py --repo-root . \
        --json-out build/migration-inventory/migration_inventory.json \
        --markdown-out docs/development/cpp-migration-inventory.md

Exit codes: 0 = report written, 2 = repository facts missing (bad --repo-root).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

# Directories that never contain conversion facts (vendored sources, build trees).
PRUNE_DIRS: Set[str] = {
    ".git",
    ".venv",
    "build",
    "third_party",
    "node_modules",
    "__pycache__",
    "geo-viz-engine",
    ".workbuddy",
    ".scratch",
}

# `paleo_workbench/mapping/layers.py` style references in comments/docs.
RE_PY_PATH = re.compile(r"paleo_workbench[/\\][A-Za-z0-9_][A-Za-z0-9_./\\]*\.py")
# `paleo_workbench.workflow.crs_policy` style references in comments/docs.
RE_PY_MODULE = re.compile(r"paleo_workbench(?:\.[A-Za-z_][A-Za-z0-9_]*)+")
# option() may span several lines when the doc string is wrapped.
RE_OPTION = re.compile(
    r"option\(\s*([A-Z][A-Z0-9_]*)\s+(?:\"((?:[^\"\\]|\\.)*)\"|\[\[(.*?)\]\])",
    re.S,
)
RE_SUBDIR = re.compile(r"add_subdirectory\(\s*([^)\s]+)")
RE_IF = re.compile(r"^\s*if\((.*)\)\s*$")
RE_ENDIF = re.compile(r"^\s*endif\s*\(")
RE_ELSE = re.compile(r"^\s*(else|elseif)\s*\(")
RE_ADD_TEST = re.compile(r"add_test\(\s*NAME\s+([A-Za-z0-9_.+-]+)")
RE_BEGIN_SLICE = re.compile(r"#\s*BEGIN\s+(CONV-\d+)")
RE_LIB_TARGET = re.compile(r"add_library\(\s*([A-Za-z0-9_:]+)")
RE_PWB_LINK = re.compile(r"\b(Pwb::[A-Za-z0-9]+)")
RE_CONV_DEFINE = re.compile(r"\b(PWB_WITH_CONV_\d+)\b")

STATUS_LABELS: Dict[str, str] = {
    "native_complete_wired": "Native complete + wired",
    "native_core_not_wired": "Native core exists but not wired",
    "partial_native": "Partial native",
    "native_no_python_origin": "Native, no Python origin recorded",
    "python_only_production": "Python-only production",
    "oracle_test_only_python": "Oracle/test-only Python",
    "legacy_deprecated_candidate": "Legacy/deprecated candidate",
}


def repo_rel(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace("\\", "/")


def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def walk_files(root: str, subdir: str) -> Iterable[Tuple[str, List[str]]]:
    base = os.path.join(root, subdir) if subdir else root
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in PRUNE_DIRS)
        if set(os.path.relpath(dirpath, root).split(os.sep)) & PRUNE_DIRS:
            continue
        yield dirpath, filenames


def module_to_path(module: str) -> str:
    """`paleo_workbench.workflow.crs_policy` -> `paleo_workbench/workflow/crs_policy.py`."""
    return module.replace(".", "/") + ".py"


def normalise(ref: str) -> str:
    return ref.replace("\\", "/")


# --------------------------------------------------------------------------- #
# Repository facts
# --------------------------------------------------------------------------- #


@dataclass
class OptionFact:
    name: str
    doc: str
    declared_in: List[str] = field(default_factory=list)
    gates_subdirs: List[str] = field(default_factory=list)


def scan_options(root: str) -> Dict[str, OptionFact]:
    facts: Dict[str, OptionFact] = {}
    for dirpath, filenames in walk_files(root, ""):
        for fn in filenames:
            if fn != "CMakeLists.txt":
                continue
            path = os.path.join(dirpath, fn)
            rel = repo_rel(root, path)
            text = read_text(path)
            for m in RE_OPTION.finditer(text):
                name = m.group(1)
                doc = " ".join((m.group(2) or m.group(3) or "").split())
                line_no = text.count("\n", 0, m.start()) + 1
                fact = facts.setdefault(name, OptionFact(name=name, doc=doc))
                fact.declared_in.append(f"{rel}:{line_no}")
    return facts


def scan_root_gating(root: str) -> Dict[str, List[str]]:
    """Map ``libs/<x>`` -> the PWB_BUILD_* conditions guarding its add_subdirectory.

    A line-based ``if(...)`` stack is maintained so nested guards (and the
    ordering hazards they hide) are attributed correctly.
    """
    text = read_text(os.path.join(root, "CMakeLists.txt"))
    gating: Dict[str, List[str]] = {}
    stack: List[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if RE_ELSE.match(line):
            continue
        m_if = RE_IF.match(line)
        if m_if:
            stack.append(m_if.group(1))
            continue
        if RE_ENDIF.match(line):
            if stack:
                stack.pop()
            continue
        for sub in RE_SUBDIR.findall(stripped):
            guards = [
                token
                for cond in stack
                for token in re.findall(r"[A-Z][A-Z0-9_]*", cond)
                if token.startswith("PWB_")
            ]
            if guards:
                gating.setdefault(sub, sorted(set(guards)))
    return gating


def scan_python_origins(root: str, paths: Sequence[str]) -> List[str]:
    refs: Set[str] = set()
    for path in paths:
        text = read_text(path)
        for m in RE_PY_PATH.finditer(text):
            refs.add(normalise(m.group(0)))
        for m in RE_PY_MODULE.finditer(text):
            refs.add(normalise(module_to_path(m.group(0))))
    return sorted(refs)


def scan_slices(paths: Sequence[str]) -> List[str]:
    slices: Set[str] = set()
    for path in paths:
        for line in read_text(path).splitlines():
            m = RE_BEGIN_SLICE.search(line)
            if m:
                slices.add(m.group(1))
    return sorted(slices)


@dataclass
class UnitFact:
    unit: str
    root_dir: str
    target: Optional[str] = None
    alias: Optional[str] = None
    # Every Pwb:: alias declared in the unit's CMakeLists (#1448): the
    # single `alias` field kept only the LAST one, so a unit exporting
    # both Pwb::UiDataCore and Pwb::UiDataQt became matchable only by
    # the Qt alias — the product links the base alias, and the wiring
    # scan reported not_wired.
    aliases: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    headers: List[str] = field(default_factory=list)
    python_origins: List[str] = field(default_factory=list)
    python_origins_present: List[str] = field(default_factory=list)
    python_origins_absent: List[str] = field(default_factory=list)
    slices: List[str] = field(default_factory=list)
    options: List[str] = field(default_factory=list)
    tests: List[str] = field(default_factory=list)
    fixtures: List[str] = field(default_factory=list)
    oracle_generators: List[str] = field(default_factory=list)
    wired: bool = False
    wiring_mode: str = "not_wired"
    wiring_evidence: List[str] = field(default_factory=list)
    # Production TU include evidence (#1448): headers under this unit's
    # public namespace included by apps/** or another lib's src/include
    # (outside the unit itself and outside tests). A unit can be linked
    # into the closure yet have ZERO production consumers — the matrix
    # must not call that NATIVE_PRODUCT (retiring the Python side would
    # orphan the capability).
    production_includes: List[str] = field(default_factory=list)
    status: str = "partial_native"
    notes: List[str] = field(default_factory=list)


def scan_units(root: str) -> Dict[str, UnitFact]:
    libs_root = os.path.join(root, "libs")
    units: Dict[str, UnitFact] = {}
    if not os.path.isdir(libs_root):
        return units
    for entry in sorted(os.listdir(libs_root)):
        unit_dir = os.path.join(libs_root, entry)
        if not os.path.isdir(unit_dir) or entry in PRUNE_DIRS:
            continue
        sources: List[str] = []
        headers: List[str] = []
        cml_files: List[str] = []
        for dirpath, filenames in walk_files(libs_root, entry):
            for fn in filenames:
                path = os.path.join(dirpath, fn)
                rel = repo_rel(root, path)
                if fn.endswith((".cpp", ".cc", ".cxx")):
                    sources.append(rel)
                elif fn.endswith((".hpp", ".h", ".hxx")):
                    headers.append(rel)
                elif fn == "CMakeLists.txt":
                    cml_files.append(path)
        if not sources and not headers:
            continue
        fact = UnitFact(unit=entry, root_dir=repo_rel(root, unit_dir))
        fact.sources = sorted(sources)
        fact.headers = sorted(headers)

        for path in cml_files:
            text = read_text(path)
            for target in RE_LIB_TARGET.findall(text):
                if target.startswith("Pwb::"):
                    fact.alias = target
                    if target not in fact.aliases:
                        fact.aliases.append(target)
                elif fact.target is None:
                    fact.target = target
            fact.tests.extend(RE_ADD_TEST.findall(text))
        fact.tests = sorted(set(fact.tests))
        fact.slices = scan_slices(cml_files)
        fact.python_origins = scan_python_origins(root, fact.headers + fact.sources + cml_files)
        for ref in fact.python_origins:
            if os.path.exists(os.path.join(root, ref)):
                fact.python_origins_present.append(ref)
            else:
                fact.python_origins_absent.append(ref)
        units[entry] = fact
    return units


def scan_fixtures(root: str) -> Tuple[Dict[str, List[str]], List[str]]:
    """(unit -> fixtures under libs/, fixtures living under tests/)."""
    by_unit: Dict[str, List[str]] = {}
    tests_fixtures: List[str] = []
    for dirpath, filenames in walk_files(root, ""):
        rel_dir = repo_rel(root, dirpath)
        parts = rel_dir.split("/")
        if "fixtures" not in parts:
            continue
        for fn in filenames:
            if not fn.endswith(".json"):
                continue
            rel = repo_rel(root, os.path.join(dirpath, fn))
            m = re.match(r"libs/([^/]+)/", rel_dir)
            if m:
                by_unit.setdefault(m.group(1), []).append(rel)
            elif rel.startswith("tests/"):
                tests_fixtures.append(rel)
    return {k: sorted(v) for k, v in by_unit.items()}, sorted(tests_fixtures)


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def attribute_generators(
    root: str,
    units: Sequence[str],
    fixtures_by_unit: Dict[str, List[str]],
    tests_fixtures: Sequence[str],
    units_by_origin: Dict[str, List[str]],
) -> Tuple[Dict[str, List[str]], List[str], List[str]]:
    """(unit -> generators, tests-tier generators, generators with no C++ home).

    Attribution is evidence based, in this order:

    1. the frozen fixture the generator writes (``<topic>_oracle.json``) and the
       ``libs/<unit>`` that owns it;
    2. the Python modules the generator imports and the C++ unit that records
       them as its origin;
    3. ``libs/<unit>/`` paths mentioned in the generator's own text;
    4. a last-resort topic match between the file stem and the fixture name.

    Generators that only feed ``tests/``-tier fixtures are reported separately:
    they are real oracles, but they do not belong to a ``libs/`` unit.
    """
    oracle_dir = os.path.join(root, "tools", "oracle")
    by_unit: Dict[str, List[str]] = {}
    tests_tier: List[str] = []
    unattributed: List[str] = []
    if not os.path.isdir(oracle_dir):
        return by_unit, tests_tier, unattributed

    fixture_owner: Dict[str, str] = {}
    for unit, paths in fixtures_by_unit.items():
        for path in paths:
            fixture_owner[path] = unit
    all_fixtures = [(p, fixture_owner[p]) for p, o in fixture_owner.items()]
    all_fixtures += [(p, "tests") for p in tests_fixtures]
    # The generic CPP-B corpus generator feeds tests/cpp/data, not a libs unit.
    generic_corpus = {"generate_fixtures.py"}

    for fn in sorted(os.listdir(oracle_dir)):
        if not fn.endswith(".py"):
            continue
        rel = repo_rel(root, os.path.join(oracle_dir, fn))
        if not fn.startswith("generate_"):
            # Pure oracle tooling (dumps/read-back), not a fixture generator.
            continue
        text = read_text(os.path.join(oracle_dir, fn))
        stem = fn[len("generate_"):]
        for suffix in ("_fixtures.py", "_fixture.py", ".py"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        stem_key = _squash(stem)
        if fn in generic_corpus:
            tests_tier.append(rel)
            continue
        if not stem_key:
            unattributed.append(rel)
            continue

        # 1: fixture-name evidence (strongest — the fixture it actually writes).
        by_fixture: Set[str] = set()
        for path, owner in all_fixtures:
            key = _squash(path)
            if stem_key in key:
                by_fixture.add(owner)

        owners: Set[str] = set(by_fixture)
        if not owners:
            # 2: Python origins the generator drives.
            driven: Set[str] = set()
            for m in RE_PY_PATH.finditer(text):
                driven.add(normalise(m.group(0)))
            for m in RE_PY_MODULE.finditer(text):
                driven.add(normalise(module_to_path(m.group(0))))
            for ref in driven:
                owners.update(units_by_origin.get(ref, []))
            # 3: explicit libs/<unit>/ paths in the generator text.
            for m in re.finditer(r"libs/([A-Za-z0-9_]+)/", text):
                if m.group(1) in units:
                    owners.add(m.group(1))

        real_owners = sorted(o for o in owners if o in set(units))
        if real_owners:
            for owner in real_owners:
                by_unit.setdefault(owner, []).append(rel)
        elif "tests" in owners:
            tests_tier.append(rel)
        else:
            unattributed.append(rel)
    return {k: sorted(set(v)) for k, v in by_unit.items()}, sorted(set(tests_tier)), sorted(unattributed)


def scan_wiring(root: str) -> Dict[str, Tuple[str, List[str]]]:
    """alias -> (mode, evidence) where mode is 'always' or 'conditional'.

    A link found inside an ``if(PWB_BUILD_*)`` block is *conditional*: the unit
    only reaches the product binary when that switch is on, which is materially
    different from an unconditional link.
    """
    out: Dict[str, Tuple[str, List[str]]] = {}
    candidates: List[str] = []
    for dirpath, filenames in walk_files(root, "apps"):
        for fn in filenames:
            if fn == "CMakeLists.txt":
                candidates.append(os.path.join(dirpath, fn))
    root_cml = os.path.join(root, "CMakeLists.txt")
    if os.path.exists(root_cml):
        candidates.append(root_cml)
    # libs/*/CMakeLists.txt link edges (#1448): the product's link
    # closure is transitive — libs/ui_data_core PUBLIC-linking
    # Pwb::Interchange reaches pwb-platform without any direct edge.
    # These edges seed the transitive closure below; a link found only
    # here (never from apps/) is marked conditional.
    libs_edges: Dict[str, List[str]] = {}
    libs_root = os.path.join(root, "libs")
    if os.path.isdir(libs_root):
        for entry in sorted(os.listdir(libs_root)):
            unit_dir = os.path.join(libs_root, entry)
            if not os.path.isdir(unit_dir):
                continue
            for dirpath, _dirnames, filenames in os.walk(unit_dir):
                if "CMakeLists.txt" not in filenames:
                    continue
                path = os.path.join(dirpath, "CMakeLists.txt")
                rel = repo_rel(root, path)
                # which alias does THIS CMakeLists declare?
                text0 = read_text(path)
                declared = [
                    t for t in RE_LIB_TARGET.findall(text0)
                    if t.startswith("Pwb::")
                ]
                if not declared:
                    continue
                for line in text0.splitlines():
                    stripped = line.strip()
                    for alias in RE_PWB_LINK.findall(stripped):
                        for decl in declared:
                            libs_edges.setdefault(alias, []).append(
                                f"{rel}: {stripped} (via {decl})"
                            )
    for path in candidates:
        rel = repo_rel(root, path)
        stack: List[str] = []
        for line in read_text(path).splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if RE_ELSE.match(line):
                continue
            m_if = RE_IF.match(line)
            if m_if:
                stack.append(m_if.group(1))
                continue
            if RE_ENDIF.match(line):
                if stack:
                    stack.pop()
                continue
            conditional = any("PWB_BUILD" in cond or "PWB_WITH" in cond for cond in stack)
            for alias in RE_PWB_LINK.findall(stripped):
                mode = "conditional" if conditional else "always"
                prev_mode, evidence = out.get(alias, ("conditional", []))
                # 'always' wins over 'conditional' for the same alias.
                mode = "always" if prev_mode == "always" or mode == "always" else "conditional"
                evidence.append(f"{rel}: {stripped}")
                out[alias] = (mode, evidence)
    # Transitive closure (#1448): walk libs_edges from every directly
    # linked alias; each newly reached alias is wired 'conditional'
    # (it rides the linking lib's own gate) with the path as evidence.
    frontier = list(out.keys())
    seen = set(out.keys())
    while frontier:
        alias = frontier.pop()
        for dep, ev in libs_edges.items():
            if dep in seen:
                continue
            if any(e.startswith(f"libs/{alias}/") or f"(via {alias})" in e
                   for e in ev):
                # dep is linked by the unit that declares `alias`
                mode, evidence = out.get(dep, ("conditional", []))
                evidence = evidence + [f"transitive via {alias}: {ev[0]}"]
                out[dep] = ("conditional", evidence)
                seen.add(dep)
                frontier.append(dep)
    return out


def scan_conv_defines(root: str) -> Set[str]:
    found: Set[str] = set()
    for dirpath, filenames in walk_files(root, "apps"):
        for fn in filenames:
            if fn == "CMakeLists.txt":
                found.update(RE_CONV_DEFINE.findall(read_text(os.path.join(dirpath, fn))))
    return found


def scan_python_packages(root: str) -> List[str]:
    pkg = os.path.join(root, "paleo_workbench")
    if not os.path.isdir(pkg):
        return []
    out = []
    for entry in sorted(os.listdir(pkg)):
        if entry.startswith(".") or entry in PRUNE_DIRS:
            continue
        if os.path.isdir(os.path.join(pkg, entry)) and os.path.exists(
            os.path.join(pkg, entry, "__init__.py")
        ):
            out.append(entry)
    return out


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


def classify(fact: UnitFact) -> str:
    has_oracle = bool(fact.fixtures) or bool(fact.oracle_generators)
    if fact.wired and has_oracle and fact.production_includes:
        # Wired covers both a direct apps/root link ('always') and the
        # transitive link closure through a gated lib ('conditional') —
        # both reach the product binary in the native-product configure.
        # NATIVE_PRODUCT additionally requires a production TU consumer
        # (#1448): linked-but-never-included cores (the integrated
        # compilation family) stay NATIVE_LIBRARY_NOT_WIRED so retiring
        # the Python side cannot orphan the capability.
        return "native_complete_wired"
    if fact.wired and has_oracle and not fact.production_includes:
        fact.notes.append(
            "linked into the product closure but no production TU "
            "includes its headers (test-only consumers do not count)"
        )
    if has_oracle:
        return "native_core_not_wired"
    # Infrastructure libraries that were never ported from Python (domain,
    # catalog, project, workspace, ui, ...) record no Python origin. Reporting
    # them as "partial native" would imply an unfinished port, which is a
    # different and misleading statement.
    if not fact.python_origins:
        return "native_no_python_origin"
    if not fact.python_origins_present and fact.python_origins_absent:
        return "legacy_deprecated_candidate"
    return "partial_native"


def build_inventory(root: str) -> dict:
    options = scan_options(root)
    gating = scan_root_gating(root)
    units = scan_units(root)
    fixtures_by_unit, tests_fixtures = scan_fixtures(root)
    units_by_origin: Dict[str, List[str]] = {}
    for name, fact in units.items():
        for ref in fact.python_origins_present:
            units_by_origin.setdefault(ref, []).append(name)
    generators, tests_tier, unattributed = attribute_generators(
        root, sorted(units), fixtures_by_unit, tests_fixtures, units_by_origin
    )
    wiring = scan_wiring(root)
    conv_defines = scan_conv_defines(root)
    # Production sources for include evidence: apps/** plus every lib's
    # src (tests/ fixtures excluded — test-only consumers do not make a
    # unit a product capability).
    production_sources: Set[str] = set()
    apps_src_root = os.path.join(root, "apps")
    for dirpath, _dirnames, filenames in os.walk(apps_src_root):
        for fn in filenames:
            if fn.endswith((".cpp", ".cc", ".cxx")):
                production_sources.add(
                    repo_rel(root, os.path.join(dirpath, fn)))
    for other in units.values():
        for src in other.sources:
            if "/tests/" not in src.replace("\\", "/") and "_tests/" not in src:
                production_sources.add(src)
    python_packages = scan_python_packages(root)

    for name, fact in units.items():
        fact.fixtures = fixtures_by_unit.get(name, [])
        fact.oracle_generators = generators.get(name, [])
        subdir = f"libs/{name}"
        gated_by = gating.get(subdir, [])
        fact.options = sorted(set(gated_by))
        for opt in gated_by:
            if opt in options:
                options[opt].gates_subdirs.append(subdir)

        # Production TU include evidence (#1448): the unit's public
        # namespace prefix (pwb/<ns>/ from its first header path) scanned
        # across every OTHER unit's sources and apps/** sources.
        if fact.headers:
            import re as _re
            header = fact.headers[0]
            mprefix = _re.search(r"include/(pwb/[^/]+(?:/[^/]+)*)/", header)
            if mprefix:
                ns = mprefix.group(1) + "/"
                for other_name, other in units.items():
                    if other_name == name:
                        continue
                    for src in other.sources:
                        if src in production_sources:
                            try:
                                text = read_text(os.path.join(root, src))
                            except OSError:
                                continue
                            if ns in text:
                                fact.production_includes.append(src)
        for alias in set(fact.aliases + [fact.alias, fact.target]) - {None}:
            if alias in wiring:
                mode, evidence = wiring[alias]
                if not fact.wired or fact.wiring_mode == "conditional":
                    fact.wired = True
                    fact.wiring_mode = mode
                fact.wiring_evidence.extend(evidence[:4])
        for slice_id in fact.slices:
            define = "PWB_WITH_" + slice_id.replace("-", "_")
            if define in conv_defines:
                if not fact.wired:
                    fact.wired = True
                    fact.wiring_mode = "conditional"
                fact.wiring_evidence.append(f"compile definition {define} in apps/")
        fact.wiring_evidence = sorted(set(fact.wiring_evidence))
        fact.production_includes = sorted(set(fact.production_includes))
        fact.status = classify(fact)

        if not fact.python_origins:
            fact.notes.append(
                "no Python origin recorded: treated as native-only infrastructure "
                "(not a port) rather than an unfinished one"
            )
        if fact.python_origins_absent and fact.python_origins_present:
            fact.notes.append("some recorded Python origins no longer exist in the tree")
        if fact.wired and not fact.fixtures:
            fact.notes.append("reaches the app but carries no frozen oracle fixture")
        if not fact.options:
            fact.notes.append("no PWB_BUILD_* switch gates this unit (always configured)")
        if fact.wiring_mode == "conditional":
            fact.notes.append("app link is conditional on an opt-in switch")

    covered: Set[str] = set()
    for fact in units.values():
        covered.update(fact.python_origins_present)

    package_rows = []
    for pkg in python_packages:
        hits = sorted(ref for ref in covered if ref.startswith(f"paleo_workbench/{pkg}/"))
        package_rows.append(
            {
                "package": pkg,
                "covered_modules": len(hits),
                "status": "partial_native" if hits else "python_only_production",
                "sample": hits[:5],
            }
        )

    slice_rollup: Dict[str, dict] = {}
    for fact in units.values():
        for slice_id in fact.slices:
            entry = slice_rollup.setdefault(
                slice_id,
                {"slice": slice_id, "option": None, "units": [], "fixtures": [],
                 "tests": [], "wired": False},
            )
            entry["units"].append(fact.unit)
            entry["fixtures"].extend(fact.fixtures)
            entry["tests"].extend(fact.tests)
            entry["wired"] = entry["wired"] or fact.wired
    for slice_id, entry in slice_rollup.items():
        opt = "PWB_BUILD_" + slice_id.replace("-", "_")
        entry["option"] = opt if opt in options else None
        entry["units"] = sorted(set(entry["units"]))
        entry["fixtures"] = sorted(set(entry["fixtures"]))
        entry["tests"] = sorted(set(entry["tests"]))

    status_counts: Dict[str, int] = {}
    for fact in units.values():
        status_counts[fact.status] = status_counts.get(fact.status, 0) + 1
    status_counts["python_only_production"] = sum(
        1 for row in package_rows if row["status"] == "python_only_production"
    )
    status_counts["oracle_test_only_python"] = len(unattributed)

    distinct_generators = sorted(
        {g for v in generators.values() for g in v} | set(unattributed) | set(tests_tier)
    )
    distinct_fixtures = sorted({f for v in fixtures_by_unit.values() for f in v} | set(tests_fixtures))

    return {
        "schema_version": 2,
        "generated_from": {
            "libs_units": len(units),
            "cmake_options": len(options),
            "oracle_generators": len(distinct_generators),
            "fixtures": len(distinct_fixtures),
            "python_packages": len(python_packages),
        },
        "status_labels": STATUS_LABELS,
        "status_counts": status_counts,
        "units": [asdict(u) for u in sorted(units.values(), key=lambda u: u.unit)],
        "python_packages": package_rows,
        "slices": [slice_rollup[k] for k in sorted(slice_rollup)],
        "options": [
            {
                "name": o.name,
                "doc": o.doc,
                "declared_in": o.declared_in,
                "gates_subdirs": sorted(set(o.gates_subdirs)),
            }
            for o in sorted(options.values(), key=lambda o: o.name)
        ],
        "oracle_only_python": unattributed,
        "oracle_tests_tier_python": tests_tier,
        "tests_fixtures": tests_fixtures,
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def render_markdown(inv: dict) -> str:
    out: List[str] = []
    out.append("# C++ Migration Inventory (generated)")
    out.append("")
    out.append(
        "Generated by `tools/migration/pwb_migration_inventory.py` from repository "
        "facts (CMake options, `libs/*` trees, C++ header attributions, oracle "
        "fixtures and app wiring). Do not hand-edit; re-run the generator."
    )
    out.append("")
    gen = inv["generated_from"]
    out.append(
        f"Scope: **{gen['libs_units']}** C++ units, **{gen['cmake_options']}** CMake "
        f"options, **{gen['oracle_generators']}** oracle generators, "
        f"**{gen['fixtures']}** frozen fixtures, **{gen['python_packages']}** Python "
        "production packages."
    )
    out.append("")
    out.append("## Status roll-up")
    out.append("")
    out.append("| Status | Meaning | Count |")
    out.append("| --- | --- | --- |")
    for status, label in STATUS_LABELS.items():
        out.append(f"| `{status}` | {label} | {inv['status_counts'].get(status, 0)} |")
    out.append("")

    out.append("## Conversion units")
    out.append("")
    out.append("| Unit | Status | Switch | Slices | Oracle | Tests | Wiring |")
    out.append("| --- | --- | --- | --- | --- | --- | --- |")
    for u in inv["units"]:
        out.append(
            "| `{unit}` | `{status}` | {switch} | {slices} | {oracle} | {tests} | {wiring} |".format(
                unit=u["unit"],
                status=u["status"],
                switch=", ".join(f"`{o}`" for o in u["options"]) or "—",
                slices=", ".join(u["slices"]) or "—",
                oracle="yes" if u["fixtures"] else "—",
                tests=len(u["tests"]),
                wiring=u["wiring_mode"].replace("_", " "),
            )
        )
    out.append("")

    out.append("## Python production package coverage")
    out.append("")
    out.append("| Package | Status | Covered modules | Sample |")
    out.append("| --- | --- | --- | --- |")
    for row in inv["python_packages"]:
        sample = ", ".join(f"`{s}`" for s in row["sample"]) or "—"
        out.append(
            "| `{pkg}` | `{status}` | {n} | {sample} |".format(
                pkg=row["package"], status=row["status"], n=row["covered_modules"], sample=sample
            )
        )
    out.append("")

    out.append("## CONV slice roll-up")
    out.append("")
    out.append("| Slice | Option | Units | Tests | Wired |")
    out.append("| --- | --- | --- | --- | --- |")
    for s in inv["slices"]:
        out.append(
            "| {slice} | {opt} | {units} | {tests} | {wired} |".format(
                slice=s["slice"],
                opt=f"`{s['option']}`" if s["option"] else "—",
                units=", ".join(f"`{x}`" for x in s["units"]) or "—",
                tests=len(s["tests"]),
                wired="yes" if s["wired"] else "no",
            )
        )
    out.append("")

    out.append("## Python origin surface per unit")
    out.append("")
    for u in inv["units"]:
        if not u["python_origins"]:
            continue
        out.append(f"### `{u['unit']}`")
        out.append("")
        for ref in u["python_origins"]:
            mark = "present" if ref in u["python_origins_present"] else "**absent**"
            out.append(f"- `{ref}` — {mark}")
        for note in u["notes"]:
            out.append(f"- note: {note}")
        out.append("")

    if inv.get("oracle_tests_tier_python"):
        out.append("## Oracle generators feeding the `tests/` tier")
        out.append("")
        out.append(
            "These freeze fixtures consumed by `tests/cpp/**` rather than by a "
            "`libs/` unit test."
        )
        out.append("")
        for item in inv["oracle_tests_tier_python"]:
            out.append(f"- `{item}`")
        out.append("")

    if inv["oracle_only_python"]:
        out.append("## Oracle/test-only Python (no attributed C++ unit)")
        out.append("")
        for item in inv["oracle_only_python"]:
            out.append(f"- `{item}`")
        out.append("")

    out.append("## C++ units with no recorded Python origin")
    out.append("")
    out.append(
        "These are read as native-only infrastructure (never ported from Python) "
        "rather than as unfinished ports. If one of them *was* meant to replace a "
        "Python module, the header is missing its attribution and the record below "
        "is the one to fix."
    )
    out.append("")
    gaps = [u for u in inv["units"] if not u["python_origins"]]
    if not gaps:
        out.append("None — every C++ unit records its Python origin.")
    else:
        for u in gaps:
            out.append(f"- `{u['unit']}` ({u['status']})")
    out.append("")

    partial = [u for u in inv["units"]
               if u["python_origins_absent"] and u["python_origins_present"]]
    out.append("## Partial attribution (some recorded origins are gone)")
    out.append("")
    if not partial:
        out.append("None — every recorded Python origin still exists in the tree.")
    else:
        for u in partial:
            out.append(f"- `{u['unit']}`: missing {', '.join('`' + p + '`' for p in u['python_origins_absent'])}")
    out.append("")
    return "\n".join(out) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", default=".", help="repository root (default: cwd)")
    parser.add_argument(
        "--json-out",
        default="build/migration-inventory/migration_inventory.json",
        help="machine-readable output path",
    )
    parser.add_argument(
        "--markdown-out",
        default="build/migration-inventory/migration_inventory.md",
        help="Markdown roll-up output path",
    )
    parser.add_argument("--quiet", action="store_true", help="suppress the stdout summary")
    args = parser.parse_args(argv)

    root = os.path.abspath(args.repo_root)
    if not os.path.exists(os.path.join(root, "CMakeLists.txt")):
        print(f"error: {root} does not look like the repository root", file=sys.stderr)
        return 2

    inv = build_inventory(root)
    for out_path, content in (
        (args.json_out, json.dumps(inv, indent=2, ensure_ascii=False) + "\n"),
        (args.markdown_out, render_markdown(inv)),
    ):
        full = out_path if os.path.isabs(out_path) else os.path.join(root, out_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)

    if not args.quiet:
        print(f"inventory: {inv['generated_from']['libs_units']} units")
        for status in STATUS_LABELS:
            print(f"  {status:32s} {inv['status_counts'].get(status, 0)}")
        print(f"json     -> {args.json_out}")
        print(f"markdown -> {args.markdown_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
