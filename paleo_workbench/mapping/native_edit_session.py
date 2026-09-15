"""原生编辑会话控制器（拓扑编辑迁移 M1 §2/§3）。

编辑权迁移 QGIS 后宿主是**同步方**：镜像层经桥 ``startEditing()`` 进入
原生编辑缓冲，顶点工具直接编辑镜像；Python 真源（user_vector_layers）
只在提交后消费 committed\\* 增量对齐（``VectorLayer.apply_committed_delta``）。
编辑期间 Python 不动——未提交编辑即崩溃即丢（易失会话，无 sidecar）。

三段门禁的落点：
- 进前段：``open`` 的 ``gate``（角色/成熟度/组锁——宿主单点
  ``_role_allows_editing``）+ M0 的 CRS 进前门（composite_document）；
  拒绝则**不** ``startEditing()``。
- 编辑中：无防御（原生缓冲自由操作）。
- 提交前段：``commit_all`` 全集合判定（gate 复查 + 拓扑零错误——几何
  从镜像**读回**校验，编辑缓冲即事实）；拒绝则全集合保持会话。

保存 = 整集合全或无（§3）：全过逐层 commit → 逐层写回 → 逐层台账对齐
（M0 ``align_publish_ledger``——commit 后无需重发）→ 关停发窗口。

纯逻辑模块（duck-typed stack，无 Qt）：真桥面由 canvas_shim 注入回调。
"""
from __future__ import annotations

import json
import logging
import uuid

from paleo_workbench.mapping.edit_gesture_manager import EditGestureManager
from paleo_workbench.mapping.edit_session_set import SESSION_SET
from paleo_workbench.mapping.geometry_schema import new_feature_id

__all__ = ["NativeEditSessionController"]

logger = logging.getLogger(__name__)


class NativeEditSessionController:
    """原生编辑会话的宿主侧生命周期（一个工作台一个实例）。"""

    def __init__(self) -> None:
        # layer_id → {"stack", "layer"}（会话集合的宿主侧视图）。
        self._sessions: dict[str, dict] = {}
        # doc_id → 提交时桥回传的 committed 增量（同步回调收集）。
        self._pending_commits: dict[str, dict] = {}
        # geotopo Ticket 5：补偿恢复事件（层 id，诊断/审计通道）。
        self._compensations: list[str] = []
        self.gestures = EditGestureManager()

    # -- 能力与状态 ---------------------------------------------------------

    @staticmethod
    def bridge_supports(stack) -> bool:
        """桥具备 M1 原生编辑面（能力探测；旧桥诚实降级）。"""
        return (
            callable(getattr(stack, "start_mirror_layer_editing", None))
            and callable(getattr(stack, "commit_mirror_layer", None))
            and callable(getattr(stack, "roll_back_mirror_layer", None))
            and callable(getattr(stack, "mirror_features_json", None))
        )

    def is_open(self, layer_id: str) -> bool:
        return str(layer_id) in self._sessions

    def session_layer_ids(self) -> tuple[str, ...]:
        return tuple(self._sessions)

    def stack_for(self, layer_id: str):
        session = self._sessions.get(str(layer_id))
        return session["stack"] if session is not None else None

    # -- 生命周期 -----------------------------------------------------------

    def open(self, stack, layer, *, gate, canvas_address=0) -> tuple[bool, str]:
        """进入原生编辑会话（§2 三段式第 1 段之后的桥侧起点）。

        ``gate(layer.id) -> (allowed, reason)``——进前段角色门禁（宿主
        单点）；拒绝则不 startEditing（RAW/成熟度/组锁在源头挡住）。
        """
        layer_id = str(layer.id)
        if layer_id in self._sessions:
            return True, ""
        if gate is not None:
            allowed, reason = gate(layer_id)
            if not allowed:
                return False, str(reason or "门禁拒绝")
        if not self.bridge_supports(stack):
            return False, "当前 QGIS 桥不支持原生编辑（需重建桥扩展）"
        # §3 集合按需生长：已有会话集合时，新层经门禁复查**入集**而非替换
        # （替换会把既有层踢出停发窗口，但其宿主会话仍在——状态分叉）。
        if SESSION_SET.is_open:
            if SESSION_SET.active_layer_ids(stack) and SESSION_SET.frozen_crs != str(
                    getattr(layer, "crs", "") or SESSION_SET.frozen_crs):
                # 同一会话集合需同 CRS（§6）；失配层不参与并提示。
                return False, (
                    f"图层「{getattr(layer, 'name', layer_id)}」CRS 与编辑"
                    "会话不一致——该图层不参与本次会话")
        # committed 回调直连（canvas_shim 存在时同一路径，见 handle_committed）。
        setter = getattr(stack, "set_committed_callback", None)
        if callable(setter):
            try:
                setter(canvas_address, self.handle_committed)
            except Exception:
                logger.debug("set_committed_callback unavailable", exc_info=True)
        try:
            error = str(stack.start_mirror_layer_editing(layer_id) or "")
        except Exception as exc:
            return False, f"镜像层进入编辑失败：{exc}"
        if error:
            return False, f"镜像层进入编辑失败：{error}"
        self._sessions[layer_id] = {
            "stack": stack, "layer": layer, "canvas": canvas_address,
        }
        if SESSION_SET.is_open:
            SESSION_SET.request_join([layer_id])  # 门禁已过 → 入集生长
        else:
            # M0 §3 停发窗口：集合 = {活动层}（进入编辑）。
            SESSION_SET.open(layer_id, crs=str(getattr(layer, "crs", "") or ""),
                             stack=stack)
        return True, ""

    def rollback(self, layer_id: str) -> tuple[bool, str]:
        """回滚到会话开启时快照基线（§2 易失会话；镜像即编辑发生地，
        rollBack 后镜像内容自动复位，宿主台账冻结在基线 → 无需重发）。"""
        layer_id = str(layer_id)
        session = self._sessions.pop(layer_id, None)
        if session is None:
            return False, "该图层没有进行中的原生编辑会话"
        try:
            error = str(session["stack"].roll_back_mirror_layer(layer_id) or "")
        except Exception as exc:
            return False, f"回滚失败：{exc}"
        if error:
            return False, f"回滚失败：{error}"
        SESSION_SET.discard(layer_id)
        self.gestures.clear()
        self._pending_commits.pop(layer_id, None)
        return True, ""

    # -- committed 增量（§2 回写通道）---------------------------------------

    def handle_committed(self, doc_id: str, delta_json) -> None:
        """桥 committed 回调收集点（commit 期间同步触发）。"""
        try:
            delta = delta_json if isinstance(delta_json, dict) else json.loads(
                str(delta_json))
        except (TypeError, ValueError):
            logger.warning("native commit delta unparsable for %s", doc_id)
            return
        self._pending_commits[str(doc_id)] = delta

    # -- 读回（编辑缓冲即事实）----------------------------------------------

    def readback_features(self, stack, layer_id: str) -> list[dict]:
        """镜像层当前要素（含未提交编辑缓冲）——拓扑门禁的校验输入。"""
        try:
            raw = stack.mirror_features_json(str(layer_id))
            payload = raw if isinstance(raw, dict) else json.loads(str(raw))
        except (TypeError, ValueError):
            return []
        if not payload or not payload.get("exists"):
            return []
        features = payload.get("features") or []
        normalized = []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            properties = feature.get("properties") or {}
            feature_id = str(
                properties.get("__pwb_fid") or feature.get("id") or "")
            if not feature_id:
                continue
            normalized.append({
                "feature_id": feature_id,
                "geometry": feature.get("geometry") or {},
                "attributes": dict(properties),
            })
        return normalized

    # -- 属性写入（编辑期换相/属性编辑的唯一原生通道）------------------------

    @staticmethod
    def supports_attribute_write(stack) -> bool:
        """桥是否具备镜像属性写 op（旧桥诚实降级，不冒充支持）。"""
        return callable(getattr(stack, "set_mirror_feature_attributes", None))

    def set_feature_attributes(self, layer_id: str, feature_ids,
                               attributes) -> tuple[bool, str]:
        """在镜像编辑缓冲改属性（一宏可撤销；随 commit 落盘）。

        编辑权在原生缓冲时宿主**不得**另开 Python 会话（M1 §2）——换相等
        属性写入走这里，与顶点编辑同一撤销/提交语义。
        """
        layer_id = str(layer_id)
        session = self._sessions.get(layer_id)
        if session is None:
            return False, "该图层没有进行中的原生编辑会话"
        stack = session["stack"]
        if not self.supports_attribute_write(stack):
            return False, (
                "当前 QGIS 桥不支持编辑期属性写入"
                "（需重建 qgis_render_bridge）")
        ids = [str(fid) for fid in (feature_ids or ()) if str(fid)]
        if not ids:
            return False, "没有要修改的要素"
        values = {str(key): value for key, value in dict(attributes or {}).items()}
        if not values:
            return False, "没有要写入的属性"
        try:
            error = str(stack.set_mirror_feature_attributes(
                layer_id, json.dumps(ids), json.dumps(values)) or "")
        except Exception as exc:  # 桥侧异常不吞：原因上浮
            return False, f"属性写入失败：{exc}"
        if error:
            return False, error
        return True, ""

    def pending_changes(self, layer_id: str) -> bool | None:
        """原生缓冲是否有未提交修改；None = 桥无查询面（未知，不猜）。"""
        session = self._sessions.get(str(layer_id))
        if session is None:
            return False
        probe = getattr(session["stack"], "mirror_layer_dirty", None)
        if not callable(probe):
            return None
        try:
            return bool(probe(str(layer_id)))
        except Exception:
            logger.debug("mirror_layer_dirty unavailable", exc_info=True)
            return None

    def _topology_gate_issues(self, topology) -> list[dict[str, object]]:
        """M4 检查器门禁；旧桥回落逐层 validate_records。"""
        checker = getattr(topology, "checker", None)
        first = next(iter(self._sessions.values()), None)
        stack = first["stack"] if first is not None else None
        if (checker is not None and stack is not None
                and callable(getattr(stack, "run_geometry_checks", None))):
            canvas = first.get("canvas") or 0
            issues = checker.run_for_commit(
                stack, canvas, list(self._sessions))
            for layer_id, session in self._sessions.items():
                count = sum(1 for issue in issues
                            if str(issue.get("layer_id") or "") == layer_id)
                topology.record_validation(session["layer"], count)
            return issues
        issues: list[dict[str, object]] = []
        for layer_id, session in self._sessions.items():
            layer = session["layer"]
            records = self.readback_features(session["stack"], layer_id)
            layer_issues = topology.validate_records(layer_id, records)
            topology.record_validation(layer, len(layer_issues))
            issues.extend(layer_issues)
        return issues

    # -- 保存：整集合全或无（§3）---------------------------------------------

    def commit_all(self, *, gate, topology, geology=None,
                   on_committed=None) -> tuple[bool, str]:
        """提交会话集合：全过逐层 commit + 写回 + 对齐；任一失败全保持。

        ``on_committed(layer)`` 在每层增量写回成功后调用（宿主做台账对齐
        —— M0 ``align_publish_ledger`` —— 与 content_changed 通知）。
        geotopo Ticket 5：① ``geology`` 谓词（编辑真值 → InvariantViolation
        列表）作为第三提交门（error 级拦截，warning 放行）；② 中途失败时
        已提交层按快照**补偿恢复**（重开会话 + restore_mirror_snapshot 一宏，
        会话保持可撤销——补偿可用 Ctrl+Z 回退的逃生口，D9）。
        """
        if not self._sessions:
            return True, ""
        # 提交前段 ①：角色门禁全集合复查。
        for layer_id, session in self._sessions.items():
            if gate is not None:
                allowed, reason = gate(layer_id)
                if not allowed:
                    layer = session["layer"]
                    return False, (
                        f"图层「{getattr(layer, 'name', layer_id)}」"
                        f"{reason}（全部编辑未提交）")
        # 提交前段 ②：拓扑零错误全集合判定。M4：桥检查器（含忽略豁免）
        # 优先；旧桥回落 validate_records（几何读回 = 编辑缓冲事实）。
        if topology is not None and topology.enabled:
            issues = self._topology_gate_issues(topology)
            if issues:
                shown = issues[:3]
                details = "；".join(
                    f"{issue.get('feature_id', '')}："
                    f"{issue.get('message', '')}" for issue in shown)
                more = (f"（另有 {len(issues) - 3} 个问题）"
                        if len(issues) > 3 else "")
                first_layer = str(shown[0].get("layer_id") or next(iter(self._sessions)))
                session = self._sessions.get(first_layer) or next(iter(self._sessions.values()))
                layer = session["layer"]
                return False, (
                    f"图层「{getattr(layer, 'name', first_layer)}」"
                    f"{len(issues)} 个要素未通过拓扑检查：{details}{more}"
                    f"（全部编辑未提交）")
        # 提交前段 ②'：地质不变量门（geotopo Ticket 4 接入，§4.3）——
        # error 级违规拦截全集合；warning 级放行（宿主另行上报）。
        if geology is not None:
            records = {
                layer_id: self.readback_features(session["stack"], layer_id)
                for layer_id, session in self._sessions.items()
            }
            violations = list(geology(records) or [])
            errors = [v for v in violations
                      if getattr(v, "severity", "error") == "error"]
            if errors:
                first = errors[0]
                layer = (self._sessions.get(first.layer_id) or {"layer": None})["layer"] \
                    if hasattr(first, "layer_id") else None
                names = "、".join(sorted({getattr(
                    (self._sessions.get(v.layer_id) or {"layer": None})["layer"]
                    if (self._sessions.get(v.layer_id) or {}).get("layer") is not None
                    else v.layer_id, "name", v.layer_id)
                    for v in errors if hasattr(v, "layer_id")})) or "图件"
                return False, (
                    f"地质不变量校验未通过（{names}）：{first.code}："
                    f"{first.message}——共 {len(errors)} 个 error 级违规"
                    f"（全部编辑未提交）")
        # 快照（补偿恢复的输入）：提交前捕获每层镜像真值——仅多会话集合
        # 需要（单会话失败无"已提交层"可补偿；审查 Standards#7）。
        snapshots: dict[str, str] = {}
        if len(self._sessions) >= 2 and all(callable(getattr(
                session["stack"], "restore_mirror_snapshot", None))
                for session in self._sessions.values()):
            for layer_id, session in self._sessions.items():
                try:
                    snapshots[layer_id] = str(
                        session["stack"].mirror_features_json(layer_id, 0))
                except Exception:
                    logger.exception("snapshot capture failed: %s", layer_id)
        # 逐层 commit（会话集合序）；失败 → 剩余层 rollBack + 已提交层补偿。
        ordered = list(self._sessions.items())
        committed: list[tuple[str, dict]] = []
        for layer_id, session in ordered:
            try:
                error = str(
                    session["stack"].commit_mirror_layer(layer_id) or "")
            except Exception as exc:
                error = str(exc)
            if error:
                # 全或无（§3）+ Ticket 5 补偿：失败层 X 保持会话（QGIS
                # commit 失败缓冲未清——修复后可重试）；X 之后的剩余层
                # rollBack；已提交层重开会话按快照恢复（内容等价），
                # 恢复宏保留在 undo 栈（逃生口），会话保持打开。
                failed_reason = (
                    f"图层「{getattr(session['layer'], 'name', layer_id)}」"
                    f"提交失败：{error}（其后图层已回滚，已提交层已补偿恢复）")
                for remaining_id, remaining in self._sessions.items():
                    if remaining_id in {lid for lid, _s in committed}:
                        continue
                    if remaining_id == layer_id:
                        continue  # 失败层保持会话
                    try:
                        remaining["stack"].roll_back_mirror_layer(remaining_id)
                    except Exception:
                        logger.exception("post-failure rollback failed: %s",
                                         remaining_id)
                compensated_ids = self._compensate_committed(
                    committed, snapshots)
                for done_id, _done in committed:
                    if done_id in compensated_ids:
                        continue  # 补偿层保持会话（恢复宏可撤销）
                    self._sessions.pop(done_id, None)
                    SESSION_SET.discard(done_id)
                for rolled_id in list(self._sessions):
                    if rolled_id != layer_id and rolled_id not in compensated_ids:
                        self._sessions.pop(rolled_id, None)
                        SESSION_SET.discard(rolled_id)
                # 停发窗口收敛为失败层（可重试提交）。
                return False, failed_reason
            committed.append((layer_id, session))
            delta = self._pending_commits.pop(layer_id, None)
            if delta:
                session["layer"].apply_committed_delta(
                    delta, session_id=f"native-{layer_id}",
                    source_tool="native",
                    gestures=self.gestures.audit_records())
            if on_committed is not None:
                on_committed(session["layer"])
        for layer_id, _session in committed:
            self._sessions.pop(layer_id, None)
        SESSION_SET.close()
        self.gestures.clear()
        return True, ""

    def _compensate_committed(self, committed, snapshots) -> list[str]:
        """已提交层补偿恢复（D9）：重开会话 + restore 一宏 + 登记手势。

        返回成功补偿的层 id；失败层尽力回滚会话并记录（不抛出——补偿
        在失败路径上，绝不再制造异常窗口）。
        """
        compensated: list[str] = []
        for done_id, session in committed:
            snapshot = snapshots.get(done_id)
            stack = session["stack"]
            if snapshot is None or not callable(
                    getattr(stack, "restore_mirror_snapshot", None)):
                continue
            try:
                reopen_error = str(stack.start_mirror_layer_editing(done_id) or "")
                if reopen_error:
                    logger.error("compensation reopen failed: %s: %s",
                                 done_id, reopen_error)
                    continue
                restore_error = str(stack.restore_mirror_snapshot(done_id, snapshot) or "")
                if restore_error:
                    logger.error("compensation restore failed: %s: %s",
                                 done_id, restore_error)
                    stack.roll_back_mirror_layer(done_id)
                    continue
            except Exception:
                logger.exception("compensation failed: %s", done_id)
                continue
            self._compensations.append(done_id)
            self.gestures.finish(
                new_feature_id("gesture"),
                undo_text="撤销复合提交",
                layer_ids=[done_id])
            compensated.append(done_id)
        return compensated

    @property
    def compensations(self) -> list[str]:
        """补偿恢复事件（只读视图；诊断/审计）。"""
        return list(self._compensations)

    # -- 手势（undo/redo 桥侧宏的宿主计划）-----------------------------------

    def undo_gesture(self) -> bool:
        """整手势撤销：逆序逐层 undo（层内 = QGIS undoStack 宏）。
        部分层失败不标记手势完成（§2 失败半程语义——下次重试同一计划）。"""
        plan = self.gestures.undo_plan()
        gesture_id = self.gestures.current_gesture_id()
        if not plan:
            return False
        ok = True
        for layer_id in plan:
            session = self._sessions.get(layer_id)
            if session is None:
                continue
            try:
                session["stack"].undo_mirror_edit(layer_id)
            except Exception:
                logger.exception("gesture undo failed: %s", layer_id)
                ok = False
        if gesture_id and ok:
            self.gestures.mark_undone(gesture_id)
        return ok

    def redo_gesture(self) -> bool:
        """整手势重做：正序逐层 redo（同 undo 的失败语义）。"""
        plan = self.gestures.redo_plan()
        gesture_id = self.gestures.current_gesture_id()
        if not plan:
            return False
        ok = True
        for layer_id in plan:
            session = self._sessions.get(layer_id)
            if session is None:
                continue
            try:
                session["stack"].redo_mirror_edit(layer_id)
            except Exception:
                logger.exception("gesture redo failed: %s", layer_id)
                ok = False
        if gesture_id and ok:
            self.gestures.mark_redone(gesture_id)
        return ok
