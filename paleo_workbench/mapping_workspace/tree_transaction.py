"""V11 树事务窗口的 Python 侧入口（能力探测 + 上下文管理器）。

桥具备 ``begin_tree_update``（0.7.0a0+）时，``with tree_transaction(stack)``
内的一切树/镜像变更共享一个原生窗口：零中间画布同步、收口一次
sync+refresh；旧桥/无桥时透明降级为逐调用语义（行为不变，仅失去批量
收口）。收口结果写入 yield 的 ``handle``（``token`` / ``revision`` /
``deferred_sync``；降级路径 ``token`` 为 None）。
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator


@contextmanager
def tree_transaction(stack: Any) -> Iterator[dict]:
    """树事务窗口（能力感知；异常路径保证收口）。"""
    begin = getattr(stack, "begin_tree_update", None)
    end = getattr(stack, "end_tree_update", None)
    if not callable(begin) or not callable(end):
        yield {"token": None}
        return
    token = begin()
    handle = {"token": token}
    try:
        yield handle
    finally:
        # end 总会执行（含窗口内异常）：已应用的变更保留，partial
        # failure 由调用方经 revision / diff 对账。
        import json as _json

        payload = end(token)
        if isinstance(payload, str) and payload:
            parsed = _json.loads(payload)
            if isinstance(parsed, dict):
                handle["revision"] = parsed.get("revision")
                handle["deferred_sync"] = parsed.get("deferred_sync")


def tree_transaction_supported(stack: Any) -> bool:
    begin = getattr(stack, "begin_tree_update", None)
    return callable(begin)
