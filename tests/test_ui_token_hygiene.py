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
    "ui/unified_map_canvas.py": 4,
    "ui/workstation/composite_document.py": 8,
    # V11 §E2：composite_editing 四条模板线已迁 CANVAS_* token（预算归零移出）。
    "ui/pages/lithology_crossplot_dialog.py": 3,
    "ui/pages/mapping_page.py": 3,
    "ui/pages/ai_check_advisor_dialog.py": 2,
    "ui/map_symbology_bridge.py": 2,
    "ui/workstation/common.py": 1,
    "ui/status_bar.py": 1,
    "ui/map_layer_properties.py": 1,
    # 领域语义科学色（D10）：stage_actions 的未知相回退调色板（哈希分类）
    # 与 categorized/空白相默认矢量样式 stroke/fill —— QGIS 地质图层样式，
    # 非 UI chrome 色，不并入 tokens。
    "ui/workstation/stage_actions.py": 4,
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
    """登记表中的每项都必须仍有对应违规，防止僵尸预算（V7 扩到全部三表）。"""
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
    # V7 新表（font-size / fixed-size）同样不得有僵尸预算。
    for table_name, budgets, pattern in (
        ("FONT_SIZE_BUDGETS", FONT_SIZE_BUDGETS, _FONT_LITERAL),
        ("FIXED_SIZE_BUDGETS", FIXED_SIZE_BUDGETS, _FIXED_LITERAL),
    ):
        for rel, budget in budgets.items():
            path = ROOT / rel
            if not path.exists():
                stale.append(f"{table_name}: {rel} 文件已不存在，请移除登记")
                continue
            actual = _count(path, pattern)
            if actual < budget:
                stale.append(
                    f"{table_name}: {rel} 预算 {budget} > 实际 {actual}，请下调")
            if budget <= 0:
                stale.append(f"{table_name}: {rel} 预算为 0 请直接移出登记表")
    assert not stale, "ratchet 登记表需要收敛：\n" + "\n".join(stale)


# ---------------------------------------------------------------------------
# V7 ratchets：字面字号 / 字面定宽 / emoji 禁令（goal §9；只能收缩）
# 迁移到 token 字号 / 最小-最大宽度对后下调预算；预算归零即移除登记。
# ---------------------------------------------------------------------------

FONT_SIZE_BUDGETS: dict[str, int] = {
    "ui/map_layer_properties.py": 2,
    "ui/page_placeholder.py": 1,
    "ui/pages/activity_card.py": 1,  # V11 §E3：12.5px 历史微调值（无刻度 token）
    "ui/pages/data_reader_panel.py": 2,
    "ui/pages/lithology_crossplot_dialog.py": 1,
    "ui/pages/map_document_panel.py": 1,
    "ui/pages/module_relationship.py": 5,
    "ui/pages/summary_table_preview_widget.py": 3,
    "ui/pages/well_seismic_joint_page.py": 1,  # V11 §E3：16px 页级标题（无刻度 token）
}

FIXED_SIZE_BUDGETS: dict[str, int] = {
    "ui/components/views.py": 1,
    "ui/pages/map_edit_toolbar.py": 1,
    "ui/pages/prediction_evidence_panel.py": 1,
    # 剖面模式下收起引擎剖面行头（0 高折叠机械，恢复走 maximumHeight 栈）
    "ui/pages/seismic_view_panel.py": 1,
    "ui/pages/stratigraphy_correlation_page.py": 1,
    "ui/pages/tag_widgets.py": 1,
}

_FONT_LITERAL = re.compile(r"font-size:\s*\d+(?:\.\d+)?px")
_FIXED_LITERAL = re.compile(r"setFixed(?:Width|Height)\(\s*\d+\s*\)")


def _count(path: Path, pattern: re.Pattern) -> int:
    return len(pattern.findall(path.read_text(encoding="utf-8")))


def _budget_check(budgets: dict[str, int], pattern: re.Pattern, what: str) -> None:
    offenders: list[str] = []
    for path in _iter_production_py():
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        found = _count(path, pattern)
        if found > budgets.get(rel, 0):
            offenders.append(f"{rel}: {found} > 预算 {budgets.get(rel, 0)}")
    assert not offenders, (
        f"production UI 出现新的{what}（超 ratchet 预算）——改用 tokens 字号或"
        "最小-最大宽度对:\n" + "\n".join(offenders))


def test_no_new_font_size_literals() -> None:
    _budget_check(FONT_SIZE_BUDGETS, _FONT_LITERAL, "字面 font-size")


def test_no_new_fixed_size_literals() -> None:
    _budget_check(FIXED_SIZE_BUDGETS, _FIXED_LITERAL, "字面 setFixedSize")


_EMOJI = re.compile("[🀀-🫿]")


def test_no_emoji_in_ui_strings() -> None:
    """goal §7：emoji 禁令（全范围硬禁；文本字形表 state_language 无 emoji）。"""
    offenders: list[str] = []
    for path in _iter_production_py():
        text = path.read_text(encoding="utf-8")
        if _EMOJI.search(text):
            offenders.append(str(path.relative_to(ROOT)).replace("\\", "/"))
    assert not offenders, (
        "production UI 含 emoji（goal §7 禁止）——改用 SVG 图标或"
        " state_language 文本字形:\n" + "\n".join(offenders))
