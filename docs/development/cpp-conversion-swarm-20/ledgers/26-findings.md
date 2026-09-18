# 26 — findings：well-log native host 迁移事实与风险

## Python surface 分类（本切片后）

| Python 模块 | 行数 | 分类 | C++ 去向 |
|---|---|---|---|
| `viz/welllog_engine_adapter.py` | 821 | **replaced / oracle** | `libs/visualization` well_log_document_plan（parity 对账）|
| `viz/well_log_track_layout.py` | 172 | **replaced / oracle** | `libs/visualization` well_log_track_layout |
| `ui/pages/well_log_canvas_panel.py` | 916 | **legacy**（交互语义已迁）| platform 测井 dock + `well_log_track_panel` |
| `viz/hosts/well_log_host.py` | 436 | **legacy** | `WellLogHostWidget`（C2 首片 + 本切片扩展）|
| `viz/well_log_load.py` | 423 | **partial** | LAS 解析/单位信封→engine；取消→`load_from_source` 每曲线检查点；LRU 缓存未迁（C++ 侧 document 为 retained 模型,无需同款缓存）|
| `viz/welllog_multi_well_adapter.py` | 558 | **python-only（待迁）** | engine 已有 `SetWellLayoutCommand`/`compose_multi_well_scene`/CrossWellOverlay,留待后续切片 |
| `ui/pages/well_log_prediction_page.py` | 928 | python-only | prediction 领域,由 CONV-RUNTIME 线（PR #1349）负责 |
| `ui/pages/well_log_track_settings.py` | 194 | **replaced**（对话框→dock 面板）| `well_log_track_panel` |

Python 文件均以注释/docstring 标注（replaced/oracle/legacy/partial）,未删除：Python 入口与 pytest 仍依赖。C++ 产品主链对以上对象零 import Python。

## 引擎能力实测（影响后续切片的硬事实）

- `SetDocumentCommand` 校验 axis `direction` 与坐标实测一致性：降序 LAS 必须显式 `AxisDirection::decreasing`,否则整文档被拒（无 diagnostics,只有 Result error）。
- `SetPresentationCommand` 只重建呈现：文档、viewport、selection 均存活——`apply_track_layout` 的语义基础（测试断言）。
- `prepare_for_export(document_id, aggregate_pixel_height)` + `SvgExporter::write` / `PdfSceneExporter::write(scene, snapshot)` 开箱可用;PDF bytes 以 `%PDF` 开头、字节确定性（无 CreationDate）。
- 2M 样本单曲线 load+select 全流程 ~85ms（offscreen llvmpipe,Release）——LOD/pyramid 为 retained,重提交成本可控。

## Oracle 基础设施事实

- `welllog_engine_adapter.py` 模块级只 import numpy/stdlib;`classify_depth_unit` 懒加载自 `paleo_workbench.workflow.well_science`（纯 stdlib）。但 `paleo_workbench/__init__` 拉起 `env_bootstrap`→geoviz→PySide6。fixture 生成器因此用 importlib 文件级加载 + 两个命名空间跳板模块,被测代码两件均为真实文件。
- Python `json.dumps(..., allow_nan=True)` 默认可吐 `NaN`/`Infinity` 字面量,nlohmann 不接受——fixture 输入侧以字符串 tag（"NaN"/"Infinity"/"-Infinity"）编码,C++ 测试同规则解码。

## 风险 / 后续

- `WellLogTrackPanel` 为 platform 侧薄胶水,Q_OBJECT 面板自身无单测（语义全部在 Qt-free 层测）;文件对话框路径人工验证。
- `python_repr_double` 本地实现的指数格式分支（>1e16 / <1e-4）仅在 fixture 覆盖的量级内对账;factor_host 的 canonical_json 有更完整实现,若两切片交汇应合并为共享工具（见 decisions D4）。
- interpretion 事件（interval_selected/marker_hit）为宿主侧派生契约（SelectionEventV1 之外的新 v1 事件）,跨面板复用时应保持 Qt-free 头 `well_log_events.hpp` 为唯一契约源。
- 与并行 PR 冲突面：`apps/paleo_workbench_platform/CMakeLists.txt`（PR #1347 也触碰）——本分支仅在其 WLE 块内加 1 行 `target_sources`。
