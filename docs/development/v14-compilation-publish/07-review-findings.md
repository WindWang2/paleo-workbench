# 07 — Review Findings（V14-COMPILATION-PUBLISH）

两轮独立 review（架构/正确性 + 对抗/性能/生命周期），全部 P0/P1 已修复并回归；P2 部分修复、部分登记。

## Round 1 — 架构/正确性

| ID | 问题 | 处置 |
|---|---|---|
| P0-1 | dict-layer 路径静默丢弃 well/annotation/label 图层（合法 JSON 组图渲染空白而导出报成功 = 假成功）；oracle 57 用例恰好未覆盖这三个 layer_type | **已修**：移植 WellSymbolRenderer/AnnotationRenderer；registry 解析对齐 `renderers.py:776-798`；oracle 增 6 用例（63 用例/1351 检查全绿） |
| P1-1 | subtitle 用 `x or ""` 而非 Python 的 `.get(key, default)`（falsy-present 漂移） | **已修** + oracle 用例 `subtitle_falsy_text` |
| P1-2 | 失败路径抛异常逃出公共 API（导出无护栏，可终止 Qt 事件循环） | **已修**：`export_composition_page` 渲染段 try/catch → ok=false + 原因；`CompositionPanel::export_to` 与 install 编排同款护栏 |
| P1-3 | main_map 非数值 extent：Python 渲染空框，C++ 落占位文本 | **已修**（保持 route 3，空框无图层）；注释改为如实描述 |
| P1-4 | `record_export` 硬编码 `format:"svg"`、`generated_at:""`（账本造假） | **已修**：格式从产物路径推导 + `now_iso8601()` |
| P1-5 | `bound_map_elements`/`map_bound` 记录但从不读取（死状态 + 语义偏差） | **已修**：inset/profile 不再贴主图画布（仅 main_map）；绑定状态保留为用户显式绑定记录（frame seam 以画布内容为判据的行为在 02/03 文档化） |
| P1-6 | `closure_workflow.grid_seams` 在标准选项集不可构建（workflow_graph 双 add） | **已修**：`pwb_add_subdirectory_once`；已验证 linux-ninja + CPP_CLOSE_02 + CONV_17 全电池可构建可运行 |
| P1-7 | grid_seams 注释/契约与实现顺序不一致；缺 legacy inline 第三级 | **已修**：03-contracts 统一表述为「catalog artifact → live resolver → refuse」；legacy inline 分支未接（登记 08） |
| P2-1 | 帧缓存静态 map 无线程保护/无清理/裸指针键 | 登记（08）；当前仅 GUI 线程路径 |
| P2-2 | 头注释声称"all user text html-escaped"，实际颜色/样式属性未转义（与 Python 一致） | **已修**：注释更正为「文本节点转义；颜色/样式属性按 Python 原样透传，文档须可信」 |
| P2-3 | 图例条目读 `stroke_width`（Python 忽略，用 dataclass 默认） | **已修**：显式 items 的 stroke_width/stroke_color 不再读取（Python parity：默认 0.5/#333333） |
| P2-4 | dict-layer 标签不 strip | **已修** + oracle 用例 |
| P2-5 | `py_splitlines` 漏 6 个 Python 行分隔符 | 登记（08，概率低） |
| P2-6 | `histogram_data` bins 死分支 + 1e30 UB + 数值字符串被跳过 | **部分修复**：死分支移除、截断语义修正；数值字符串仍跳过（Python 接受）——登记 08 |
| P2-7 | `resolve_renderer` style.renderer 只认两个关键字 | **已修**：facies/well/annotation/label 关键字全映射 |
| P2-8 | 图例从快照派生时扁平化（每层一条） | 登记（08，seam 简化已文档化） |
| P2-9 | format 分派漏 `lstrip(".")` 全剥 | **已修**（while 循环剥所有前导点） |

## Round 2 — 对抗/性能/生命周期

| ID | 问题 | 处置 |
|---|---|---|
| P0-1 | 渲染器/导出内核违反 "never throws"：11 处未保护数字属性读取，畸形属性可终止进程（实测 11/12 例抛出并穿到 export） | **已修**（同 Round1 P1-2）：内核渲染段 + 面板 + 编排三层护栏 |
| P1-1 | grid 元素循环无上界（w=1e7 → 608MB/11.8s） | **已修**：20000 线结构上界 + scale 测试 |
| P1-2 | 页面像素 `long long → int` 窄化 → 静默空白预览 | **已修**：`composition_replay` 与预览路径钳制 + null pixmap 显示失败文案 |
| P1-3 | `record_export` 硬编码 svg 且被 save_json 复用（伪造溯源） | **已修**（同 Round1 P1-4）：格式从路径推导（.json → "json"） |
| P1-4 | `grid_for_task` pin 失效时静默回退 live resolver（击穿陈旧检测） | **已修**：pin 存在即拒绝回退 + 测试 |
| P1-5 | `workflow_rail()` 锁内返回引用、锁外使用（UAF） | **已修**：按值返回 shared_ptr |
| P2-1 | 帧缓存静态 map 无回收/地址复用串味 | 登记（08） |
| P2-2 | 颜色属性未转义（Python parity） | 注释已更正（Round1 P2-2） |
| P2-3 | `check_pixel_budget` 对 NaN/负 dpi 失明 → 1×1 "成功"导出 | **已修**：预算前拒非有限/非正 dpi（编排层） |
| P2-4 | oracle 测试近恒真断言（viewBox 析取项） | **已修**：删去蕴含析取项 |
| P2-5 | scale 测试时间门槛形同虚设 | **已修**：1000 元素用例纳入计时 |
| P2-6 | 负向测试缺口（畸形数字属性、病态 grid、NaN dpi 等） | **已修**：oracle 增 6 用例 + scale 增预算/格式拒绝 + export 护栏测试 |
| P2-7 | `record_export` any_cast 抛异常 | **已修**：指针形式 |
| P2-8 | INSET/PROFILE 嵌主画布整图 | **已修**（Round1 P1-5） |
| P2-9 | rail 每次变更全量重写 | 登记（08） |

## 结论
P0/P1 清零（含两个 P0）。P2 剩余项均为已登记的限制或有意识的 seam 简化，依据见 08-known-limitations.md。
