"""GUI 线程契约（goal §9）：统一异步查询 —— epoch + latest-only + 迟到拒绝。

背景（01-ui-audit D1/D4）：页面在 GUI 线程直接做服务调用（血缘遍历、
大对象物化）；已有 worker（IntegrityWorker 等）的进度信号甚至没接线。
本模块给表现层一个统一的异步查询入口，硬约束：

* 查询函数**永不**在 GUI 线程执行；
* 每次 submit 递增 epoch；回调只对**最新** epoch 生效（latest-only）；
* 宿主关闭（``shutdown`` / ``destroyed``）后一切迟到回调被丢弃
  （OwnedWorkerJob released 旗标 + 本层 epoch 双保险）；
* 取消是协作式的：提交方可传 ``cancel`` 钩子，新一轮请求让位时调用。

不引入新的线程设施：复用 OwnedWorkerJob（一次一作业、排队投递、
销毁安全），本类是它的**单槽最新值**门面。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar

from PySide6.QtCore import QObject, Signal

from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob

logger = logging.getLogger(__name__)

T = TypeVar("T")


class _QueryWorker(QObject):
    """单函数工作体：run() 在 owned 线程执行查询，结束时发 done 终止线程。"""

    done = Signal()

    def __init__(self, fn: Callable[[], Any], on_done: Callable[[], None]) -> None:
        super().__init__()
        self._fn = fn
        self._on_done = on_done

    def run(self) -> None:  # thread.started 触发
        try:
            self._fn()
        finally:
            try:
                self._on_done()
            except Exception:
                pass
            self.done.emit()


class AsyncQuery(QObject):
    """单槽 latest-only 异步查询门面（GUI 线程构造与使用）。

    用法::

        query = AsyncQuery(parent=page)
        query.submit(
            lambda: service.get_lineage_chain(asset_id),   # worker 线程执行
            on_ready=self._show_lineage,                   # GUI 线程回调
            on_error=self._show_lineage_error,
        )

    较重的服务调用（全量 SQL、hash、血缘遍历、大 JSON）**必须**走这里
    而不是在 GUI 线程直呼；轻量内存操作（按 id 取单对象）允许同步。
    """

    _CALL = Signal(int, object)  # epoch, result
    _FAIL = Signal(int, object)  # epoch, exception

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._epoch = 0
        self._job: OwnedWorkerJob | None = None
        self._on_ready: Callable[[object], None] | None = None
        self._on_error: Callable[[Exception], None] | None = None
        # 连接指向本对象（随宿主销毁自动断开，不留 singleton 回调）。
        self._CALL.connect(self._deliver)
        self._FAIL.connect(self._deliver_error)

    # -- 生命周期 -----------------------------------------------------------------

    @property
    def is_pending(self) -> bool:
        return self._job is not None and self._job.is_running

    def shutdown(self, wait_ms: int = 500) -> None:
        """取消并等待在途查询（页面 close / 工程关闭时调用）。"""
        self._epoch += 1  # 使一切在途回调失效
        self._on_ready = None
        self._on_error = None
        job = self._job
        if job is not None:
            job.shutdown(wait_ms)
            self._job = None

    # -- 提交 ---------------------------------------------------------------------

    def submit(
        self,
        fn: Callable[[], T],
        *,
        on_ready: Callable[[T], None],
        on_error: Callable[[Exception], None] | None = None,
        cancel: Callable[[], None] | None = None,
    ) -> int:
        """执行 ``fn``（worker 线程）并把结果交给 ``on_ready``（GUI 线程）。

        返回本次 epoch。已有在途查询时：先协作取消旧查询并立即释放其
        槽位（released 旗标即刻生效），旧结果即使完成也不再投递。
        """
        if self._job is not None and self._job.is_running:
            self._job.cancel()
            self._job.shutdown(0)  # 不等待；迟到结果由 epoch 拒绝
        self._epoch += 1
        epoch = self._epoch
        self._on_ready = on_ready
        self._on_error = on_error

        def _run() -> None:
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001 — 错误交给调用方回调
                self._FAIL.emit(epoch, exc)
                return
            self._CALL.emit(epoch, result)

        def _drain() -> None:
            # run() 结束（无论成败）：线程由 done 信号退出；槽位清理由
            # GUI 线程的 _deliver/_deliver_error 完成（避免跨线程写状态）。
            return

        worker = _QueryWorker(_run, _drain)
        job = OwnedWorkerJob(parent=self)
        # 释放即自清（长会话高频选择不再累积已释放的 QObject 子对象）。
        job.released.connect(job.deleteLater)
        job.start(
            worker,
            terminal_signals=(worker.done,),
            cancel=cancel,
            target=epoch,
        )
        self._job = job
        return epoch

    # -- GUI 线程投递（epoch 校验） -----------------------------------------------

    def _deliver(self, epoch: int, result: object) -> None:
        if epoch != self._epoch:
            return  # 迟到结果：已有更新请求或已关闭
        if self._job is not None and self._job.target == epoch:
            self._job = None  # 槽位清理只发生在 GUI 线程
        callback = self._on_ready
        if callback is not None:
            try:
                callback(result)
            except RuntimeError:
                pass  # 宿主已销毁
            except Exception:
                logger.exception("AsyncQuery on_ready 回调失败")

    def _deliver_error(self, epoch: int, exc: object) -> None:
        if epoch != self._epoch:
            return
        if self._job is not None and self._job.target == epoch:
            self._job = None
        callback = self._on_error
        if callback is not None:
            try:
                callback(exc if isinstance(exc, Exception) else RuntimeError(str(exc)))
            except RuntimeError:
                pass
            except Exception:
                logger.exception("AsyncQuery on_error 回调失败")
