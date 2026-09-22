#!/usr/bin/env python3
"""Generate the line-11 agent/harness oracle from the frozen Python product.

Run from the repository root with the product importable (read-only use of
the Python sources — the oracle JSON lands in this directory):

    python3 libs/closure_agent/oracle/generate_agent_oracle.py

The output (closure_agent_tests/agent_oracle.json) freezes, for the current
Python tree: intent-parse verdicts, planner DAG skeletons, action-spec
validation problems, tool-schema derivation, and the executor guard message
strings. The C++ port tests compare against this file byte-for-byte on the
semantic fields. Regenerating requires the Python tree at a known SHA —
record it in the ledger when the oracle is refreshed.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# The product package __init__ chain pulls the full GUI/science dependency
# tree. The four modules this oracle freezes have no such imports: load them
# directly by path behind package stubs so their intra-package imports
# resolve, without executing any __init__.
import importlib.util  # noqa: E402
import types  # noqa: E402


def _stub_package(name: str, path: Path) -> None:
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ARCHIVE_PRODUCT = REPO / "legacy" / "python_reference" / "product"  # Python-retirement
_stub_package("paleo_workbench", ARCHIVE_PRODUCT / "paleo_workbench")
_stub_package("paleo_workbench.agent", ARCHIVE_PRODUCT / "paleo_workbench" / "agent")
_stub_package("paleo_workbench.harness", ARCHIVE_PRODUCT / "paleo_workbench" / "harness")
_stub_package("paleo_workbench.providers", ARCHIVE_PRODUCT / "paleo_workbench" / "providers")
_intent = _load(
    "paleo_workbench.agent.intent",
    ARCHIVE_PRODUCT / "paleo_workbench" / "agent" / "intent.py",
)
_planner = _load(
    "paleo_workbench.agent.planner",
    ARCHIVE_PRODUCT / "paleo_workbench" / "agent" / "planner.py",
)
_spec = _load(
    "paleo_workbench.harness.spec",
    ARCHIVE_PRODUCT / "paleo_workbench" / "harness" / "spec.py",
)
_load(
    "paleo_workbench.providers.contracts",
    ARCHIVE_PRODUCT / "paleo_workbench" / "providers" / "contracts.py",
)

IntentParser = _intent.IntentParser
TaskPlanner = _planner.TaskPlanner
ActionRisk = _spec.ActionRisk
ActionSpec = _spec.ActionSpec
validate_action_spec = _spec.validate_action_spec
DEFAULT_PERMISSIONS = _spec.DEFAULT_PERMISSIONS

QUERIES = [
    "对比XX井和YY井的砂组顶面分层并拉平GR曲线",
    "对长东区块做砂地比单因素编图，目标层位长8段",
    "编制鄂尔多斯盆地长8段古地理图，输出出版级排版",
    "检查地震工区inline 500切片的相干属性异常",
    "把图层导出为高精SVG和PDF截图",
    "清理目录中的孤立点并对资产版本做质检QC",
    "导入新井的LAS测井曲线到数据资产catalog",
    "今天天气怎么样",
]

SPECS = {
    "ok_compute": ActionSpec(
        action_id="well.correlate_tops",
        description="Correlate formation tops across wells",
        risk=ActionRisk.COMPUTE,
        version="1.2",
        deterministic=True,
        cacheable=True,
        output_refs=("PathRef",),
        domain_tags=("well", "correlation"),
    ),
    "bad_id": ActionSpec(action_id="Bad-ID", description="x"),
    "bad_cacheable": ActionSpec(
        action_id="map.export",
        description="x",
        cacheable=True,
    ),
    "bad_version": ActionSpec(action_id="map.export", description="x", version="v1"),
    "no_executable": ActionSpec(action_id="map.export", description="x"),
    "bad_tag": ActionSpec(action_id="map.export", description="x", domain_tags=("Bad Tag",)),
    "destructive": ActionSpec(action_id="map.purge", description="x", risk=ActionRisk.DESTRUCTIVE),
}

TOOL_SCHEMA_ACTION = ActionSpec(
    action_id="geology.factor_summary",
    description="Summarize a factor dataset",
    provider_id="geology.factor_stats",
    risk=ActionRisk.READ,
    input_schema={
        "type": "object",
        "properties": {
            "report_name": {"type": "string", "description": "报告工件名"},
        },
        "required": ["report_name"],
        "additionalProperties": False,
    },
)


def intent_record(query: str) -> dict:
    parser = IntentParser()
    parsed = parser.parse(query)
    return {
        "query": query,
        "raw_query": parsed.raw_query,
        "primary_domain": parsed.primary_domain.value,
        "secondary_domains": [d.value for d in parsed.secondary_domains],
        "target_horizon": parsed.target_horizon,
        "factor_type": parsed.factor_type,
        "suggested_skills": list(parsed.suggested_skills),
        "requires_data": parsed.requires_data,
        "confidence": parsed.confidence,
    }


def plan_record(query: str) -> dict:
    intent = IntentParser().parse(query)
    graph = TaskPlanner().create_plan(intent)
    nodes = []
    for node in graph.nodes.values():  # insertion order
        nodes.append(
            {
                "id": node.id,
                "agent_name": node.agent_name,
                "action": node.action,
                "dependencies": list(node.dependencies),
            }
        )
    return {"query": query, "primary_domain": intent.primary_domain.value, "nodes": nodes}


def spec_record() -> list:
    records = []
    for name, spec in SPECS.items():
        try:
            problems = validate_action_spec(spec)
        except Exception as exc:  # validate_action_spec itself raised
            problems = [f"<raise> {type(exc).__name__}: {exc}"]
        records.append({"name": name, "problems": problems})
    return records


def tool_schema_record() -> dict:
    return TOOL_SCHEMA_ACTION.tool_schema()


def permissions_record() -> list:
    return sorted(r.value for r in DEFAULT_PERMISSIONS)


def main() -> int:
    oracle = {
        "schema_version": "1.0",
        "source": "frozen paleo_workbench Python tree (see line-11 ledger for SHA)",
        "intents": [intent_record(q) for q in QUERIES],
        "plans": [plan_record(q) for q in QUERIES],
        "spec_validation": spec_record(),
        "tool_schema": tool_schema_record(),
        "default_permissions": permissions_record(),
    }
    out = Path(__file__).resolve().parent.parent / "closure_agent_tests" / "agent_oracle.json"
    out.write_text(json.dumps(oracle, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
