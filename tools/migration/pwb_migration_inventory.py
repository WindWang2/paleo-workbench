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
RE_INCLUDE = re.compile(r'#\s*include\s*[<"]([^<">]+)[>"]')
RE_TOKEN = re.compile(r"[A-Za-z0-9_:.+-]+")
LINK_KEYWORDS = {
    "LINK_PUBLIC", "LINK_PRIVATE", "LINK_INTERFACE_LIBRARIES",
    "INTERFACE", "PUBLIC", "PRIVATE", "debug", "optimized", "general",
}

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
    # All add_library names / all Pwb:: aliases defined by the unit's CMake
    # files. The single-target/alias fields above stay for schema continuity;
    # wiring resolution must consult the full sets (a unit may expose several
    # aliases, and only some of them may be linked).
    targets: List[str] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    headers: List[str] = field(default_factory=list)
    public_include_keys: List[str] = field(default_factory=list)
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
    # TU-level consumer evidence (#1448): which units/apps translation units
    # actually include this unit's public headers, and whether that include
    # graph reaches the unit from an apps/ TU.
    tu_consumers: List[str] = field(default_factory=list)
    tu_reachable: bool = False
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
                    if target not in fact.aliases:
                        fact.aliases.append(target)
                elif target not in fact.targets:
                    fact.targets.append(target)
        fact.alias = fact.aliases[0] if fact.aliases else None
        fact.target = fact.targets[0] if fact.targets else None
        for path in cml_files:
            text = read_text(path)
            fact.tests.extend(RE_ADD_TEST.findall(text))
        fact.tests = sorted(set(fact.tests))
        fact.slices = scan_slices(cml_files)
        fact.python_origins = scan_python_origins(root, fact.headers + fact.sources + cml_files)
        for ref in fact.python_origins:
            if os.path.exists(os.path.join(root, ref)) or (
                ref.startswith("paleo_workbench/")
                and os.path.exists(os.path.join(root, "legacy", "python_reference",
                                                "product", ref))
            ):
                # A retired origin still counts as present: it lives in the
                # archive now (docs/development/python-retirement/).
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


def _cmake_command_spans(text: str) -> Iterable[Tuple[str, List[str], int, bool]]:
    """Yield (command, args, line_no, inside_conditional_block) for a CMake text.

    Only the commands the wiring scan cares about (add_library,
    add_executable, target_link_libraries) are emitted. The conditional flag
    mirrors the legacy line-based rule: a block guarded by ``if(PWB_...)`` is
    conditional; ``else/elseif`` inversion is intentionally not modelled (the
    conservative direction — such links stay "conditional").
    """
    lines = text.splitlines()
    # Per-line PWB_ condition tokens plus line start offsets, so a command
    # span can union the guards of every line it touches.
    line_tokens: List[frozenset] = []
    line_starts: List[int] = []
    stack: List[str] = []
    pos = 0
    for line in lines:
        stripped = line.strip()
        tokens: Set[str] = set()
        if stripped and not stripped.startswith("#"):
            m_if = RE_IF.match(line)
            if m_if:
                stack.append(m_if.group(1))
            elif RE_ENDIF.match(line):
                if stack:
                    stack.pop()
            tokens = {
                token
                for cond in stack
                for token in re.findall(r"PWB_[A-Z0-9_]+", cond)
            }
        line_starts.append(pos)
        line_tokens.append(frozenset(tokens))
        pos += len(line) + 1

    def guards_of(start: int, end: int) -> Set[str]:
        out: Set[str] = set()
        for index, line_start in enumerate(line_starts):
            if line_start > end:
                break
            if line_start + len(lines[index]) >= start:
                out |= line_tokens[index]
        return out
    for m in re.finditer(
        r"\b(add_library|add_executable|target_link_libraries)\s*\(", text
    ):
        command = m.group(1)
        # Find the matching close paren.
        depth = 1
        end = m.end()
        while end < len(text) and depth:
            ch = text[end]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            end += 1
        inner = text[m.end():end - 1]
        args = RE_TOKEN.findall(inner)
        line_no = text.count("\n", 0, m.start()) + 1
        yield command, args, line_no, guards_of(m.start(), end)


def scan_product_implied_switches(root: str) -> Set[str]:
    """Transitive closure of the switches PWB_BUILD_NATIVE_PRODUCT turns on.

    ``cmake/PwbFeatures.cmake`` declares the feature graph
    (``pwb_declare_feature(<NAME> ... IMPLIES a;b ...)``); the formal native
    product closure is the closure of NATIVE_PRODUCT's IMPLIES set. A link
    edge guarded only by switches in this set is ON in every formal product
    configuration, so it must not be reported as opt-in conditional wiring.
    """
    text = read_text(os.path.join(root, "cmake", "PwbFeatures.cmake"))
    implies: Dict[str, List[str]] = {}
    for m in re.finditer(r"pwb_declare_feature\(\s*([A-Z][A-Z0-9_]*)", text):
        name = m.group(1)
        depth = 1
        end = m.end()
        while end < len(text) and depth:
            ch = text[end]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            end += 1
        body = text[m.end():end - 1]
        # Everything before REQUIRES (if present) belongs to IMPLIES when the
        # keyword is present; otherwise there is no implies list.
        if "IMPLIES" in body:
            implies_tail = body.split("IMPLIES", 1)[1]
            implies_tail = implies_tail.split("REQUIRES", 1)[0]
            implies[name] = re.findall(r"PWB_BUILD_[A-Z0-9_]+", implies_tail)
        else:
            implies[name] = []
    closure: Set[str] = set()
    frontier = ["PWB_BUILD_NATIVE_PRODUCT"]
    while frontier:
        name = frontier.pop()
        for nxt in implies.get(name, []):
            if nxt not in closure:
                closure.add(nxt)
                frontier.append(nxt)
    return closure


def scan_link_graph(
    root: str, units: Dict[str, UnitFact]
) -> Dict[str, Dict[str, object]]:
    """Whole-repository link graph with transitive closure from the product.

    Replaces the legacy apps/-only direct scan (#1448 A-3): every
    ``target_link_libraries`` edge in the repository (root, apps/, libs/,
    tests/) is collected, tokens are resolved to ``libs/<unit>`` through the
    *full* alias and target sets of each unit, and product wiring is the
    transitive closure from the ``pwb-platform`` executable.

    Returns unit -> {wired, wiring_mode, wiring_evidence} where mode is
    'always' (an all-unconditional-edge path exists), 'product' (every guard
    on the best path is a switch PWB_BUILD_NATIVE_PRODUCT implies, so the link
    is present in every formal product configuration), 'conditional' (only
    genuinely opt-in paths), or the unit is absent when unreachable.
    """
    # token -> unit resolution table (aliases + bare target names).
    token_unit: Dict[str, str] = {}
    for name, fact in units.items():
        for token in list(fact.aliases) + list(fact.targets):
            token_unit.setdefault(token, name)

    edges: Dict[str, List[Tuple[str, str, str]]] = {}
    implied = scan_product_implied_switches(root)
    for dirpath, filenames in walk_files(root, ""):
        for fn in filenames:
            if fn != "CMakeLists.txt":
                continue
            path = os.path.join(dirpath, fn)
            rel = repo_rel(root, path)
            text = read_text(path)
            for command, args, line_no, cond_tokens in _cmake_command_spans(text):
                if command in ("add_library", "add_executable"):
                    continue
                if len(args) < 2:
                    continue
                src = args[0]
                if cond_tokens and cond_tokens <= implied:
                    category = "product"
                elif cond_tokens:
                    category = "optin"
                else:
                    category = "always"
                for token in args[1:]:
                    if token in LINK_KEYWORDS:
                        continue
                    dst = token_unit.get(token)
                    if dst is None:
                        continue
                    edges.setdefault(src, []).append(
                        (dst, category, f"{rel}:{line_no} ({token})")
                    )

    product_root = "pwb-platform"
    allowed: Dict[str, Set[str]] = {
        "always": {"always"},
        "product": {"always", "product"},
        "all": {"always", "product", "optin"},
    }

    def closure(level: str) -> Dict[str, Tuple[str, str]]:
        found: Dict[str, Tuple[str, str]] = {}
        queue: List[Tuple[str, str, str]] = [(product_root, "", "")]
        seen_targets = {product_root}
        permit = allowed[level]
        while queue:
            src, via_unit, via_ev = queue.pop(0)
            for dst, category, ev in edges.get(src, []):
                if category not in permit:
                    continue
                evidence = (f"{src} -> {ev}" if not via_ev else f"{via_ev} -> {ev}")
                if dst not in found or (len(evidence) < len(found[dst][1])):
                    found[dst] = (via_unit or "apps", evidence)
                # Traverse onward through any target name of the destination
                # unit so transitive edges resolve.
                if dst in seen_targets:
                    continue
                seen_targets.add(dst)
                fact = units.get(dst)
                names = ([fact.alias] if fact and fact.alias else []) + (
                    fact.targets if fact else []
                )
                for name in names:
                    if name not in seen_targets:
                        seen_targets.add(name)
                        queue.append((name, dst, evidence))
        return found

    always = closure("always")
    product = closure("product")
    all_paths = closure("all")
    out: Dict[str, Dict[str, object]] = {}
    for unit, (origin, evidence) in all_paths.items():
        if unit in always:
            mode = "always"
        elif unit in product:
            mode = "product"
        else:
            mode = "conditional"
        out[unit] = {
            "wired": True,
            "wiring_mode": mode,
            "wiring_evidence": [evidence],
            "link_origin": origin,
        }
    return out


def scan_tu_consumers(root: str, units: Dict[str, UnitFact]) -> None:
    """TU-level consumer evidence (#1448 A-2): fill ``tu_consumers`` and
    ``tu_reachable`` on each unit.

    A unit is consumed by a translation unit when that TU #includes one of the
    unit's public headers (``libs/<unit>/include/**``). A unit is
    TU-reachable when some apps/ TU reaches it through the include graph
    (apps TU -> unit -> that unit's own TUs -> further units). Link-time
    presence without a TU consumer is exactly the false-NATIVE_PRODUCT shape
    issue #1448 describes, so this scan is what backs the promoted
    classification.
    """
    include_key_unit: Dict[str, Set[str]] = {}
    for name, fact in units.items():
        prefix = f"libs/{name}/include/"
        for header in fact.headers:
            if not header.startswith(prefix):
                continue
            key = header[len(prefix):]
            fact.public_include_keys.append(key)
            include_key_unit.setdefault(key, set()).add(name)

    def units_included_by(rel_path: str) -> Set[str]:
        text = read_text(os.path.join(root, rel_path))
        found: Set[str] = set()
        for m in RE_INCLUDE.finditer(text):
            inc = normalise(m.group(1))
            # Exact public-key match, or suffix match for angled includes
            # rooted elsewhere (e.g. "pwb/seismic_io/reader.hpp").
            if inc in include_key_unit:
                found.update(include_key_unit[inc])
                continue
            marker = "pwb/"
            idx = inc.find(marker)
            if idx >= 0:
                suffix = inc[idx:]
                if suffix in include_key_unit:
                    found.update(include_key_unit[suffix])
        return found

    # file -> directly included units.
    file_units: Dict[str, Set[str]] = {}
    app_files: List[str] = []
    unit_files: Dict[str, List[str]] = {name: [] for name in units}
    for dirpath, filenames in walk_files(root, ""):
        rel_dir = repo_rel(root, dirpath)
        for fn in filenames:
            if not fn.endswith((".cpp", ".cc", ".cxx", ".hpp", ".h")):
                continue
            rel = f"{rel_dir}/{fn}"
            if rel_dir == "apps" or rel_dir.startswith("apps/"):
                app_files.append(rel)
            m = re.match(r"libs/([^/]+)/", rel_dir)
            if m and m.group(1) in unit_files:
                unit_files[m.group(1)].append(rel)
    for rel in app_files:
        file_units[rel] = units_included_by(rel)
    for name, files in unit_files.items():
        for rel in files:
            file_units[rel] = units_included_by(rel)

    # BFS over apps TU -> unit -> unit TUs -> ...
    reached: Set[str] = set()
    consumers: Dict[str, Set[str]] = {name: set() for name in units}
    queue: List[str] = []
    for rel in app_files:
        for unit in file_units.get(rel, ()):  # apps TU directly includes unit
            if unit not in consumers or rel.startswith(f"libs/{unit}/"):
                continue
            consumers[unit].add(rel)
            if unit not in reached:
                reached.add(unit)
                queue.append(unit)
    while queue:
        unit = queue.pop(0)
        for rel in unit_files.get(unit, []):
            for nxt in file_units.get(rel, ()):
                if nxt == unit or nxt not in consumers:
                    continue
                consumers[nxt].add(f"libs/{unit}")
                if nxt not in reached:
                    reached.add(nxt)
                    queue.append(nxt)

    for name, fact in units.items():
        fact.tu_consumers = sorted(consumers.get(name, ()))
        fact.tu_reachable = name in reached


def scan_conv_defines(root: str) -> Set[str]:
    found: Set[str] = set()
    for dirpath, filenames in walk_files(root, "apps"):
        for fn in filenames:
            if fn == "CMakeLists.txt":
                found.update(RE_CONV_DEFINE.findall(read_text(os.path.join(dirpath, fn))))
    return found


def python_product_dir(root: str) -> str:
    """The retired Python package dir: active tree first, else the archive
    (legacy/python_reference/product — the package was retired with the
    Python retirement; see docs/development/python-retirement/)."""
    pkg = os.path.join(root, "paleo_workbench")
    if os.path.isdir(pkg):
        return pkg
    archived = os.path.join(root, "legacy", "python_reference", "product",
                            "paleo_workbench")
    if os.path.isdir(archived):
        return archived
    return pkg  # absent; callers treat missing dirs as empty


def scan_python_packages(root: str) -> List[str]:
    pkg = python_product_dir(root)
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
    # NATIVE_PRODUCT requires TU-level product consumer evidence (#1448 A-2):
    # linked-but-never-included is a library, not a product capability.
    # wiring_mode 'product' means every guarding switch on the link path is
    # implied by PWB_BUILD_NATIVE_PRODUCT (on in every formal product build).
    product_linked = fact.wiring_mode in ("always", "product")
    if product_linked and fact.wired and fact.tu_reachable and has_oracle:
        return "native_complete_wired"
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
    wiring = scan_link_graph(root, units)
    conv_defines = scan_conv_defines(root)
    python_packages = scan_python_packages(root)
    scan_tu_consumers(root, units)

    for name, fact in units.items():
        fact.fixtures = fixtures_by_unit.get(name, [])
        fact.oracle_generators = generators.get(name, [])
        subdir = f"libs/{name}"
        gated_by = gating.get(subdir, [])
        fact.options = sorted(set(gated_by))
        for opt in gated_by:
            if opt in options:
                options[opt].gates_subdirs.append(subdir)

        link_info = wiring.get(name)
        if link_info:
            fact.wired = True
            fact.wiring_mode = str(link_info["wiring_mode"])
            fact.wiring_evidence.extend(
                str(ev) for ev in link_info["wiring_evidence"]
            )
        for slice_id in fact.slices:
            define = "PWB_WITH_" + slice_id.replace("-", "_")
            if define in conv_defines:
                if not fact.wired:
                    fact.wired = True
                    fact.wiring_mode = "conditional"
                fact.wiring_evidence.append(f"compile definition {define} in apps/")
        fact.wiring_evidence = sorted(set(fact.wiring_evidence))
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
        if fact.wired and not fact.tu_reachable:
            fact.notes.append(
                "linked into the product closure but no product TU includes its "
                "public headers (transitive-only link, no TU consumer)"
            )

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
        "schema_version": 3,
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
    out.append(
        "| Unit | Status | Switch | Slices | Oracle | Tests | Wiring | "
        "TU consumers | TU reachable |"
    )
    out.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for u in inv["units"]:
        out.append(
            "| `{unit}` | `{status}` | {switch} | {slices} | {oracle} | {tests} | {wiring} | {tu_consumers} | {tu_reachable} |".format(
                unit=u["unit"],
                status=u["status"],
                switch=", ".join(f"`{o}`" for o in u["options"]) or "—",
                slices=", ".join(u["slices"]) or "—",
                oracle="yes" if u["fixtures"] else "—",
                tests=len(u["tests"]),
                wiring=u["wiring_mode"].replace("_", " "),
                tu_consumers=len(u.get("tu_consumers", [])),
                tu_reachable="yes" if u.get("tu_reachable") else "no",
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
