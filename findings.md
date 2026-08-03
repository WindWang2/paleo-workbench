# Technical Findings & Project Architecture State

## 项目重构成果与架构图谱

经过 P1 – P4 四个阶段的整体重构，`paleo_workbench` 的依赖架构已彻底梳理清晰，消除了全部反向边与死代码。

### 1. 核心依赖层级（无环、单向下沉）

```
                     ┌───────────────────────┐
                     │   ui (Qt 界面/页面)    │
                     └──────────┬────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌───────────────┐       ┌───────────────┐       ┌───────────────┐
│     viz       │       │   workflow    │       │   resources   │
│  (可视化引擎) │       │ (任务业务流程) │       │ (格式解析/导出)│
└───────┬───────┘       └───────┬───────┘       └───────┬───────┘
        │                       │                       │
        └───────────────────────┼───────────────────────┘
                                ▼
                        ┌───────────────┐
                        │    mapping    │
                        │  (地图/几何)  │
                        └───────┬───────┘
                                ▼
                        ┌───────────────┐
                        │    project    │
                        │ (文档模型/存储)│
                        └───────────────┘
```

### 2. 模块下沉与精简明细

1. **`paleo_workbench/resources/preview_parsers/`**：
   - `models.py`: PreviewResult, PreviewMode, 格式常量
   - `table_parsers.py`: CSV, TSV, Excel, DAT 解析器
   - `well_log_parsers.py`: LAS, XML/WITSML 解析器
   - `seismic_parsers.py`: SEG-Y 解析器
   - `office_parsers.py`: PPTX, DFB, ZIP, SpreadsheetML, WLP 解析器
   - `document_parsers.py`: GeoTIFF, Markdown, JSON, Audio, HTML 解析器
   - `registry.py`: PreviewRegistry 查表注册表

2. **`paleo_workbench/ui/pages/` (Map Edit Subsystem)**：
   - `map_edit_factory.py`: 图形项（Facies, Well, Line, Label）创建纯函数工厂
   - `map_edit_draft.py`: 草图绘制状态机 (`MapDraftManager`)
   - `map_edit_snap.py`: 控制点吸附与候选点缓存 (`MapSnapManager`)
   - `map_edit_topology.py`: 拓扑检验、缝隙检测、重建与合并/拆分编排
   - `map_edit_scene.py`: 代码量从 1382 行降至 604 行

### 3. 测试覆盖率与兼容性

* **单元测试**：163 个测试文件 / 1109 个 Pytest 用例 **100% 绿色通过**。
* **兼容性**：100% 保留向后兼容门面，不破坏现有的单测及 monkeypatch 约定。

---

## WellLogEngine C++ 子系统（`well-log-engine/`）— #154 Phase B 发现（2026-08-01）

独立 C++ 子系统轨道（非 Python 重构）。分支 `agent/welllog-pdf-spike-185`。从交接文档接续 Phase A（已完成 review）。

### 架构发现

1. **Session 作为单一真相源（ADR 0024）**：`WellLogSession` 持有 document/presentation/viewport/crosshair/**selection** 命令 + `ViewEvent` observer。所有 UI 状态（viewport、crosshair、selection）都存于 session；`WellLogView` 与 `TableModel` 都是薄 adapter，读/写 session，不持有自身状态副本。新增 selection 完全沿用此模式（与 crosshair 一一对应）。

2. **Selection Set 数据模型（ADR 0024）**：每个 document 一条 selection，基于身份而非屏幕坐标——`SelectionState{document_id, sampling_axis_id, reference_depth_range, [first_row,last_row), document_revision, valid}`。不存 Display Depth / LOD 点 / 屏幕像素。

3. **Mapping 是纯 index projection**：depth-range↔row-span 通过线性扫描 axis 的原始 `BufferView`（零拷贝，复用 file-local `load_as_double`），处理 increasing & decreasing 轴。**无插值、无浮点近似 join、无 Display Depth 替换**（table-and-export.md §2.2/§4.1）。

4. **Document 替换安全 remap（ADR 0024）**：`SetDocumentCommand` 时若 selection 存在，尝试在新 revision 的同 axis 上 remap（轴存活且深度范围仍在轴范围内 → 重算 row span，保持 `valid`；否则 `valid=false` + 发布 `selection_invalidated` 事件，宿主必须停止使用）。

5. **GUI 线程跳转（ADR 0147）**：`WellLogView` 的 session event subscription 用 `QMetaObject::invokeMethod(QueuedConnection)` 把事件 marshal 到 GUI 线程；新 `selection_changed`/`selection_invalidated` 沿同一通路。signal 经现有 `signal_timer`（16ms）coalesce。

### 关键约束（不得违反）
- Core headers 不得含 Qt/Python/OpenGL token（`tests/cmake/check_core_boundary.cmake` 强制）→ selection 类型放 `session/session.hpp`（与 `DepthViewport`/`CrosshairState` 同层）。
- Table copy 始终读原始 Buffer，**不读 LOD**（table-and-export.md §4.2）。
- 超大选择不在 GUI 线程构造巨型字符串（Phase A 已实现 `default_clipboard_cell_limit` 守卫）。

### Phase A 遗留打包 bug（本会话发现并修复）
`welllog_table`（Phase A commit `d9ef433`）被 `welllog_qtwidgets` 链接且两者都在 install export set，但 `welllog_table` 自身从未加入 `install(TARGETS ... EXPORT WellLogTargets)`。cmake reconfigure 时报 "requires target welllog_table that is not in any export set"。原 build dir 因缓存目标集陈旧而掩盖了此问题。修复：加入主 install TARGETS 块。

### 测试规模
31/31 headless green（原 29；+`welllog.session-selection` 12 用例，+`welllog.qt-table-selection-sync` 8 用例）。3 个 env-blocked（`qt-widget`/`python.qt-embedding`/`qt.package.consumer`）需真实 GL / 非 conda libstdc++（`GLIBCXX_3.4.35` mismatch），与 #154 无关。

