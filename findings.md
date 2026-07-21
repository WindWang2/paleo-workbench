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
