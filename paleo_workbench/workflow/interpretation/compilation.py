"""CompilationInputSet — 综合编图输入集（V9 ADR-7，goal §14）。

Phase 3 的科学运行**绝不**使用"当前可见"作为输入：输入集显式列出
evidence 选择器并在 freeze 时钉死版本。持久化形态为
``ProjectDocument.compilation_input_sets``（plain dict 载体，schema 由本
模块拥有——与 ``mapping_workspace`` 的 V5 §45 分工模式一致）；工作区旧
``compilation_input_set`` dict 保留为兼容视图（:func:`legacy_view` 镜像）。

状态机：``draft``（可增删证据）→ ``frozen``（版本已钉死，运行输入不可
漂移）。freeze 拒绝任何不可钉住的条目（缺失/未登记版本/未知），绝不
带着暗洞进入科学运行。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from paleo_workbench.workflow.interpretation.evidence import (
    EvidenceResolution,
    EvidenceStatus,
    parse_evidence_selector,
    resolve_evidence,
)


@dataclass
class CompilationInputSetEntry:
    """输入集中的一个证据条目（选择器 + 加入时的诚实解析快照）。"""

    selector: str
    label: str = ""
    evidence_kind: str = ""
    #: freeze 时钉死的版本（RESOLVED 条目）；freeze 前为空。
    pinned_version_id: str = ""
    resolved_asset_id: str = ""
    added_at: str = ""
    added_by: str = ""
    note: str = ""
    #: 加入时的解析状态（evidence.EvidenceStatus 词汇；快照，不随时间更新）。
    status_at_add: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "selector": self.selector,
            "label": self.label,
            "evidence_kind": self.evidence_kind,
            "pinned_version_id": self.pinned_version_id,
            "resolved_asset_id": self.resolved_asset_id,
            "added_at": self.added_at,
            "added_by": self.added_by,
            "note": self.note,
            "status_at_add": self.status_at_add,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompilationInputSetEntry":
        return cls(
            selector=str(data.get("selector") or ""),
            label=str(data.get("label") or ""),
            evidence_kind=str(data.get("evidence_kind") or ""),
            pinned_version_id=str(data.get("pinned_version_id") or ""),
            resolved_asset_id=str(data.get("resolved_asset_id") or ""),
            added_at=str(data.get("added_at") or ""),
            added_by=str(data.get("added_by") or ""),
            note=str(data.get("note") or ""),
            status_at_add=str(data.get("status_at_add") or ""),
        )


@dataclass
class CompilationInputSet:
    """一次综合编图的输入集（goal §14：base interpretation + factor versions
    + constraint versions + evidence versions + 配置）。"""

    id: str
    name: str = ""
    entries: list[CompilationInputSetEntry] = field(default_factory=list)
    created_at: str = ""
    created_by: str = ""
    #: 算法推荐记录（方法推荐 + 理由；人工选择记录在 manual_overrides）。
    recommendation: dict[str, Any] = field(default_factory=dict)
    manual_overrides: dict[str, Any] = field(default_factory=dict)
    configuration: dict[str, Any] = field(default_factory=dict)
    frozen: bool = False
    frozen_at: str = ""
    schema_version: int = 1

    # -- 视图 ---------------------------------------------------------------

    def entry_for_selector(self, selector: str) -> CompilationInputSetEntry | None:
        for entry in self.entries:
            if entry.selector == selector:
                return entry
        return None

    def selectors(self) -> list[str]:
        return [entry.selector for entry in self.entries]

    def legacy_view(self) -> dict[str, str]:
        """兼容视图：label → selector（dependencies/存档的旧词汇）。"""
        return {entry.label or entry.selector: entry.selector
                for entry in self.entries}

    # -- 序列化 ---------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "entries": [entry.to_dict() for entry in self.entries],
            "created_at": self.created_at,
            "created_by": self.created_by,
            "recommendation": dict(self.recommendation),
            "manual_overrides": dict(self.manual_overrides),
            "configuration": dict(self.configuration),
            "frozen": self.frozen,
            "frozen_at": self.frozen_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompilationInputSet":
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            entries=[CompilationInputSetEntry.from_dict(e)
                     for e in (data.get("entries") or [])
                     if isinstance(e, dict) and e.get("selector")],
            created_at=str(data.get("created_at") or ""),
            created_by=str(data.get("created_by") or ""),
            recommendation=dict(data.get("recommendation") or {}),
            manual_overrides=dict(data.get("manual_overrides") or {}),
            configuration=dict(data.get("configuration") or {}),
            frozen=bool(data.get("frozen", False)),
            frozen_at=str(data.get("frozen_at") or ""),
            schema_version=int(data.get("schema_version") or 1),
        )


@dataclass(frozen=True)
class CompilationValidation:
    """一次输入集验证的诚实结果。"""

    input_set_id: str
    resolutions: tuple[EvidenceResolution, ...]
    #: ready=全部可用（RESOLVED/FLOATING/STALE）；degraded=含 UNPINNED；
    #: blocked=含 MISSING/UNKNOWN。
    verdict: str  # ready | degraded | blocked
    detail: str = ""

    @property
    def factor_selectors(self) -> list[str]:
        return [r.selector.raw for r in self.resolutions
                if r.selector.raw.startswith("factor:")]

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_set_id": self.input_set_id,
            "verdict": self.verdict,
            "detail": self.detail,
            "entries": [r.to_dict() for r in self.resolutions],
        }


# ----------------------------------------------------------------- 生命周期


def create_input_set(
    document: Any,
    selectors: list[str],
    *,
    name: str = "",
    created_by: str = "",
    catalog: Any = None,
    workspace_state: Any = None,
    set_id: str = "",
    now: str = "",
) -> CompilationInputSet:
    """从证据选择器列表创建输入集（解析快照随条目记录，绝不猜）。"""
    import uuid

    entries: list[CompilationInputSetEntry] = []
    for raw in selectors:
        selector = parse_evidence_selector(str(raw))  # malformed → ValueError
        resolution = resolve_evidence(
            document, selector, catalog=catalog, workspace_state=workspace_state)
        entries.append(CompilationInputSetEntry(
            selector=selector.raw,
            label=resolution.display or selector.raw,
            evidence_kind=selector.kind.value,
            resolved_asset_id=resolution.asset_id,
            added_at=now,
            added_by=created_by,
            status_at_add=resolution.status.value,
            note=resolution.detail,
        ))
    return CompilationInputSet(
        id=set_id or f"ciset_{uuid.uuid4().hex[:12]}",
        name=name or f"综合编图输入集（{len(entries)} 项证据）",
        entries=entries,
        created_at=now,
        created_by=created_by,
    )


def validate_input_set(
    input_set: CompilationInputSet,
    document: Any,
    *,
    catalog: Any = None,
    workspace_state: Any = None,
) -> CompilationValidation:
    """逐条解析输入集（诚实 verdict：ready/degraded/blocked）。"""
    resolutions: list[EvidenceResolution] = []
    for entry in input_set.entries:
        if entry.pinned_version_id:
            # frozen 条目按钉住版本验证（selector 内的 version 即 pin）。
            pinned_selector = _selector_with_version(
                entry.selector, entry.pinned_version_id)
            resolutions.append(resolve_evidence(
                document, pinned_selector, catalog=catalog,
                workspace_state=workspace_state))
        else:
            resolutions.append(resolve_evidence(
                document, entry.selector, catalog=catalog,
                workspace_state=workspace_state))
    verdict = "ready"
    detail = ""
    statuses = [r.status for r in resolutions]
    if any(s in (EvidenceStatus.MISSING, EvidenceStatus.UNKNOWN)
           for s in statuses):
        verdict = "blocked"
        bad = [r.selector.raw for r in resolutions
               if r.status in (EvidenceStatus.MISSING, EvidenceStatus.UNKNOWN)]
        detail = f"存在不可用证据（缺失/未知）：{'；'.join(bad)}"
    elif any(s is EvidenceStatus.UNPINNED for s in statuses):
        verdict = "degraded"
        unpinned = [r.selector.raw for r in resolutions
                    if r.status is EvidenceStatus.UNPINNED]
        detail = f"存在未钉版本的证据（保存/提交后可冻结）：{'；'.join(unpinned)}"
    return CompilationValidation(input_set.id, tuple(resolutions), verdict, detail)


def _selector_with_version(selector: str, version_id: str) -> str:
    """把钉住版本写回选择器字符串（factor/constraints/prediction 词汇）。"""
    parsed = parse_evidence_selector(selector)
    if parsed.kind.value in ("factor", "prediction"):
        return f"{parsed.kind.value}:{parsed.ref_id}:{version_id}"
    if parsed.kind is not None and parsed.kind.value == "constraint_group":
        return f"constraints:{parsed.ref_id}:{version_id}"
    return selector


def freeze_input_set(
    input_set: CompilationInputSet,
    document: Any,
    *,
    catalog: Any = None,
    workspace_state: Any = None,
    now: str = "",
) -> CompilationInputSet:
    """冻结输入集：钉死每条可解析证据的版本；不可钉 → ValueError。

    钉法（诚实、按证据类型）：
    * RESOLVED → 解析出的 pinned_version_id；
    * FLOATING（constraints:current）→ 钉到该组最新提交版本（无提交→拒绝）；
    * STALE → 仍按其钉住版本冻结（stale 是评估层判断，不阻断 freeze）；
    * UNPINNED/MISSING/UNKNOWN → 拒绝并列出全部原因（绝不带暗洞冻结）。
    """
    if input_set.frozen:
        raise ValueError("输入集已冻结（不可重复冻结——新建输入集替代）")
    validation = validate_input_set(
        input_set, document, catalog=catalog, workspace_state=workspace_state)
    refusals: list[str] = []
    by_selector = {r.selector.raw: r for r in validation.resolutions}
    for entry in input_set.entries:
        resolution = by_selector.get(entry.selector)
        if resolution is None:
            refusals.append(f"{entry.label}：无法解析")
            continue
        if resolution.status is EvidenceStatus.FLOATING:
            pinned = _pin_floating_constraints(document, catalog)
            if pinned:
                entry.pinned_version_id = pinned
            else:
                refusals.append(
                    f"{entry.label}：constraints:current 无已提交版本——"
                    "先提交约束版本再冻结")
            continue
        if resolution.status in (EvidenceStatus.RESOLVED,
                                 EvidenceStatus.STALE):
            entry.pinned_version_id = resolution.pinned_version_id
            continue
        refusals.append(f"{entry.label}：{resolution.status.value}（{resolution.detail}）")
    if refusals:
        # 回滚本次尝试的 pin（freeze 是原子语义）。
        for entry in input_set.entries:
            entry.pinned_version_id = ""
        raise ValueError(
            "输入集冻结被拒绝——以下证据无法钉住版本："
            + "；".join(refusals))
    input_set.frozen = True
    input_set.frozen_at = now
    return input_set


def _pin_floating_constraints(document: Any, catalog: Any) -> str:
    """constraints:current → 最新提交版本 id（无目录/无提交 → ""）。"""
    if catalog is None:
        return ""
    try:
        from paleo_workbench.workflow.constraint_versions import (
            current_constraint_version,
        )

        # 逐组取最新提交；冻结钉 per-group：这里返回首个组（调用方按
        # entry 粒度钉——多组工程应使用显式 constraints:<group>:<ver> 条目）。
        for group in getattr(document, "constraint_layers", None) or []:
            latest = current_constraint_version(
                catalog, str(getattr(group, "id", "") or ""))
            if latest is not None:
                return str(getattr(latest, "id", "") or "")
    except Exception:  # noqa: BLE001 — 查询失败=不可钉
        return ""
    return ""


# ----------------------------------------------------------------- 持久化辅助


def persist_input_set(document: Any, input_set: CompilationInputSet,
                      *, active: bool = True) -> None:
    """写入 ProjectDocument.compilation_input_sets（additive dict 载体）。"""
    sets = list(getattr(document, "compilation_input_sets", None) or [])
    payload = input_set.to_dict()
    if active:
        payload["active"] = True
        sets = [dict(s, active=False) for s in sets]
    replaced = False
    for i, existing in enumerate(sets):
        if str(existing.get("id")) == input_set.id:
            sets[i] = payload
            replaced = True
            break
    if not replaced:
        sets.append(payload)
    try:
        document.compilation_input_sets = sets
    except AttributeError:
        # 旧文档对象无该字段（schema 兼容）——设置属性供保存层序列化。
        setattr(document, "compilation_input_sets", sets)


def active_input_set(document: Any) -> CompilationInputSet | None:
    """工程当前激活的输入集（无 → None；旧工程只有 legacy dict 视图）。"""
    sets = getattr(document, "compilation_input_sets", None) or []
    for payload in sets:
        if isinstance(payload, dict) and payload.get("active"):
            return CompilationInputSet.from_dict(payload)
    return None


def input_sets_for_document(document: Any) -> list[CompilationInputSet]:
    return [CompilationInputSet.from_dict(s)
            for s in (getattr(document, "compilation_input_sets", None) or [])
            if isinstance(s, dict) and s.get("id")]
