"""原生编辑会话控制器（拓扑编辑迁移 M1 §2/§3）。

编辑权迁移 QGIS 后宿主是**同步方**：镜像层经桥 ``startEditing()`` 进入
原生编辑缓冲，顶点工具直接编辑镜像；Python 真源（user_vector_layers）
只在提交后消费 committed\* 增量对齐（``VectorLayer.apply_committed_delta``）。
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

__all__ = ["NativeEditSessionController"]

logger = logging.getLogger(__name__)


class NativeEditSessionController:
    """原生编辑会话的宿主侧生命周期（一个工作台一个实例）。"""

    def __init__(self) -> None:
        # layer_id → {"stack", "layer"}（会话集合的宿主侧视图）。
        self._sessions: dict[str, dict] = {}
        # doc_id → 提交时桥回传的 committed 增量（同步回调收集）。
        self._pending_commits: dict[str, dict] = {}
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
            })
        return normalized

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

    def commit_all(self, *, gate, topology, on_committed=None) -> tuple[bool, str]:
        """提交会话集合：全过逐层 commit + 写回 + 对齐；任一失败全保持。

        ``on_committed(layer)`` 在每层增量写回成功后调用（宿主做台账对齐
        —— M0 ``align_publish_ledger`` —— 与 content_changed 通知）。
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
        # 逐层 commit（会话集合序）；失败 → 剩余层 rollBack（全或无）。
        ordered = list(self._sessions.items())
        committed: list[tuple[str, dict]] = []
        for layer_id, session in ordered:
            try:
                error = str(
                    session["stack"].commit_mirror_layer(layer_id) or "")
            except Exception as exc:
                error = str(exc)
            if error:
                # 全或无（§3）：失败层 X 保持会话（QGIS commit 失败缓冲未清
                # ——修复后可重试）；X 之后的剩余层 rollBack；已提交层照常
                # 留在已提交态（on_committed 已跑，出宿主会话表）。
                failed_reason = (
                    f"图层「{getattr(session['layer'], 'name', layer_id)}」"
                    f"提交失败：{error}（其后图层已回滚）")
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
                for done_id, _done in committed:
                    self._sessions.pop(done_id, None)
                    SESSION_SET.discard(done_id)
                for rolled_id in list(self._sessions):
                    if rolled_id != layer_id:
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
