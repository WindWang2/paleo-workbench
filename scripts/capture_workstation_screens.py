#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""B17 视觉 QA 截图 harness（offscreen widget.grab，无头可跑）。

用法（worktree 根目录）：
    ./run_goalB.sh --python scripts/capture_workstation_screens.py [输出目录]

产出 12 张关键状态 PNG（默认 visual_qa/）。部件用 QWidget.grab() 渲染，
offscreen 平台下无需真实显示服务器；截图只是像素证据，不替代 widget 级
断言测试。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paleo_workbench.project.domain import WellEntity  # noqa: E402
from paleo_workbench.project.models import ProjectDocument, ResourceItem  # noqa: E402


def _project(tmp: Path, *, heavy: bool = False, empty: bool = False) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp)
    if empty:
        return project
    wells = ["A12", "W23", "B5", "C7"] + (
        [f"W{n}" for n in range(100, 160)] if heavy else []
    )
    for i, name in enumerate(wells):
        project.wells.append(
            WellEntity(
                name=name,
                surface_x=1.0 + i,
                surface_y=2.0 + i * 0.5,
                project_x=1.0 + i,
                project_y=2.0 + i * 0.5,
            )
        )
        project.resources.append(
            ResourceItem(
                name=f"{name}.Las", path=f"wells/{name}.Las", type="well_log", format="las"
            )
        )
    project.resources.extend(
        [
            ResourceItem(name="D63.dat", path="horizons/D63.dat", type="horizon", format="dat"),
            ResourceItem(name="seis.segy", path="segy/seis.segy", type="seismic", format="segy"),
            ResourceItem(name="factor_map.png", path="maps/factor_map.png", type="raster", format="png"),
        ]
    )
    project.stratigraphy.target_horizon = "D63"
    return project


def _grab(widget, path: Path) -> None:
    host = widget
    host.resize(1600, 900)
    # 延迟 restore（show 后 ~50ms）+ 首运行尺寸校准要在事件循环里跑完，
    # 否则抓到的是 QMainWindow 出厂均分布局（那不是工作站的真实布局）。
    from PySide6.QtCore import QEventLoop, QTimer as _QTimer

    loop = QEventLoop()
    _QTimer.singleShot(300, loop.quit)
    loop.exec()
    QApplication.processEvents()
    pix = host.grab()
    path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(path))
    host.hide()
    print(f"saved {path} ({pix.width()}x{pix.height()})")


def _settle(ms: int) -> None:
    from PySide6.QtCore import QEventLoop, QTimer as _QTimer

    loop = QEventLoop()
    _QTimer.singleShot(ms, loop.quit)
    loop.exec()
    QApplication.processEvents()


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("visual_qa")
    # 隔离 QSettings：截图 harness 不得读写真实用户布局（也不吃上一轮
    # offscreen 运行留下的坏布局——那正是要审的第一运行问题）。
    import os

    settings_dir = out_dir / "_qsettings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    os.environ["XDG_CONFIG_HOME"] = str(settings_dir)
    from PySide6.QtCore import QSettings

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(settings_dir),
    )
    app = QApplication.instance() or QApplication([])
    # 用生产顶层窗口（dock_host = 窗口本体 + setCentralWidget），
    # 孤立 AppShell 没有 dock 宿主装配，抓不到真实布局。
    from paleo_workbench.app import PaleoWorkbenchWindow
    from paleo_workbench.ui.theme import ThemeManager

    tmp = out_dir / "_tmp_project"
    tmp.mkdir(parents=True, exist_ok=True)

    # 全局演示任务：任务中心/错误态截图的数据源（进程级调度器）。
    stop = {"flag": False}

    def _long_task(_ctx):
        import time

        while not stop["flag"]:
            time.sleep(0.05)
        return {"ok": True}

    def _bad(_ctx):
        raise RuntimeError("合成失败：SEGY 卷缺少必要的 trace 头字段")

    demo_task_id = None

    def start_demo_tasks():
        nonlocal demo_task_id
        try:
            from paleo_workbench.runtime.task_scheduler import TaskSpec, get_scheduler

            handle = get_scheduler().submit(
                TaskSpec(callable=_long_task, kind="background.io", title="示例 · 制备因子网格")
            )
            demo_task_id = handle.task_id
            get_scheduler().submit(
                TaskSpec(callable=_bad, kind="background.io", title="示例 · 转码失败")
            )
        except Exception as exc:  # noqa: BLE001 — 截图 harness 不因调度器差异失败
            print(f"task center demo skipped: {exc}")

    def drive_mapping(window):
        ws = window.app_shell.workstation
        for dock in (ws.composite_layer_dock, ws.inspector_dock):
            dock.show()
        ws.inspector.show_payload(
            {"kind": "layer", "layer_id": "facies_polygons", "name": "砂岩等值线",
             "geometry_kind": "polygon"}
        )

    def drive_layer_style(window):
        ws = window.app_shell.workstation
        ws.inspector_dock.show()
        ws.inspector_dock.raise_()  # 与图层管理 tab 化：必须把检查器带到前台
        ws.inspector.show_payload(
            {"kind": "layer", "layer_id": "facies_polygons", "name": "砂岩等值线",
             "geometry_kind": "polygon"}
        )
        ws.inspector.tabs.setCurrentWidget(ws.inspector.style_page)

    def drive_integrated(window):
        # 集成工作区：全部 dock 的综合预设 + 井/地震/联动视图同屏
        # （此前只 raise 测井，与 05-well 像素级相同，视觉 QA 判 fail）。
        ws = window.app_shell.workstation
        ws.apply_layout_preset("integrated")
        _settle(150)
        ws.show_seismic()
        _settle(150)
        ws.show_well("A12")  # 后 raise：测井在前，地震/联动/任务同屏可见

    def drive_well(window):
        window.app_shell.workstation.show_well("A12")

    def drive_seismic(window):
        window.app_shell.workstation.show_seismic()

    def drive_agent(window):
        ws = window.app_shell.workstation
        agent = ws.process_hub.agent
        agent.history.append(
            "<hr><b>用户</b> · 打开井 A12，把 GR 曲线放到第一道<br>"
            "<b>执行计划</b> · 打开井 A12，校验 GR 曲线并生成第一轨显示文档<br>"
            "<span>动作 well.open [计算] · 回执 1a2b3c4d</span>"
        )
        # 运行中的真实任务行：顶栏计数 + 任务中心进度可视化（此前空表壳）。
        start_demo_tasks()
        _settle(400)  # 让调度器认领任务、进度首跳可见
        ws.task_center.refresh()
        ws.show_agent()

    def drive_tasks(window):
        window.app_shell.workstation.show_tasks()

    def drive_error(window):
        """错误态：单独提交一个立即失败的任务并等它真实落到 FAILED。

        不走 start_demo_tasks——长任务先占住 worker 会把失败任务压在
        排队里，8 秒内落不了 FAILED（视觉 QA 实测）。"""
        ws = window.app_shell.workstation
        from paleo_workbench.runtime.task_scheduler import TaskSpec, TaskState, get_scheduler

        ws.show_tasks()
        get_scheduler().submit(
            TaskSpec(callable=_bad, kind="background.io", title="示例 · 转码失败")
        )
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            app.processEvents()
            statuses = get_scheduler().statuses()
            if any(h.state is TaskState.FAILED for h in statuses):
                break
            time.sleep(0.05)
        ws.task_center.refresh()

    shots = {
        "01-default-workstation": (lambda: _project(tmp), None),
        "02-data-heavy-project": (lambda: _project(tmp, heavy=True), None),
        "11-empty-state": (lambda: _project(tmp, empty=True), None),
        "03-mapping": (lambda: _project(tmp), drive_mapping),
        "04-layer-style": (lambda: _project(tmp), drive_layer_style),
        "05-well": (lambda: _project(tmp), drive_well),
        "06-seismic": (lambda: _project(tmp), drive_seismic),
        "07-integrated": (lambda: _project(tmp), drive_integrated),
        "08-agent-running": (lambda: _project(tmp), drive_agent),
        "09-task-center": (lambda: _project(tmp), drive_tasks),
        "10-error-state": (lambda: _project(tmp), drive_error),
        "12-dark-theme": (lambda: _project(tmp), "dark"),
    }

    # --shot NAME：单 shot 子进程模式（main 进程逐个 spawn——多窗口同进程
    # 会因 QGIS/调度器状态搅扰挂死；每 shot 一个进程 = 真实全新启动）。
    only = None
    if len(sys.argv) > 2 and sys.argv[2] == "--shot":
        only = sys.argv[3]
    if only is not None:
        make_project, drive = shots[only]
        # 清工作站布局必须用 shell 的设置身份（QSettings() 无参是空 org/app，
        # 清不到 PaleoWorkbench/Workstation——首运行分支因此从未触发）。
        QSettings("PaleoWorkbench", "Workstation").clear()
        if drive == "dark":
            # 必须切全局单例：app_shell 构造时会用 theme_manager.get_qss()
            # 自贴一层（子树优先于 app 级样式表），图标染色与 ui.style 注册
            # 表也都读单例——局部实例只暗了 QSS，留下整片亮色 chrome。
            from paleo_workbench.ui.theme import theme_manager as _global_theme

            _global_theme.set_theme("dark")
            _global_theme.apply(app)
        if drive is drive_tasks:
            start_demo_tasks()  # 任务行是进程级调度器的：子进程里自己起
        window = PaleoWorkbenchWindow(project=make_project())
        window.resize(1600, 900)
        window.show()
        _settle(500)
        if callable(drive):
            drive(window)
            _settle(250)
        pix = window.grab()
        path = out_dir / f"{only}.png"
        pix.save(str(path))
        print(f"saved {path} ({pix.width()}x{pix.height()})", flush=True)
        return 0

    import subprocess

    def run_all() -> int:
        failures = []
        for name in shots:
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    str(out_dir),
                    "--shot",
                    name,
                ],
                check=False,
                timeout=300,
            )
            if result.returncode != 0:
                failures.append(f"{name}: exit {result.returncode}")
        for line in failures:
            print(f"FAILED SHOT {line}", flush=True)
        return 0

    QTimer.singleShot(200, lambda: (run_all(), app.quit()))
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
