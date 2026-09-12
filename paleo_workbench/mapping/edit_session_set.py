"""编辑会话层集合（拓扑编辑迁移 M0 §3 地基）。

会话集合 = 当前编辑会话波及的层集合：进入编辑 = {活动层}；手势波及
邻层（顶点「全部层」档、拓扑点散布目标）时经门禁复查**按需生长**——
通过自动加入，拒绝则该层不参与并提示（决策 #1283）。

集合整体构成镜像重发的**停发窗口**：集合内层的数据增量重发被短路
（M1 起编辑直接发生在镜像层上，宿主重发会覆盖编辑缓冲）；集合外层
照常发布（no-op 样式漂移自愈在集合外层继续生效）。编辑期数据台账
冻结；样式验证继续跑；提交后由台账对齐直跳新基线（qgis_mirror.
align_publish_ledger）。

会话开启时 CRS 冻结（决议 #1285：编辑会话期间 CRS 不可变更）；字段
schema 变更在集合内层被拒（先保存/回滚），集合外不受限。

纯逻辑模块（无 Qt）——M1 的手势管理器/committed* 回写以本模块为
集合权威，镜像发布通道经 :func:`active_layer_ids` 消费。
"""
from __future__ import annotations

import weakref
from dataclasses import dataclass

__all__ = [
    "EditSessionSet",
    "JoinDecision",
    "SESSION_SET",
    "reset_session_set",
]


@dataclass(frozen=True)
class JoinDecision:
    """一次邻层入集复查的结论（拒绝时 reason 供状态条提示）。"""

    layer_id: str
    accepted: bool
    reason: str = ""


class EditSessionSet:
    """单编辑会话的层集合与冻结状态（会话集合按需生长，§3）。"""

    def __init__(self) -> None:
        self._layers: dict[str, str] = {}  # layer_id -> 会话内有效 CRS
        self._frozen_crs: str = ""
        self._stack_ref: object = None  # weakref → 发布目标栈（停发窗口绑定）

    # -- 生命周期 ---------------------------------------------------------

    def open(self, layer_id: str, *, crs: str = "", stack=None) -> None:
        """开启会话：集合 = {活动层}，冻结会话 CRS 与发布目标栈。"""
        self._layers = {str(layer_id): str(crs or "")}
        self._frozen_crs = str(crs or "")
        self._stack_ref = self._ref(stack)

    @staticmethod
    def _ref(stack):
        """栈绑定引用：可弱引用则弱引用（随栈回收解除绑定）；否则强引用
        （不可弱引用的栈对象生命周期即会话绑定，close() 显式解除）。"""
        if stack is None:
            return None
        try:
            return weakref.ref(stack)
        except TypeError:
            return stack

    def request_join(self, layer_ids, gate=None) -> list[JoinDecision]:
        """邻层入集复查（手势波及时调用）：门禁通过自动加入集合。

        ``gate(layer_id) -> (allowed, reason)``——角色/成熟度/组锁等
        宿主门禁的单点复查；缺省无门禁 = 全通过（纯几何波及）。
        """
        decisions: list[JoinDecision] = []
        for layer_id in layer_ids:
            layer_id = str(layer_id)
            if layer_id in self._layers:
                decisions.append(JoinDecision(layer_id, True))
                continue
            allowed, reason = (True, "")
            if gate is not None:
                allowed, reason = gate(layer_id)
            if allowed:
                self._layers[layer_id] = self._frozen_crs
                decisions.append(JoinDecision(layer_id, True))
            else:
                decisions.append(
                    JoinDecision(layer_id, False, str(reason or "门禁拒绝")))
        return decisions

    def close(self) -> tuple[str, ...]:
        """关闭会话（提交/回滚后）：复位集合与冻结状态，返回曾属集合的层。"""
        was = tuple(self._layers)
        self._layers = {}
        self._frozen_crs = ""
        self._stack_ref = None
        return was

    def discard(self, layer_id: str) -> None:
        """从集合移除单层（QGIS 逐层回滚语义；集合空 = 会话关闭）。"""
        self._layers.pop(str(layer_id), None)
        if not self._layers:
            self._frozen_crs = ""
            self._stack_ref = None

    # -- 查询 -------------------------------------------------------------

    def contains(self, layer_id: str) -> bool:
        return str(layer_id) in self._layers

    def layer_ids(self) -> tuple[str, ...]:
        """有序集合（加入顺序；首元素 = 活动层）。"""
        return tuple(self._layers)

    @property
    def is_open(self) -> bool:
        return bool(self._layers)

    @property
    def frozen_crs(self) -> str:
        """会话开启时冻结的 CRS（编辑期间不可变更，§6）。"""
        return self._frozen_crs

    def active_layer_ids(self, stack) -> tuple[str, ...]:
        """停发窗口查询：会话绑定到该发布栈时返回集合，否则空。

        未绑定栈的会话对任何发布都不短路（保守：无编辑发生地的会话
        不构成停发窗口）。
        """
        if not self._layers or self._stack_ref is None:
            return ()
        bound = self._stack_ref() if callable(self._stack_ref) else self._stack_ref
        if bound is None or bound is not stack:
            return ()
        return tuple(self._layers)

    # -- 变更互斥（§3）-----------------------------------------------------

    def allows_crs_change(self) -> tuple[bool, str]:
        """编辑会话期间 CRS 冻结：会话开启即拒绝变更。"""
        if self.is_open:
            return False, "编辑会话进行中——CRS 已冻结，请先保存或回滚编辑"
        return True, ""

    def allows_schema_change(self, layer_id: str) -> tuple[bool, str]:
        """集合内层编辑中字段 schema 变更拒绝（先保存/回滚）；集合外不受限。"""
        if self.contains(layer_id):
            return False, (
                f"图层「{layer_id}」正在编辑会话中——字段结构变更被拒绝，"
                "请先保存或回滚编辑")
        return True, ""


# 进程级默认实例：工作台同一时刻至多一个编辑会话（M1 手势管理器接管
# 生命周期；镜像发布通道只读消费）。
SESSION_SET = EditSessionSet()


def reset_session_set() -> None:
    """测试隔离：原地复位进程级会话集合。

    原地复位（而非重建实例）——消费方（镜像发布通道、测试）以
    ``from ... import SESSION_SET`` 持有实例引用，重建会让旧引用指向
    已死集合，停发窗口静默失效。
    """
    SESSION_SET.close()
