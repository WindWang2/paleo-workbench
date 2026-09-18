# 16 — Decisions（每个非显然选择）

分支 `feat/cpp-conv-16-ui-panel-cluster`（BASE = origin/main `35987e13`）。

## D1 路径适配（任务书 vs 本机现实）

任务书给出的仓库根 `/home/kevin/projects/paleo_project/main` 在本机不存在；实际仓库是
`/home/kevin/project/paleo-workbench`（remote 相同：WindWang2/paleo-workbench）。worktree 落在
`/home/kevin/project/worktrees/cpp-conv-16-ui-panel-cluster`（与 conv-11..15 同级，仓库外）。
goal-loop/karpathy skill 按仓内 `agent/skills/` 解析。其余流程（分支名、BASE、账本、验收）不变。

## D2 C++ 验证环境：PLATFORM=OFF + CONV-16 自带 Qt 目标

本机没有 QGIS vendor 树（`PwbQgisSdk.cmake` 指向的 sibling main checkout 不存在），而系统 Qt6
6.11.2 可用。因此本 worktree 的构建树用任务书 §8 原样给出的
`-DPWB_BUILD_PLATFORM=OFF -DPWB_BUILD_DATA=ON -DPWB_BUILD_SCIENCE=OFF
-DPWB_BUILD_MAPPING_KERNEL=ON -DPWB_BUILD_CONV_16=ON -DBUILD_TESTING=ON`。
但 `tests/cpp/platform` 仅在 `PWB_BUILD_PLATFORM=ON` 下进入构建。为让 §8.4 要求的
`platform.factor_hud` 目标在本配置下真实存在，CONV-16 的根 CMake 块（§6 明示允许
「根 CMake 一般不用新 option；若必须 BEGIN CONV-16」）自行定义该测试目标：
仅依赖 `Qt6::Widgets + Pwb::MappingKernel`（HUD 不链 QGIS），offscreen 环境，单一定义
（`NOT TARGET platform_factor_hud` 守卫，平台树将来启用也不会重名）。
`apps/paleo_workbench_platform/CMakeLists.txt` 的 CONV-16 块则只在平台真被构建的机器上把
dock 编进 `pwb-platform`（`PWB_WITH_CONV_16=1`）。诚实边界：本机验证覆盖「dock + oracle」，
「MainWindow 内 dock 接线」只过编译级守卫、无法在本机链接（无 QGIS），如实声明。

## D3 §6 写入范围 vs §4「挂到 MainWindow dock」的冲突：最小守卫钩子

§6 只列出「apps 追加 dock 类新文件」，未列 `main_window.{hpp,cpp}`；而 §4/用户流程验收要求
dock 挂到 MainWindow。按 §0「对用户流程更诚实、更少抽象」裁定：对 `main_window.{hpp,cpp}`
做**最小 CONV-16 守卫钩子**（hpp：前置声明+成员+2 个方法声明；cpp：include+buildUi 3 行
addDockWidget+8 行 `showFactorStatistics` 转发）。全部改动 `#ifdef PWB_WITH_CONV_16` 包裹，
CONV-16 关闭时与 BASE 逐字节等价；绝无对既有逻辑的重排。清单与账本如实记录该文件被触及。

## D4 HUD 的行词表与格式 = Python 工作站已冻结的契约，不是新发明

行名（因素/取值范围/均值/标准差/有效格元）与取值范围格式 `f"{min:g} ~ {max:g}"` 来自
`inspector.show_factor`（workstation/inspector.py:512-520）且被 `tests/test_inspector_v7.py`
钉死（范围行 "10 ~ 220.5"、空 grid→"—"；:101 的 "0.5 ~ 3.25" 属「不确定性」行的同款
`:g` 词表佐证）；均值/标准差/有效格元是 §4 明确要求的
`FactorGrid.statistics` 字段（Python `GridStatistics` 有 min/max/mean/std/valid_count/total_count
六字段，uncertainty 属 kriging 方差面不在 `GridStatistics` 内，不伪造）。C++ `format_g`
= `QString::number(v,'g',6)`，与 Python `:g` 的逐字等价由 oracle 案例
（`0.0001 ~ 1.23457e+06`、`0.325`、`1.11803`）在 C++ 侧实测验证。

## D5 oracle 生成器 import 真实模块；「通过 FactorGridResult」路径单列

`tools/oracle/generate_factor_hud_fixtures.py` 用 conv-11 遗留的 oracle venv
（`/home/kevin/project/oracle-venvs/conv11`，numpy 可用）运行，`sys.path.insert(0, REPO_ROOT)`
保证 import 的是**本 worktree** 的 `paleo_workbench.workflow.factor_grid_result`。11 个案例中
`via_factor_grid_result` 走真实生产路径（`FactorGridResult.__post_init__ → _finalise →
GridStatistics.from_grid`），其余直调 `from_grid`；所有期望值（含显示字符串）均由真实模块与
真实 f-string 产出，零手写。全 NaN/空网格的显示走 Python 的 "—" 回退，C++ 同态断言。

## D6 测试里 dock 堆分配（Qt 所有权）

`addDockWidget` 会把 dock 重父级到 MainWindow；栈上 dock 会在宿主析构时被 Qt delete
再随栈析构二次销毁（实测 SIGABRT double-free）。测试改为 `new FactorStatsDock()` 由 Qt
所有权树接管——与 MainWindow 真实接线的所有权形态一致。

## D7 不移植 uncertainty 行、不做样式系统

`GridStatistics`（C++/Python 两侧）没有 uncertainty 字段；工作站的「不确定性」行来自
kriging 方差网格的 live 缓存摘要（shell.py:1000-1008），不属本切片验收（min/max/mean/
valid_count）。设计系统（tokens/style.bind/ratchet）是 Python 侧机制，C++ 侧尚无对应物；
本切片只取其语义（只读、可选中文本、诚实的 "—" 回退），不提前发明 C++ 主题机制。

## D8 逐步骤验收映射

* §7.1 清单 → `docs/development/cpp-ui-panel-inventory.md`（132/132，含策略统计与 M10 顺序建议）。
* §7.2 dock → `factor_stats_dock.{hpp,cpp}`（读 GridStatistics，QLabel 展示）。
* §7.3 测试 → `tests/cpp/platform/factor_hud_test.cpp`（构造统计→控件文本含冻结数值，11 案例）。
* §7.4 不重做 133 个页面 → 只落第一簇；其余在清单中逐文件裁定。
* §7.5 三轮审核 → 账本 R7-R9（subagent #2 spec 对抗 / subagent #3 Karpathy / 父代理清单漏文件专项）。
