"""统一 Evidence 契约（V9 ADR-3）。

Evidence 是工作流中一切科学输入的统一身份：原始相图、井解释、地震解释结果、
区域地质图、预测结果、约束、既有 factor 结果。本模块把此前散落的
``draft:<layer_id>`` / ``factor:<task>:<version>`` / ``constraints:current`` /
裸版本 id 字符串词汇收敛为**类型化选择器** + **解析结果**：

* 选择器是持久化形态（字符串），语法向后兼容既有 Compilation Input Set；
* 解析 (:func:`resolve_evidence`) 给出诚实状态——resolved / floating /
  unpinned / stale / missing / unknown，**绝不猜测**；
* 显示名称绝不作为身份（goal §6）：身份 = kind + ref_id + version_id。

不引入新存储：解析读 ProjectDocument + Catalog（可选）+ workspace 状态。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EvidenceKind(str, Enum):
    """证据类型（身份的一部分，绝不只用显示名）。"""

    PHASE1_DRAFT = "phase1_draft"
    FACTOR = "factor"
    PREDICTION = "prediction"
    CONSTRAINT_GROUP = "constraint_group"
    CATALOG_VERSION = "catalog_version"


class EvidenceStatus(str, Enum):
    """证据解析状态（诚实词汇：没有证据时 UNKNOWN，不猜 RESOLVED）。"""

    RESOLVED = "resolved"      # 钉住版本在 catalog 中可解析
    FLOATING = "floating"      # constraints:current——解析到 live 内容，无 pin
    UNPINNED = "unpinned"      # 目标存在但无版本身份（诚实 UNKNOWN 语义）
    STALE = "stale"            # 解析成功但上游判定过期/被取代
    MISSING = "missing"        # 目标不存在（图层/任务/版本缺失）
    UNKNOWN = "unknown"        # 无法判定（无 catalog、从未提交等）


#: 选择器前缀 → kind（解析优先级：具体前缀在前，裸版本 id 最后兜底）。
_PREFIX_KINDS = {
    "draft:": EvidenceKind.PHASE1_DRAFT,
    "factor:": EvidenceKind.FACTOR,
    "prediction:": EvidenceKind.PREDICTION,
    "constraints:": EvidenceKind.CONSTRAINT_GROUP,
    "version:": EvidenceKind.CATALOG_VERSION,
}


@dataclass(frozen=True)
class EvidenceSelector:
    """类型化证据选择器（持久化形态为 :func:`format_evidence_selector` 字符串）。"""

    kind: EvidenceKind
    #: 身份主体：layer_id / task_id / 约束组名 / catalog version id。
    ref_id: str
    #: 钉住的 catalog 版本（""=未钉住——解析将诚实返回 UNPINNED）。
    version_id: str = ""
    #: 浮动引用（仅 constraint_group 的 ``constraints:current``）。
    floating: bool = False

    @property
    def raw(self) -> str:
        return format_evidence_selector(
            self.kind, self.ref_id, self.version_id, floating=self.floating)

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.raw


def format_evidence_selector(
    kind: EvidenceKind,
    ref_id: str,
    version_id: str = "",
    *,
    floating: bool = False,
) -> str:
    """规范字符串形态（与既有 Compilation Input Set 词汇双向兼容）。"""
    kind = EvidenceKind(kind)
    ref_id = str(ref_id or "")
    version_id = str(version_id or "")
    if kind is EvidenceKind.PHASE1_DRAFT:
        return f"draft:{ref_id}"
    if kind is EvidenceKind.FACTOR:
        return f"factor:{ref_id}:{version_id}" if version_id else f"factor:{ref_id}"
    if kind is EvidenceKind.PREDICTION:
        return (f"prediction:{ref_id}:{version_id}" if version_id
                else f"prediction:{ref_id}")
    if kind is EvidenceKind.CONSTRAINT_GROUP:
        if floating or (not ref_id and not version_id):
            return "constraints:current"
        # 评审 R1-F8：名为 "current" 的组与浮动引用撞词表——无版本时拒绝
        # （identity 不可静默翻转）；带版本的形式无歧义。
        if ref_id == "current" and not version_id:
            raise ValueError(
                "constraint group named 'current' collides with the floating "
                "constraints:current reference — pin an explicit version")
        return f"constraints:{ref_id}:{version_id}" if version_id \
            else f"constraints:{ref_id}"
    # CATALOG_VERSION：规范形态带前缀；裸 id 由 parse 兜底兼容。
    return f"version:{version_id or ref_id}"


def parse_evidence_selector(value: str) -> EvidenceSelector:
    """把持久化字符串解析为类型化选择器；无法识别 → ValueError（不静默猜）。

    兼容既有词汇：``draft:<id>``、``factor:<task>[:<ver>]``、
    ``constraints:current``、``constraints:<group>:<ver>``、裸版本 id
    （``ver_``/uuid 形态）、以及规范新词汇 ``prediction:<task>[:<ver>]`` 与
    ``version:<ver>``。
    """
    text = str(value or "").strip()
    if not text:
        raise ValueError("empty evidence selector")
    if text == "constraints:current":
        return EvidenceSelector(EvidenceKind.CONSTRAINT_GROUP, "", "", floating=True)
    for prefix, kind in _PREFIX_KINDS.items():
        if not text.startswith(prefix):
            continue
        body = text[len(prefix):]
        if kind is EvidenceKind.PHASE1_DRAFT:
            if not body:
                raise ValueError(f"draft selector missing layer id: {text!r}")
            return EvidenceSelector(kind, body)
        if kind is EvidenceKind.CATALOG_VERSION:
            if not body:
                raise ValueError(f"version selector missing version id: {text!r}")
            return EvidenceSelector(kind, body, body)
        parts = [part for part in body.split(":")]
        if not parts or not parts[0]:
            raise ValueError(f"malformed evidence selector: {text!r}")
        if len(parts) == 1:
            return EvidenceSelector(kind, parts[0])
        if len(parts) == 2 and parts[1]:
            return EvidenceSelector(kind, parts[0], parts[1])
        raise ValueError(f"malformed evidence selector: {text!r}")
    if _looks_like_version_id(text):
        return EvidenceSelector(EvidenceKind.CATALOG_VERSION, text)
    raise ValueError(f"unrecognized evidence selector: {text!r}")


def _looks_like_version_id(value: str) -> bool:
    """与 mapping_workspace.dependencies._looks_like_version_id 同判据。"""
    text = str(value or "")
    return text.startswith(("ver_", "dver_")) or (
        len(text) >= 32 and "-" in text and not text.startswith("sha:")
    )


@dataclass(frozen=True)
class EvidenceResolution:
    """一次证据解析的诚实结果。"""

    selector: EvidenceSelector
    status: EvidenceStatus
    #: 解析到的 catalog 版本（RESOLVED/STALE 时非空）。
    pinned_version_id: str = ""
    asset_id: str = ""
    #: 展示名（仅展示；身份在 selector）。
    display: str = ""
    detail: str = ""
    #: 已知的质量/置信元数据（缺省空——不知道就是不知道）。
    quality: dict[str, Any] = field(default_factory=dict)

    @property
    def is_usable(self) -> bool:
        """能否作为科学输入（RESOLVED/FLOATING/STALE 可选；缺失/未知不可）。"""
        return self.status in (
            EvidenceStatus.RESOLVED,
            EvidenceStatus.FLOATING,
            EvidenceStatus.STALE,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "selector": self.selector.raw,
            "kind": self.selector.kind.value,
            "ref_id": self.selector.ref_id,
            "version_id": self.selector.version_id,
            "status": self.status.value,
            "pinned_version_id": self.pinned_version_id,
            "asset_id": self.asset_id,
            "display": self.display,
            "detail": self.detail,
            "quality": dict(self.quality),
        }


# --------------------------------------------------------------------- 解析


def _resolve_version(catalog: Any, version_id: str) -> Any | None:
    if catalog is None or not version_id:
        return None
    try:
        return catalog.resolve_version(version_id)
    except Exception:  # noqa: BLE001 — 解析失败诚实返回 None
        return None


def _resolve_draft(document: Any, selector: EvidenceSelector,
                   workspace_state: Any, catalog: Any = None) -> EvidenceResolution:
    layer_id = selector.ref_id
    display = layer_id
    # 展示名尽力而为：live 文档里的图层名；身份始终是 layer_id。
    for layer in getattr(document, "user_vector_layers", None) or []:
        if str(getattr(layer, "id", "")) == layer_id:
            display = str(getattr(layer, "name", "") or layer_id)
            break
    membership = None
    if workspace_state is not None:
        membership = workspace_state.membership(layer_id)
    if membership is None:
        return EvidenceResolution(
            selector, EvidenceStatus.MISSING, display=display,
            detail=f"草稿图层无工作区成员资格：{layer_id}")
    pinned = str(getattr(membership, "source_version_id", "") or "")
    if not pinned:
        return EvidenceResolution(
            selector, EvidenceStatus.UNPINNED, display=display,
            detail="草稿未钉住 RAW 源版本（旧工程或未走 checkout）")
    info = _resolve_version(catalog, pinned)
    if info is None:
        if catalog is None:
            return EvidenceResolution(
                selector, EvidenceStatus.UNKNOWN, display=display,
                detail="无目录服务，无法验证钉住的 RAW 版本",
                quality={"identity": "content_fingerprint"})
        return EvidenceResolution(
            selector, EvidenceStatus.MISSING, display=display,
            pinned_version_id=pinned,
            detail=f"钉住的 RAW 版本不可解析：{pinned}",
            quality={"identity": "content_fingerprint"})
    return EvidenceResolution(
        selector, EvidenceStatus.RESOLVED, display=display,
        pinned_version_id=pinned,
        asset_id=str(getattr(info, "asset_id", "") or ""),
        detail="草稿（几何为内容指纹身份，输入 RAW 版本已钉住）",
        quality={"identity": "content_fingerprint"})


def _resolve_factor(document: Any, selector: EvidenceSelector,
                    catalog: Any) -> EvidenceResolution:
    task = None
    for candidate in getattr(document, "factor_map_tasks", None) or []:
        if str(candidate.id) == selector.ref_id:
            task = candidate
            break
    if task is None:
        return EvidenceResolution(
            selector, EvidenceStatus.MISSING,
            display=selector.ref_id, detail=f"单因素任务不存在：{selector.ref_id}")
    display = str(getattr(task, "name", "") or selector.ref_id)
    version_id = selector.version_id or str(
        getattr(task, "grid_artifact_version_id", "") or "")
    if not version_id:
        return EvidenceResolution(
            selector, EvidenceStatus.UNPINNED, display=display,
            detail="插值结果尚未登记版本（保存后登记）")
    info = _resolve_version(catalog, version_id)
    if info is None:
        if catalog is None:
            return EvidenceResolution(
                selector, EvidenceStatus.UNKNOWN, display=display,
                detail="无目录服务，无法验证版本")
        return EvidenceResolution(
            selector, EvidenceStatus.MISSING, display=display,
            pinned_version_id=version_id,
            detail=f"钉住版本不可解析：{version_id}")
    # 评审 R3-F6：pin 仍可解析但任务当前结果版本已前移 → STALE（与约束
    # supersession 同语义；此前恒 RESOLVED 掩盖了取代）。
    current_version = str(getattr(task, "grid_artifact_version_id", "") or "")
    if current_version and current_version != version_id:
        return EvidenceResolution(
            selector, EvidenceStatus.STALE, display=display,
            pinned_version_id=version_id,
            asset_id=str(getattr(info, "asset_id", "") or ""),
            detail=f"钉住 {version_id}，任务当前结果版本为 {current_version}")
    quality = {}
    metrics = getattr(task, "quality_metrics", None) or {}
    for key in ("r2", "n_points", "variance_min", "variance_max"):
        if key in metrics:
            quality[key] = metrics[key]
    if str(getattr(task, "source_kind", "")) in ("mock", "mixed"):
        quality["mock_data"] = True
    return EvidenceResolution(
        selector, EvidenceStatus.RESOLVED, display=display,
        pinned_version_id=version_id,
        asset_id=str(getattr(info, "asset_id", "") or ""),
        quality=quality)


def _resolve_prediction(document: Any, selector: EvidenceSelector,
                        catalog: Any) -> EvidenceResolution:
    task = None
    for candidate in getattr(document, "prediction_tasks", None) or []:
        if str(candidate.id) == selector.ref_id:
            task = candidate
            break
    if task is None:
        return EvidenceResolution(
            selector, EvidenceStatus.MISSING,
            display=selector.ref_id, detail=f"预测任务不存在：{selector.ref_id}")
    display = str(getattr(task, "name", "") or selector.ref_id)
    status = str(getattr(task, "status", "") or "")
    if status and status not in ("complete", "completed", "done"):
        return EvidenceResolution(
            selector, EvidenceStatus.MISSING, display=display,
            detail=f"预测任务未完成（status={status}）")
    quality: dict[str, Any] = {}
    if str(getattr(task, "adapter_kind", "")) == "mock":
        quality["mock_data"] = True
    summary = getattr(task, "probability_summary", None) or {}
    if isinstance(summary, dict):
        for key in ("classes", "mean_confidence"):
            if key in summary:
                quality[key] = summary[key]
    version_id = selector.version_id
    if not version_id:
        # 预测结果通常只登记 DataRun（result_summary 载荷，无文件版本）——
        # 诚实 UNPINNED，绝不伪称 RESOLVED。
        return EvidenceResolution(
            selector, EvidenceStatus.UNPINNED, display=display,
            detail="预测结果为 run 级溯源（无文件版本可钉）", quality=quality)
    info = _resolve_version(catalog, version_id)
    if info is None:
        return EvidenceResolution(
            selector, EvidenceStatus.MISSING, display=display,
            pinned_version_id=version_id,
            detail=f"钉住版本不可解析：{version_id}", quality=quality)
    return EvidenceResolution(
        selector, EvidenceStatus.RESOLVED, display=display,
        pinned_version_id=version_id,
        asset_id=str(getattr(info, "asset_id", "") or ""),
        quality=quality)


def _resolve_constraint_group(document: Any, selector: EvidenceSelector,
                              catalog: Any) -> EvidenceResolution:
    from paleo_workbench.workflow.constraint_versions import resolve_constraint_ref

    if selector.floating:
        try:
            verdict = resolve_constraint_ref(document, catalog, "constraints:current")
        except Exception as exc:  # noqa: BLE001 — 解析失败=UNKNOWN，不猜
            return EvidenceResolution(
                selector, EvidenceStatus.UNKNOWN,
                display="地质约束（当前内容）", detail=f"约束解析失败：{exc}")
        status_map = {
            "clean": EvidenceStatus.FLOATING,
            "current": EvidenceStatus.FLOATING,
            "stale": EvidenceStatus.STALE,
            "superseded": EvidenceStatus.STALE,
            "unknown": EvidenceStatus.UNKNOWN,
        }
        return EvidenceResolution(
            selector,
            status_map.get(str(verdict.get("status", "")), EvidenceStatus.UNKNOWN),
            display="地质约束（当前内容）",
            detail=str(verdict.get("detail", "") or ""))
    raw = (f"constraints:{selector.ref_id}:{selector.version_id}"
           if selector.version_id else f"constraints:{selector.ref_id}")
    try:
        verdict = resolve_constraint_ref(document, catalog, raw)
    except Exception as exc:  # noqa: BLE001
        return EvidenceResolution(
            selector, EvidenceStatus.UNKNOWN, display=selector.ref_id,
            detail=f"约束解析失败：{exc}")
    status_text = str(verdict.get("status", ""))
    if status_text in ("missing",):
        return EvidenceResolution(
            selector, EvidenceStatus.MISSING, display=selector.ref_id,
            pinned_version_id=selector.version_id,
            detail=str(verdict.get("detail", "") or ""))
    status = {
        "clean": EvidenceStatus.RESOLVED,
        "current": EvidenceStatus.RESOLVED,
        "stale": EvidenceStatus.STALE,
        "superseded": EvidenceStatus.STALE,
        "unknown": EvidenceStatus.UNKNOWN,
    }.get(status_text, EvidenceStatus.UNKNOWN)
    return EvidenceResolution(
        selector, status, display=selector.ref_id,
        pinned_version_id=selector.version_id if status != EvidenceStatus.UNKNOWN else "",
        detail=str(verdict.get("detail", "") or ""))


def _resolve_catalog_version(selector: EvidenceSelector,
                             catalog: Any) -> EvidenceResolution:
    version_id = selector.version_id or selector.ref_id
    info = _resolve_version(catalog, version_id)
    if info is None:
        if catalog is None:
            return EvidenceResolution(
                selector, EvidenceStatus.UNKNOWN,
                detail="无目录服务，无法验证版本")
        return EvidenceResolution(
            selector, EvidenceStatus.MISSING, pinned_version_id=version_id,
            detail=f"版本不可解析：{version_id}")
    return EvidenceResolution(
        selector, EvidenceStatus.RESOLVED, pinned_version_id=version_id,
        asset_id=str(getattr(info, "asset_id", "") or ""),
        detail=str(getattr(info, "name", "") or ""))


def resolve_evidence(
    document: Any,
    value: str | EvidenceSelector,
    *,
    catalog: Any = None,
    workspace_state: Any = None,
) -> EvidenceResolution:
    """把证据选择器解析为诚实结果（绝不猜测，goal §36）。"""
    selector = value if isinstance(value, EvidenceSelector) \
        else parse_evidence_selector(value)
    if selector.kind is EvidenceKind.PHASE1_DRAFT:
        return _resolve_draft(document, selector, workspace_state, catalog)
    if selector.kind is EvidenceKind.FACTOR:
        return _resolve_factor(document, selector, catalog)
    if selector.kind is EvidenceKind.PREDICTION:
        return _resolve_prediction(document, selector, catalog)
    if selector.kind is EvidenceKind.CONSTRAINT_GROUP:
        return _resolve_constraint_group(document, selector, catalog)
    return _resolve_catalog_version(selector, catalog)


# ----------------------------------------------------------------- 可选清单


def available_evidence(
    document: Any,
    workspace_state: Any = None,
) -> list[EvidenceResolution]:
    """列出当前可选证据（供选择对话框 / create_input_set 动作）。

    只列**存在**的目标；状态诚实（UNPINNED/… 不隐瞒）。不包含已删除图层。
    """
    out: list[EvidenceResolution] = []
    if document is None:
        return out
    if workspace_state is not None:
        from paleo_workbench.mapping_workspace.layer_roles import LayerRole

        for layer_id in workspace_state.layers_with_role(
                LayerRole.INITIAL_FACIES_DRAFT):
            out.append(resolve_evidence(
                document, f"draft:{layer_id}",
                workspace_state=workspace_state))
    for task in getattr(document, "factor_map_tasks", None) or []:
        if str(getattr(task, "status", "")) != "complete":
            continue
        version = str(getattr(task, "grid_artifact_version_id", "") or "")
        out.append(resolve_evidence(
            document, f"factor:{task.id}:{version}".rstrip(":")))
    for task in getattr(document, "prediction_tasks", None) or []:
        if str(getattr(task, "status", "")) not in ("complete", "completed", "done"):
            continue
        out.append(resolve_evidence(document, f"prediction:{task.id}"))
    if getattr(document, "constraint_layers", None):
        out.append(resolve_evidence(document, "constraints:current"))
    return out
