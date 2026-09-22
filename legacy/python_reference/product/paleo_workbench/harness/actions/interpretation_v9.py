"""V9 Geological Interpretation Workbench harness actions.

补齐 goal §26 要求的科学动作（thin wrapper over the V9 domain spine —
无新科学，全部委托 workflow.interpretation.* 与 workflow.map_product）：

* ``compilation.create_input_set`` / ``compilation.freeze_input_set``
* ``interpretation.commit`` / ``interpretation.compare``
* ``map_product.assemble`` / ``map_product.review`` / ``map_product.publish``

WRITE 动作带 verifier；不支持/缺前置 → 诚实 ``error`` payload，绝不伪造。
"""
from __future__ import annotations

from typing import Any

from paleo_workbench.harness.context import ActionContext
from paleo_workbench.harness.spec import ActionRisk, ActionSpec


def register(registry) -> None:
    # ---- compilation.* ----------------------------------------------------
    registry.register(
        ActionSpec(
            action_id="compilation.create_input_set",
            description=(
                "从证据选择器列表创建综合编图输入集（CompilationInputSet，"
                "每条记录加入时的诚实解析快照；随后可 freeze 钉死版本）。"
            ),
            handler=_compilation_create_input_set,
            risk=ActionRisk.WRITE,
            side_effect_notes="appends a CompilationInputSet record to ProjectDocument.compilation_input_sets",
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.5, "io_weight": 0.2},
            required_context=("project",),
            version="1.0",
            deterministic=True,
            domain_tags=("compilation", "evidence", "scientific"),
            input_schema={
                "type": "object",
                "properties": {
                    "selectors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "证据选择器（draft:/factor:/prediction:/"
                            "constraints:/version: 词汇）"),
                    },
                    "name": {"type": "string"},
                },
                "required": ["selectors"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "input_set_id": {"type": ["string", "null"]},
                    "entries": {"type": "array"},
                    "error": {"type": ["string", "null"]},
                },
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="compilation.freeze_input_set",
            description=(
                "冻结输入集：钉死每条可解析证据的 catalog 版本；不可钉条目"
                "（缺失/未知/未提交约束）原子拒绝并列出原因。"
            ),
            handler=_compilation_freeze_input_set,
            risk=ActionRisk.WRITE,
            side_effect_notes="pins catalog version ids on the input set entries (document record)",
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.5, "io_weight": 0.2},
            required_context=("project",),
            version="1.0",
            deterministic=True,
            domain_tags=("compilation", "evidence", "scientific"),
            input_schema={
                "type": "object",
                "properties": {
                    "input_set_id": {"type": "string"},
                },
                "required": ["input_set_id"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "input_set_id": {"type": ["string", "null"]},
                    "frozen": {"type": "boolean"},
                    "error": {"type": ["string", "null"]},
                },
            },
        )
    )
    # ---- interpretation.* --------------------------------------------------
    registry.register(
        ActionSpec(
            action_id="interpretation.commit",
            description=(
                "提交综合解释：编辑层几何 → catalog DERIVED 版本 + "
                "integrated_interpretation DataRun + InterpretationRevision。"
            ),
            handler=_interpretation_commit,
            verifier=_verify_interpretation_commit,
            risk=ActionRisk.WRITE,
            side_effect_notes="registers a DERIVED catalog version + DataRun + InterpretationRevision",
            category="background.compute",
            resource_profile={"estimated_cpu_cores": 1.0, "io_weight": 0.8},
            required_context=("project", "catalog"),
            version="1.0",
            deterministic=True,
            domain_tags=("interpretation", "provenance", "scientific"),
            input_schema={
                "type": "object",
                "properties": {
                    "layer_id": {"type": "string", "description": "解释层 id"},
                    "actor": {"type": "string"},
                    "evidence_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "本修订依据的证据选择器",
                    },
                },
                "required": ["layer_id"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "version_id": {"type": ["string", "null"]},
                    "revision_id": {"type": ["string", "null"]},
                    "error": {"type": ["string", "null"]},
                },
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="interpretation.compare",
            description=(
                "比较解释层两个修订（内容指纹/要素与顶点 delta/base 证据归因）。"
            ),
            handler=_interpretation_compare,
            risk=ActionRisk.READ,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.5, "io_weight": 0.2},
            required_context=("project",),
            version="1.0",
            deterministic=True,
            domain_tags=("interpretation", "compare", "scientific"),
            input_schema={
                "type": "object",
                "properties": {
                    "layer_id": {"type": "string"},
                },
                "required": ["layer_id"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "layer_id": {"type": "string"},
                    "revisions": {"type": ["array", "null"]},
                },
            },
        )
    )
    # ---- map_product.* ------------------------------------------------------
    registry.register(
        ActionSpec(
            action_id="map_product.assemble",
            description=(
                "组装 MapProduct（复用 workflow.map_product 组装器；V9 增补 "
                "fusion/integrated/input_set 引用进入配方与指纹）。"
            ),
            handler=_map_product_assemble,
            verifier=_verify_map_product_assemble,
            risk=ActionRisk.WRITE,
            side_effect_notes="appends a MapProductRecord + registers catalog OUTPUT version + run",
            category="background.compute",
            resource_profile={"estimated_cpu_cores": 1.0, "io_weight": 0.8},
            required_context=("project", "catalog"),
            version="1.0",
            deterministic=True,
            domain_tags=("map_product", "compilation", "scientific"),
            input_schema={
                "type": "object",
                "properties": {
                    "product_name": {"type": "string"},
                    "factor_task_ids": {
                        "type": "array", "items": {"type": "string"}},
                    "interpretation_refs": {
                        "type": "array", "items": {"type": "string"}},
                    "composition_ref": {"type": ["string", "null"]},
                    "input_set_id": {"type": "string"},
                },
                "required": ["product_name", "factor_task_ids"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "record_id": {"type": ["string", "null"]},
                    "output_version_id": {"type": ["string", "null"]},
                    "run_id": {"type": ["string", "null"]},
                    "error": {"type": ["string", "null"]},
                },
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="map_product.review",
            description=(
                "产品评审（draft → reviewed）：运行产品级 QA（severity 分级），"
                "含 ERROR/BLOCKER 时拒绝。"
            ),
            handler=_map_product_review,
            verifier=_verify_map_product_review,
            risk=ActionRisk.WRITE,
            side_effect_notes="runs product-level QA and advances record lifecycle draft->reviewed",
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.5, "io_weight": 0.3},
            required_context=("project",),
            version="1.0",
            deterministic=True,
            domain_tags=("map_product", "qa", "scientific"),
            input_schema={
                "type": "object",
                "properties": {
                    "product": {"type": "string", "description": "产品 id 或名称"},
                },
                "required": ["product"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "product": {"type": ["string", "null"]},
                    "lifecycle": {"type": ["string", "null"]},
                    "qa": {"type": "object"},
                    "error": {"type": ["string", "null"]},
                },
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="map_product.publish",
            description=(
                "发布产品（goal §31 阶梯：仅 FROZEN 可发布；BLOCKER 一票否决；"
                "成功后 lifecycle=published 不可再隐式修改）。"
            ),
            handler=_map_product_publish,
            verifier=_verify_map_product_publish,
            risk=ActionRisk.WRITE,
            side_effect_notes="runs the publish gate and advances record lifecycle frozen->published",
            category="background.compute",
            resource_profile={"estimated_cpu_cores": 1.0, "io_weight": 0.8},
            required_context=("project", "catalog"),
            version="1.0",
            deterministic=True,
            domain_tags=("map_product", "publish", "scientific"),
            input_schema={
                "type": "object",
                "properties": {
                    "product": {"type": "string"},
                    "accept_warnings": {"type": "boolean"},
                },
                "required": ["product"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "product": {"type": ["string", "null"]},
                    "lifecycle": {"type": ["string", "null"]},
                    "ok": {"type": "boolean"},
                    "error": {"type": ["string", "null"]},
                },
            },
        )
    )


# --------------------------------------------------------------------- 实现


def _workspace_state(context: ActionContext):
    state = (context.extras or {}).get("mapping_workspace_state")
    if state is None:
        controller = (context.extras or {}).get("stage_controller")
        state = getattr(controller, "state", None) if controller else None
    return state


def _catalog_service(context: ActionContext):
    catalog = getattr(context, "catalog", None)
    if catalog is None:
        return None
    return getattr(catalog, "service", catalog)


def _compilation_create_input_set(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.workflow.interpretation.compilation import (
        create_input_set,
        persist_input_set,
    )

    try:
        input_set = create_input_set(
            context.project,
            [str(s) for s in (parameters.get("selectors") or [])],
            name=str(parameters.get("name") or ""),
            created_by="harness",
            catalog=_catalog_service(context),
            workspace_state=_workspace_state(context),
        )
    except ValueError as exc:
        return {"input_set_id": None, "entries": [], "error": str(exc)}
    persist_input_set(context.project, input_set)
    return {
        "input_set_id": input_set.id,
        "entries": [entry.to_dict() for entry in input_set.entries],
        "error": None,
    }


def _compilation_freeze_input_set(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.workflow.interpretation.compilation import (
        freeze_input_set,
        input_sets_for_document,
    )

    target_id = str(parameters.get("input_set_id") or "")
    input_set = next(
        (s for s in input_sets_for_document(context.project) if s.id == target_id),
        None)
    if input_set is None:
        return {"input_set_id": target_id, "frozen": False,
                "error": f"输入集不存在：{target_id}"}
    try:
        freeze_input_set(
            input_set, context.project,
            catalog=_catalog_service(context),
            workspace_state=_workspace_state(context))
    except ValueError as exc:
        return {"input_set_id": target_id, "frozen": False, "error": str(exc)}
    from paleo_workbench.workflow.interpretation.compilation import (
        persist_input_set,
    )

    persist_input_set(context.project, input_set)
    return {"input_set_id": target_id, "frozen": True, "error": None}


def _interpretation_commit(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.workflow.interpretation.integrated_interpretation import (
        commit_integrated_interpretation,
        find_by_layer,
    )

    document = context.project
    layer_id = str(parameters.get("layer_id") or "")
    interpretation = find_by_layer(document, layer_id)
    if interpretation is None:
        return {"version_id": None, "revision_id": None,
                "error": f"层 {layer_id} 没有综合解释记录（先创建）"}
    layer = next(
        (l for l in getattr(document, "user_vector_layers", None) or []
         if str(l.id) == layer_id), None)
    if layer is None:
        return {"version_id": None, "revision_id": None,
                "error": f"层 {layer_id} 不在工程文档中"}
    catalog = _catalog_service(context)
    if catalog is None:
        return {"version_id": None, "revision_id": None,
                "error": "unavailable: catalog 服务不可用"}
    try:
        version_id = commit_integrated_interpretation(
            document, interpretation, layer, catalog,
            actor=str(parameters.get("actor") or "harness"),
            evidence_refs=[str(r) for r in (parameters.get("evidence_refs") or [])],
        )
    except ValueError as exc:
        return {"version_id": None, "revision_id": None, "error": str(exc)}
    return {
        "version_id": version_id,
        "revision_id": interpretation.revision_ids[-1]
        if interpretation.revision_ids else None,
        "error": None,
    }


def _verify_interpretation_commit(payload, parameters, context) -> dict:
    if payload.get("error"):
        return {"verdict": "fail", "reasons": [str(payload.get("error"))]}
    version_id = str(payload.get("version_id") or "")
    if not version_id:
        return {"verdict": "fail", "reasons": ["no version id in payload"]}
    catalog = _catalog_service(context)
    if catalog is None:
        return {"verdict": "fail", "reasons": ["catalog unavailable at verify"]}
    try:
        resolved = catalog.resolve_version(version_id)
    except Exception as exc:  # noqa: BLE001
        return {"verdict": "fail", "reasons": [f"resolve failed: {exc}"]}
    if resolved is None:
        return {"verdict": "fail",
                "reasons": [f"claimed version {version_id} does not resolve"]}
    return {"verdict": "pass", "reasons": []}


def _interpretation_compare(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.workflow.interpretation.revision import (
        revisions_for_layer,
    )

    chain = revisions_for_layer(context.project, str(parameters.get("layer_id") or ""))
    return {
        "layer_id": str(parameters.get("layer_id") or ""),
        "revisions": [revision.to_dict() for revision in chain],
    }


def _map_product_assemble(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.workflow.map_product import (
        MapProductAssembly,
        assemble_map_product,
        assembly_from_workspace,
        write_product_manifest,
    )

    catalog = _catalog_service(context)
    if catalog is None:
        return {"record_id": None, "output_version_id": None, "run_id": None,
                "error": "unavailable: catalog 服务不可用"}
    staged_path = None
    try:
        staged_path = write_product_manifest(
            context.project,
            product_name=str(parameters.get("product_name") or "综合编图"),
            factor_task_ids=[str(t) for t in (parameters.get("factor_task_ids") or [])],
        )
        # V9（评审 R2-F3）：共享构造器打底（补齐 fusion/integrated 引用），
        # 显式参数覆盖。
        base = assembly_from_workspace(
            context.project,
            product_name=str(parameters.get("product_name") or "综合编图"),
            workspace_state=_workspace_state(context),
        )
        assembly = MapProductAssembly(
            product_name=base.product_name,
            factor_task_ids=[str(t) for t in
                             (parameters.get("factor_task_ids")
                              or base.factor_task_ids)],
            interpretation_refs=[str(r) for r in
                                 (parameters.get("interpretation_refs")
                                  or base.interpretation_refs)],
            composition_ref=parameters.get("composition_ref")
            or base.composition_ref,
            fusion_version_id=base.fusion_version_id,
            integrated_interpretation_id=base.integrated_interpretation_id,
            input_set_id=str(parameters.get("input_set_id") or base.input_set_id),
        )
        result = assemble_map_product(
            context.project, assembly=assembly, catalog=catalog,
            payload_path=staged_path)
    except ValueError as exc:
        return {"record_id": None, "output_version_id": None, "run_id": None,
                "error": str(exc)}
    finally:
        if staged_path is not None:
            try:
                staged_path.unlink(missing_ok=True)
            except OSError:
                pass
    return {
        "record_id": result.record_id,
        "output_version_id": result.output_version_id,
        "run_id": result.run_id,
        "error": None,
    }


def _verify_map_product_assemble(payload, parameters, context) -> dict:
    if payload.get("error"):
        return {"verdict": "fail", "reasons": [str(payload.get("error"))]}
    record_id = str(payload.get("record_id") or "")
    output_version = str(payload.get("output_version_id") or "")
    run_id = str(payload.get("run_id") or "")
    if not (record_id and output_version and run_id):
        return {"verdict": "fail",
                "reasons": ["success payload must carry record+version+run"]}
    catalog = _catalog_service(context)
    if catalog is None:
        return {"verdict": "fail", "reasons": ["catalog unavailable at verify"]}
    try:
        resolved = catalog.resolve_version(output_version)
        run = catalog.get_run(run_id)
    except Exception as exc:  # noqa: BLE001
        return {"verdict": "fail", "reasons": [f"resolve failed: {exc}"]}
    if resolved is None:
        return {"verdict": "fail",
                "reasons": [f"output version {output_version} does not resolve"]}
    if run is None or str(run.status) != "complete":
        return {"verdict": "fail",
                "reasons": [f"run {run_id} missing or incomplete"]}
    return {"verdict": "pass", "reasons": []}


def _verify_map_product_review(payload, parameters, context) -> dict:
    if payload.get("error"):
        return {"verdict": "fail", "reasons": [str(payload.get("error"))]}
    record = _find_product(context, str(payload.get("product") or ""))
    if record is None:
        return {"verdict": "fail", "reasons": ["record vanished"]}
    if str(getattr(record, "lifecycle", "")) != "reviewed":
        return {
            "verdict": "fail",
            "reasons": [
                f"lifecycle={getattr(record, 'lifecycle', '')}, expected reviewed"],
        }
    if not getattr(record, "product_qa", None):
        return {"verdict": "fail", "reasons": ["no product_qa recorded"]}
    return {"verdict": "pass", "reasons": []}


def _verify_map_product_publish(payload, parameters, context) -> dict:
    if payload.get("error"):
        return {"verdict": "fail", "reasons": [str(payload.get("error"))]}
    record = _find_product(context, str(payload.get("product") or ""))
    if record is None:
        return {"verdict": "fail", "reasons": ["record vanished"]}
    if str(getattr(record, "lifecycle", "")) != "published":
        return {
            "verdict": "fail",
            "reasons": [
                f"lifecycle={getattr(record, 'lifecycle', '')}, expected published"],
        }
    return {"verdict": "pass", "reasons": []}


def _find_product(context: ActionContext, ref: str):
    from paleo_workbench.workflow.map_product import find_map_product

    record = find_map_product(context.project, ref)
    if record is not None:
        return record
    # 名称回退（id 优先；名称匹配唯一时才接受，歧义=找不到）。
    matches = [
        r for r in (getattr(context.project, "map_products", None) or [])
        if str(getattr(r, "product_name", "") or "") == str(ref)
    ]
    return matches[0] if len(matches) == 1 else None


def _map_product_review(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.workflow.map_product import (
        effective_lifecycle,
        review_map_product,
    )

    record = _find_product(context, str(parameters.get("product") or ""))
    if record is None:
        return {"product": str(parameters.get("product")), "lifecycle": None,
                "qa": {}, "error": "not_found: 产品不存在"}
    try:
        report = review_map_product(
            record, context.project,
            catalog=_catalog_service(context),
            workspace_state=_workspace_state(context))
    except ValueError as exc:
        return {"product": record.id,
                "lifecycle": effective_lifecycle(record),
                "qa": record.product_qa or {}, "error": str(exc)}
    return {"product": record.id, "lifecycle": effective_lifecycle(record),
            "qa": report, "error": None}


def _map_product_publish(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.workflow.map_product import (
        effective_lifecycle,
        publish_map_product,
    )

    record = _find_product(context, str(parameters.get("product") or ""))
    if record is None:
        return {"product": str(parameters.get("product")), "lifecycle": None,
                "ok": False, "error": "not_found: 产品不存在"}
    accept = bool(parameters.get("accept_warnings", True))
    try:
        report = publish_map_product(
            record, context.project,
            accept_warnings=accept,
            catalog=_catalog_service(context),
            workspace_state=_workspace_state(context))
    except ValueError as exc:
        return {"product": record.id,
                "lifecycle": effective_lifecycle(record),
                "ok": False, "error": str(exc)}
    return {"product": record.id,
            "lifecycle": effective_lifecycle(record),
            "ok": bool(report.get("ok")), "error": None}
