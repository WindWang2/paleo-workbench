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
    """把钉住版本写回选择器字符串（factor/prediction/constraint_group 词汇）。

    约束组钉住时重写为**组解析后的显式选择器**（freeze 已把浮动条目展开
    为 per-group pin——绝不产出 ``constraints::<ver>`` 这类不可解析形态）。
    """
    parsed = parse_evidence_selector(selector)
    if parsed.kind.value in ("factor", "prediction"):
        return f"{parsed.kind.value}:{parsed.ref_id}:{version_id}"
    if parsed.kind.value == "constraint_group" and parsed.ref_id:
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
    * RESOLVED → 解析出的 pinned_version_id，且**选择器重写为带版本的
      显式形态**（评审 R3-F2：selector 不带版本时 pin 会从 legacy 视图
      消失，融合/staleness 都看不见——冻结语义=输入不可漂移，必须可查）；
    * FLOATING（constraints:current）→ **仅当恰好一个约束组有提交**时钉到
      该组版本并把选择器重写为显式 ``constraints:<group>:<ver>``；多组有
      提交 → 拒绝（浮动引用钉住一个组=给其余组留暗洞，评审 R1-F1）；
    * STALE → 仍按其钉住版本冻结（stale 是评估层判断，不阻断 freeze）；
    * UNPINNED/MISSING/UNKNOWN → 拒绝并列出全部原因（绝不带暗洞冻结）。

    原子性（评审 R3-F4）：拒绝时回滚**全部**变更——pin 与选择器重写都
    恢复到冻结前快照，绝不留下半转换的条目。
    """
    if input_set.frozen:
        raise ValueError("输入集已冻结（不可重复冻结——新建输入集替代）")
    validation = validate_input_set(
        input_set, document, catalog=catalog, workspace_state=workspace_state)
    refusals: list[str] = []
    by_selector = {r.selector.raw: r for r in validation.resolutions}
    snapshots: list[tuple[str, str]] = [
        (entry.selector, entry.pinned_version_id) for entry in input_set.entries]
    for entry in input_set.entries:
        resolution = by_selector.get(entry.selector)
        if resolution is None:
            refusals.append(f"{entry.label}：无法解析")
            continue
        if resolution.status is EvidenceStatus.FLOATING:
            pinned = _pin_floating_constraints(document, catalog)
            if pinned is None:
                refusals.append(
                    f"{entry.label}：constraints:current 无法安全钉住——"
                    "无目录/无提交，或多个约束组各有提交（请改用显式 "
                    "constraints:<组>:<版本> 条目逐组钉住）")
                continue
            group_id, version_id = pinned
            entry.pinned_version_id = version_id
            entry.selector = f"constraints:{group_id}:{version_id}"
            continue
        if resolution.status in (EvidenceStatus.RESOLVED,
                                 EvidenceStatus.STALE):
            entry.pinned_version_id = resolution.pinned_version_id
            rewritten = _selector_with_version(
                entry.selector, resolution.pinned_version_id)
            if rewritten != entry.selector and _parses(rewritten):
                entry.selector = rewritten
            continue
        refusals.append(f"{entry.label}：{resolution.status.value}（{resolution.detail}）")
    if refusals:
        # 回滚本次尝试的全部变更：选择器重写 + pin（freeze 原子语义）。
        for entry, (selector, pinned) in zip(input_set.entries, snapshots):
            entry.selector = selector
            entry.pinned_version_id = pinned
        raise ValueError(
            "输入集冻结被拒绝——以下证据无法钉住版本："
            + "；".join(refusals))
    input_set.frozen = True
    input_set.frozen_at = now
    return input_set


def _parses(selector: str) -> bool:
    try:
        parse_evidence_selector(selector)
        return True
    except ValueError:
        return False


def _pin_floating_constraints(document: Any, catalog: Any) -> tuple[str, str] | None:
    """constraints:current → (group_id, version_id)。

    仅当**恰好一个**约束组有已提交版本时返回；零组或多组 → None
    （多组时钉住任一组都会给其余组留下暗洞——评审 R1-F1/R2-F4）。
    """
    if catalog is None:
        return None
    try:
        from paleo_workbench.workflow.constraint_versions import (
            current_constraint_version,
        )

        pinned: tuple[str, str] | None = None
        for group in getattr(document, "constraint_layers", None) or []:
            latest = current_constraint_version(
                catalog, str(getattr(group, "id", "") or ""))
            if latest is None:
                continue
            if pinned is not None:
                return None  # 多组有提交：拒绝浮动钉住
            pinned = (str(getattr(group, "id", "") or ""),
                      str(getattr(latest, "id", "") or ""))
        return pinned
    except Exception:  # noqa: BLE001 — 查询失败=不可钉
        return None


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


def evidence_view(document: Any, workspace_state: Any = None) -> dict[str, str]:
    """Compilation Input Set 的**单一消费适配器**（评审 R2-F1）。

    结构化激活输入集存在 → 其 ``legacy_view()``（label → selector）；
    否则 → 工作区旧 ``compilation_input_set`` dict。fusion/staleness/
    validation 一律经本函数读证据集——两个载体不再各自为政。
    """
    input_set = active_input_set(document)
    if input_set is not None:
        view = input_set.legacy_view()
        if view:
            return view
    if workspace_state is None:
        return {}
    return {
        str(k): str(v)
        for k, v in (getattr(workspace_state, "compilation_input_set", None)
                     or {}).items()
    }


def create_input_set_shell_from_legacy(
    document: Any,
    workspace_state: Any,
    *,
    created_by: str = "",
) -> CompilationInputSet | None:
    """首次结构化时从 legacy 视图迁移创建输入集外壳（评审 R2-F9：
    迁移逻辑属于领域层，不属于 UI 模块）。"""
    try:
        import uuid

        shell = CompilationInputSet(
            id=f"ciset_{uuid.uuid4().hex[:12]}",
            name="综合编图输入集", created_by=created_by)
        for label, selector in dict(
                getattr(workspace_state, "compilation_input_set", None)
                or {}).items():
            try:
                parsed = parse_evidence_selector(str(selector))
            except ValueError:
                continue
            shell.entries.append(CompilationInputSetEntry(
                selector=parsed.raw, label=str(label),
                evidence_kind=parsed.kind.value, added_by=created_by))
        persist_input_set(document, shell)
        return shell
    except Exception:  # noqa: BLE001 — 迁移失败不阻断旧视图路径
        import logging

        logging.getLogger(__name__).debug(
            "structured input set shell migration skipped", exc_info=True)
        return None
