# 06 — Performance Baseline（V14-COMPILATION-PUBLISH）

机器：40 逻辑核 / 62 GiB；测试 `-O1`（直接编译）与 `-O2`（CMake Release）两档。所有断言为**结构性**（成本模型/调用计数/字节比），wall-clock 仅作健全性下限，不作为门禁。

## 渲染器（`composer_scale`，30 检查）

| 场景 | 断言 | 实测 |
|---|---|---|
| 100 元素文档 | 输出字节比 8–12×（10× 元素 → 线性） | 通过 |
| 1000 元素文档 | 同上（10× 于 100 元素） | 通过 |
| 50 元素文档 | < 1000 ms（健全性） | 远低于 |
| 100 条目图例 | swatch 数 = 100（每条目 1 rect + 1 label，线性）；无 N² | 通过 |
| 图例框增长 | `req_h` = 610.0（`max(h, 10+n·6)`，Python parity：不裁剪） | 通过 |
| 模板实例化 | < 50 ms；id 唯一且定形（`el_%010d`） | 通过 |
| 渲染确定性 | 两次渲染 byte 相等（预览缓存可按内容键控） | 通过 |
| grid 病态宽度 | 20000 线结构上界（w=1e7 不再产生 600MB 字符串） | 通过 |

## 导出

| 场景 | 行为 |
|---|---|
| 单次导出 | 渲染一次（`export_composition_page` 内一次 `render_composition_to_svg`）；QGIS 路径失败后才渲染 composer 引擎 |
| 像素预算 | `check_pixel_budget`（2e8 px）：5000×5000mm@600dpi 拒绝；A4@600dpi 接受 |
| 预览刷新 | 画布帧缓存 TTL 300ms（元素拖动/属性编辑期间复用，不重复 grab） |
| 批量导出 | `CompositionPanel::export_to` 为 headless 入口（无对话框），可被批量驱动 |

## 融合（`grid_seams`）

| 场景 | 行为 |
|---|---|
| pin 装载 | 一次目录 `resolve_version` + JSON parse（O(cells)） |
| current 装载 | 同上（目录优先，live resolver 次之） |
| decode | 单遍遍历 cells/axes；ragged 早退（不建部分网格） |

## 已知性能特征（登记）
- 组图导出为同步路径（GUI 线程）；A4@300dpi 的单页 SVG 渲染与 Qt replay 在百毫秒级。大页/高 DPI 批量导出应移入 worker（`export_to` 已是无对话框入口，迁移成本低）。
- QC provenance rail 每次注册全量重写 store（`persistent_catalog` 既有设计）；验收环反复 QC 时 store 线性增长（P2-9，登记）。
- `install` 帧缓存为函数局部静态 map，随窗口创建增长（P2-1：键为裸指针、无清理；已登记，修复建议 QPointer + 窗口生命周期收殓）。
