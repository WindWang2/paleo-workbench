"""UI token 卫生门禁（V5-U1）。

禁止 production UI 代码新增裸颜色字面量：裸 hex setStyleSheet、
QColor("#...") 字面色、``color: white`` 类命名色。设计语义色一律经
``paleo_workbench.tokens``（三主题同词汇表）；确属领域语义的科学色
（colormap、岩性图例、编辑会话 pen 色等）在 ALLOWED_VIOLATIONS 中以
ratchet 预算显式登记（见 decisions.md D10）。

规则：
- 范围 = 设计系统所有权边界：``paleo_workbench/ui/**`` + ``viz/hosts/**``；
  ``prototypes/**`` 整体豁免（NON-PRODUCTION，D9）。
- hex 识别要求含 a-f 字母且不被 ``(`` 前导——排除 issue 引用 ``(#379)``。
- 每文件预算只能下调不能上调；新增违规 → 失败；预算出现僵尸（>实际）→ 失败。

修复债务时：改用 tokens / style.bind 并同步下调预算；预算归零即移出登记表。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "paleo_workbench"
SCOPE_DIRS = [ROOT / "ui", ROOT / "viz" / "hosts"]
EXCLUDED_DIRS = {"prototypes"}

# ratchet：历史债务存量（file → 允许的违规行数）。只能调低。
ALLOWED_VIOLATIONS: dict[str, int] = {
    "ui/unified_map_canvas.py": 13,
    "ui/workstation/composite_document.py": 8,
    "ui/pages/project_well_map_page.py": 7,
    "ui/pages/module_relationship.py": 7,
    "ui/workstation/composite_editing.py": 4,
    "ui/pages/lithology_crossplot_dialog.py": 4,
    "viz/hosts/well_log_host.py": 3,
    "ui/pages/mapping_page.py": 3,
    "ui/pages/ai_check_advisor_dialog.py": 3,
    "viz/hosts/well_section_host.py": 2,
    "ui/workstation/agent_panel.py": 2,
    "ui/pages/geological_modeling_3d_page.py": 2,
    "ui/pages/data_view_models.py": 2,
    "ui/map_symbology_bridge.py": 2,
    "ui/workstation/common.py": 1,
    "ui/status_bar.py": 1,
    "ui/qgis_stack/display_canvas.py": 1,
    "ui/pages/visualization_page.py": 1,
    "ui/pages/seismic_slice_preview_widget.py": 1,
    "ui/map_status_bar.py": 1,
    "ui/map_layer_properties.py": 1,
}

_HEX_LITERAL = re.compile(
    r"(?<!\()#(?=[0-9a-fA-F]*[a-fA-F])(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b"
)
_QCOLOR_LITERAL = re.compile(r"QColor\(\s*\"#[0-9a-fA-F]{3,8}\"")
_NAMED_COLOR = re.compile(r"color:\s*(white|black|red|green|blue|grey|gray)\b")


def _iter_production_py() -> list[Path]:
    files: list[Path] = []
    for base in SCOPE_DIRS:
        for path in base.rglob("*.py"):
            if any(part in EXCLUDED_DIRS for part in path.relative_to(ROOT).parts):
                continue
            files.append(path)
    return files


def _violations(path: Path) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if _QCOLOR_LITERAL.search(line) or _NAMED_COLOR.search(line) or _HEX_LITERAL.search(line):
            found.append((lineno, line.strip()[:120]))
    return found


def test_no_new_raw_color_literals() -> None:
    offenders: list[str] = []
    for path in _iter_production_py():
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        budget = ALLOWED_VIOLATIONS.get(rel, 0)
        found = _violations(path)
        if len(found) > budget:
            sample = "; ".join(f"L{n}: {text}" for n, text in found[:5])
            offenders.append(
                f"{rel}: {len(found)} violations > budget {budget}\n    {sample}"
            )
    assert not offenders, (
        "production UI 出现新的裸颜色字面量（超过 ratchet 预算）——"
        "改用 paleo_workbench.tokens / ui.style.bind；确属领域语义色时"
        "在 ALLOWED_VIOLATIONS 显式登记并说明：\n" + "\n".join(offenders)
    )


def test_ratchet_only_shrinks() -> None:
    """登记表中的每项都必须仍有对应违规，防止僵尸预算。"""
    stale: list[str] = []
    known = set()
    for path in _iter_production_py():
        known.add(str(path.relative_to(ROOT)).replace("\\", "/"))
    for rel, budget in ALLOWED_VIOLATIONS.items():
        if rel not in known:
            stale.append(f"{rel}: 文件已不在范围，请移除登记")
            continue
        actual = len(_violations(ROOT / rel))
        if actual < budget:
            stale.append(f"{rel}: 预算 {budget} > 实际 {actual}，请下调")
        if budget <= 0:
            stale.append(f"{rel}: 预算为 0 请直接移出登记表")
    assert not stale, "ALLOWED_VIOLATIONS 需要收敛：\n" + "\n".join(stale)
