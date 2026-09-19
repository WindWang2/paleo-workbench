# UI-02 decisions — components + modelview + qgis_stack

## D1 — 三 target 分层（core / widgets / qgis）

`pwb_ui_widgets_core`（Qt-free）/ `pwb_ui_widgets`（Qt Widgets 壳）/
`pwb_ui_widgets_qgis`（QGIS 栈，仅 `if(TARGET Pwb::Qgis)` 构建）。沿用
job_runtime/ui_shell 的「Qt-free 核先进 _core、Qt 壳单独 target」先例，
并把 QGIS 依赖收敛到独立 target 走既有 SDK 准入模式（`Pwb::Qgis` 存在
才构建）。理由：Qt-free 核可被 oracle/无头 replay 直接对账；QGIS 面与
Qt-only 面解耦，无 vendor SDK 的配置仍可用前两腿。

## D2 — domain 依赖的自足核 + 收编待办

`facies_patterns` / `facies_taxonomy` / `epoch_switching` 的真身在
`paleo_workbench/mapping*/`（domain 迁移轨，不在 `ui/` 树、不属任何
UI-NN 切片）。在册部件（palette/eyedropper/timeline）import 它们。
UI-02 在 `pwb_ui_widgets_core` 放**自足语义核**实现这些部件需要的
子集，而非阻塞等待 domain 轨。**收编待办**：domain 轨迁移这两个模
块时，应收编/去重 `core/facies_*`、`core/epoch_switching` —— 本核是
「冻结 Python 语义的原生承接」，不是第二权威。此决策与 findings 缝
1/2 互引。

## D3 — map_chrome 共享帮助函数抽取

`canvas_shim.py` 的 chrome overlay 惰性 import `unified_map_canvas.py`
（UI-15 文件）的纯 paint 帮助函数。UI-02 把它们抽成 `map_chrome.hpp/
cpp`（只含自由函数，不含 UnifiedMapCanvas 部件）。**UI-15 移植画布时
直接复用 `map_chrome`，不重转这些帮助函数。** chrome ink 相对图体色
（非 app 主题）、CANVAS_* 交互色、device-pixel 尺寸的语义注释随代码。
见 findings 缝 6。

## D4 — destroyed 回调只记账，绝不进 QGIS（生命周期纪律）

`QObject::destroyed` 在控件/QGIS 子树半销毁时运行；此时调
`MapSession::close()` / `session_.reset()` / 任何 QGIS API 是 UAF。
`mark_disposed()` 只置 `shutdown_done_`/`canvas_destroyed_` 记账标志；
session 由析构体的有序 `shutdown()`（`session_->close()`）+ 正常成员
销毁负责。与 Python `_mark_disposed`「纯记账」语义及
apps/paleo_workbench_platform/main_window 的「session_->close() 必须
在成员析构前」先例一致。**测试期真实暴露（SIGSEGV/invalid free）后修
复** —— 非预防性改动。

## D5 — AsyncQuery latest-only 语义用 Qt 线程亲和实现，不强杀 worker

epoch 语义：提交即递增 epoch，协作取消前任务（`cancel` 回调 +
`requestInterruption`），迟到投递经 epoch 比对作废。**绝不强杀
native worker**（Python 同款）。`QObject::moveToThread` 只允许从
worker 当前线程推出 —— `push_worker_to_app_thread` 在 dying
`QThread` 上 DirectConnection 执行（#1057 教训）。宿主销毁未完成任
务 detach 到 `DetachedJobKeeper`（job_runtime 先例）跑完。worker 必须
无 parent 构造（`qFatal` 响铃，防 moveToThread 静默 no-op 留 run()
在 GUI 线程）。

## D6 — QgsMapCanvas extent 语义用容差而非边等值

`QgsMapCanvas` 对 set_extent 做 aspect-fit + 像素量化 —— 逻辑
extent 会被扩张保持中心（如 [10,10,50,40] → ~[9.98,10,50.02,40]）。
测试用 center/span 语义 + 容差断言（`_is_fitted_compatible` 同款
aspect-fit 容差匹配），不断言精确边值。

## D7 — modelview 差分语义忠实 Python

- `ObjectTableModel`：同键序 → `dataChanged`（保选择/滚动），键序变
  → `beginResetModel`。排序在模型侧重排**索引**不搬对象，
  `std::stable_sort`（Python `list.sort` 稳定序同款）。持久索引经
  stable business key remap（`layoutChanged` 时 Qt 不自动 remap —
  review P1-1）；重复键按序消歧（Python id()-序 dict 同款）。
- `reconcile_widget_items`：按键差分、identity 保持、仅必要时结构
  操作、被删 item 显式 `delete`（对齐 Python 对象生命周期）。
- `StableSelection`：跨 reset 按 stable key 存取选中（
  paged_asset_model.row_for_key 的推广）。

## D8 — tree_sync 落 Qt-free core，JSON 层消解为结构体

Python 经桥 `set_tree_change_callback` 收 JSON payload；C++ 里桥可
直接传结构体。但「坏 JSON/非 dict→空集不抛」「visibility 强转
bool」「rename 强转 str」「revision 门控过期回声」「结构变化才带
tree」语义**完整保留**为可测的解析层（`core/tree_sync`，不链 Qt）。

## D9 — DEFER 纪律：未迁移服务层注入 seam，不伪造

- `workflow.stratigraphy`（active_target_horizon /
  set_target_from_boundary）→ `HorizonIo` seam 注入。
- 图层管理器 → `LayerManagerSeam` 注入。
- `ui.style.current_density`（theme_manager.density.value）→
  `ui_context` 注入宿主 `ThemeService`（未注入时进程级惰性
  fallback 读同一持久化对）。
- `canvas_shim` 的 capability manifest 探测 → 原生恒可；不支持操作
  诚实 `native_tool_activation_failed`→回退 pan / commit 拒绝可感知。

原则（taskbook §3 DEFER-10）：依赖未迁移服务层的语义如实记
decisions，只搬已验证纪律，不伪造默认实现。

## D10 — 不接线、不删 Python、最小共享面手术

- 不动 MainWindow/AppContext/wiring（taskbook §2.2：接线是集成片）。
- 不删任何 Python（`不删 Python`）。
- 共享文件只两处最小追加：根 `CMakeLists.txt` 单行
  `add_subdirectory(libs/ui_widgets)`（platform 块，不新增 option）；
  `libs/qgis/CMakeLists.txt` 补 `if(TARGET Pwb::Domain)` 链（main
  预存缺陷修复，守卫式）。

## 已知非阻塞 nit（记录不阻塞 ship）

- `AsyncQuery` worker 的 `repr` 转义、check-then-act 微窗口属理论
  竞态，offscreen 测试不触发；记入 D5 语义注释。
- `map_chrome` 与 UI-15 的 unified_map_canvas 存在语义重叠面 —— 以
  D3 的「UI-15 复用不重转」收口，非真重复实现。
