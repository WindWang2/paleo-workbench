# Findings: Paleogeography Workbench

## Phase 28 Review 核验（2026-07-17）

- reviewer 的两条 packaging 结论成立：`contour_draft_worker.py`、`thread_keeper.py`、`test_seismic_async_contract.py` 仍是父仓 untracked；engine gitlink 仍为 `dc321a5d`，所有 facade/jobs/topology/seismic API 只存在 dirty submodule。
- complex geometry 风险采用 fail-closed：现有 merge/split 算法只接受单 outer ring，短期强行扩展会扩大拓扑回归面；对 holes/MultiPolygon 在任何删除/命令 push 前拒绝并提示，保证零数据损失。
- preview、SEGY stale-result、preload I/O 三条需以行为测试验证，不能仅靠代码审阅。
- 用户已要求“全修改”，包含 reviewer 明确要求的 engine commit + parent gitlink；提交范围必须排除 `SCRATCH/` 与 5 个历史未跟踪 plan 文件。

## Phase 27 / Task 27.6：等值线与 SEGY 异步边界（2026-07-17）

- 等值线提取的正确状态边界是“后台读取 deep snapshot、GUI 提交 draft DTO”，而不是让 worker 修改 live `ProjectDocument`。worker 只计算 draft；`upsert + apply_to_map` 在 GUI 中作为短事务执行，因此运行期间发生的地图编辑不会被旧工程 clone 整表覆盖。
- contourpy 的单个 `cg.lines(level)` 是不可抢占的 C 调用，但 engine 在 generator 创建前、每个 level 前及完成后轮询 token；页面销毁超时则由 QApplication keeper 保活，结果另有 token + project identity 双门禁，不会落入陈旧页面。
- 固定 `(4,4,2)` 无法构成内存上界。SEGY worker 现按元数据和 `max_voxels` 推导三轴整数 stride，并验证 `prod(ceil(dim/stride)) <= budget`；loader 每个 inline 前检查取消，且 downsample cache 与 factor 绑定。
- SEGY loader 必须在创建它的 worker thread 的 `finally` 中关闭，成功 DTO 发射也在 close 之后。GUI 若需后续交互切片，会在接受 latest generation 后重新创建独立 loader；旧 generation 即使晚到也不会替换 `_meta/_loader/renderer`。
- `SeismicHost` 与 `VizAdapter` 不再同步解析文件：adapter 只解析工程引用/绝对路径，host 调度 `SeismicView.load_segy_async`。预测面板对 path-only payload 显示非阻塞 loading，并在 engine `segy_loaded` 后更新 shape/controls。
- QThread wrapper 不应以短生命周期 View 为 parent。SEGY 与 synthetic workers 由 engine application-lifetime registry 保活；view cleanup 只请求 interruption，不逐 worker 阻塞 GUI，application `aboutToQuit` 再用共享 5 秒 deadline 集中收口。
- `geoviz` facade gate 是显式 allowlist；新增 analytics/directional/jobs/topology API 后必须同步登记公开符号。该失败不是 deep import，而是测试契约未随 facade 扩展更新。

## Phase 27 / Task 27.7：全量门禁 DTW 性能根因（2026-07-17）

- engine 全量唯一失败不是本轮 GIS/线程回归，而是 cross-well DTW 1k 样本稳定为 1.04–1.06 秒，超过既有 1 秒产品预算；独立复现排除了全套资源争用和 editable checkout 指向错误。
- 热点是 banded DP 内约 50 万次 Python/NumPy scalar 循环。递推 `c[j] = d[j] + min(base[j], c[j-1])` 可严格改写为 min-plus prefix scan：令 `P[j]=sum(d[0:j])`，则 `c[j]=P[j]+min_{k<=j}(base[k]-P[k-1])`。使用 `cumsum + minimum.accumulate` 保持相同 DP/回溯矩阵语义并移除 Python 内环。
- 数值等价、shift/ref-depth、progress callback 与性能共 10 项 DTW 回归全绿；这不是放宽阈值，而是消除算法解释器开销。

## Phase 27 最终状态与验证结论（2026-07-17）

- Project path 单一真源为 `project.paths.resolve_project_path/relativize_path`：相对路径经 `resolve + relative_to(project_dir)` 拒绝普通 `..` 与 symlink 越界；明确绝对路径保留为外部资产。resources、artifacts、reference layers 的 save/open 均经过 ProjectManager 边界，DataPage/adapter 使用工程路径解析，不再让未相对化路径跨页漂移。
- `ProjectManager.save` 的 `updated_at` 只在 temp write + fsync + atomic `os.replace` 成功后提交到 live model。factor/contour worker 均计算 deep snapshot，并以 token + project identity 校验后在 GUI thread 做短提交；消除了保存观察半成品和旧工程结果反写两类 ISS-STATE 风险。
- root quiet 全套在修复后一次停于 57% 且 pytest-timeout 无节点输出；精确终止后，prep 单文件与相邻顺序均通过。改用同一 collection 的 `-vv + faulthandler` 后 997 selected 全部正常结束（993 passed/4 skipped），明确显示 prep、preview、thread keeper 节点均通过。因此该 quiet 停顿没有形成可复现产品缺陷证据。
- 页面 fade 在全套高负载下曾停在 0.999666；page-owned deadline QTimer 现在精确完成 1.0，并以 effect identity 防止快速切页旧 timer 清除新 effect。empty-map QC 的正确契约为缺 facies/wells/contours 三条 warning，旧 integration 的 1 条期望已更新。
- 最终门禁：root `993 passed, 4 skipped, 8 deselected`；engine `1027 passed, 2 skipped, 134 deselected`；compileall 与 root/engine diff-check 均为 exit 0，无 `QThread destroyed`、deleted-wrapper 或 modal teardown 告警。

## Phase 27 / Task 27.2：数学核心与有界插值结论（2026-07-17）

- Modified z-score 的正常分支严格使用 `0.6745 * (x - median) / MAD`。当 MAD=0 时，“全部置零”会漏掉少数偏离中位数的极端值；新定义为等于 median 的样本得 0，有限偏离得到带符号 `±inf`，因此现有 `abs(z*) > threshold` 判定自然生效。
- 砂地比核心已移入 engine 纯数学层：只接受有限数值、`H_t > 0` 且 `0 <= H_s <= H_t`，边界输出严格为 0 或 1。
- 异向距离保持北向顺时针方位角约定：`u = dx*sin(theta)+dy*cos(theta)`、`v = dx*cos(theta)-dy*sin(theta)`；`a/b` 非有限或非正现在直接拒绝，不再静默钳成 epsilon。方向趋势与 IDW 均按目标 cell 分块，避免全幅 `(H,W,N)` 中间矩阵。
- 断层屏障由严格 CCW 改为 orientation + on-segment 容差判定，端点接触与共线重叠均视为阻断；IDW 同时过滤 x/y/z 的 NaN 与 infinity。
- 大样本 LOO R² 验证固定最多 64 个等距确定性观测点，仍以其余全样本训练，将验证插值次数从 N 限制为常数；synthetic 基值改用 SHA-256，不再受 Python hash randomization 影响。
- `geoviz` cache codec 的 payload 类型顶层导入曾破坏 core-only import；FormationTop 与 DAT payload 类型已按实际 kind 延迟加载，恢复可选渲染包隔离。

## Phase 27 / Task 27.3：engine 拓扑不变量（2026-07-17）

- GeoJSON `MultiPolygon` 不能仅平铺为 `rings`：平铺后无法区分“第二个 outer ring”和“第一个 polygon 的 hole”。兼容方案是在 `FeatureRef` 保留 `geometry_type` 与 `polygon_ring_counts`，编辑算法继续使用平铺 ring 列表，I/O 边界按 counts 重建嵌套。
- 闭合 ring 的首尾坐标必须共享同一个 vertex id，而不是两个坐标相同但身份不同的点。builder 与 `add_feature` 现在都将 open input 规范为 `[v0, ..., vn, v0]`。
- 删除闭合端点时，首 occurrence 与 closing occurrence 是同一逻辑顶点。命令必须在排除 closing duplicate 的逻辑列表上删除，然后用新首点重新闭合；undo 还原完整 id snapshot，避免按坐标或数组位置猜测。
- ring 身份发生变化后，局部手工修补 edge index 容易遗漏首尾边与共享顶点。当前 delete 命令使用模型级索引重建以保证 `_edge_index/_vertex_to_features` 与所有 feature 一致；拖拽仍按 vertex id 原位更新，无需重建。

## Phase 27 / Task 27.4：workbench 多环 Thin Host（2026-07-17）

- compact `.paleo.json` 需兼容三种深度：单 ring、Polygon rings、MultiPolygon polygons→rings。normalized record 现在同时保留 legacy `coordinates`、显式 `geometry_type` 与标准 GeoJSON `geometry`，因此旧消费者不变，复杂几何不再被首 ring 截断。
- `QGraphicsPolygonItem` 无法表达 hole；Facies item 改为 OddEven `QGraphicsPathItem`，内部 canonical 形状统一为 polygons→rings→points。简单 Polygon 的 `coordinates()` 仍返回第一 outer ring以兼容既有 merge/split/topology API。
- 多环顶点编辑不能只用 `vertex_index`。handle 与 `RingEditCommand` 使用 `(part_index, ring_index, vertex_index)`，闭合首点仍由 ring primitive 同步 closing point；mouse preview、release commit 与 undo 都沿同一地址传播。
- C++ compact hit-test 仅支持 point/ring，复杂 geometry 必须显式绕过 native 单 ring payload，使用 outer-minus-holes / per-part 判定；否则不仅命中错误，还会把三层数组送入 `float(list)` 崩溃。
- 保存门禁现在结合逐 ring 自交诊断与 engine `validate_polygon_geometry` whole-Shape 校验，后者覆盖 hole containment、nested shell 与 MultiPolygon part 冲突。

## 3-Strike RCA：Task 27.5 running prepare teardown hang（2026-07-17）

### 三次证据

1. 全 `test_prep_well_table_worker.py` 输出 8 个通过点后不打印 summary，PID 409193 持续存活，精确 TERM。
2. 单跑 `test_running_prepare_shutdown_is_kept_and_stale_snapshot_never_commits` 在 test body/teardown 阶段不返回；PID 409571 主线程停在 Qt poll，精确 TERM。
3. 将 keeper 的 `finished→_release` 改为 queued relay 后，单测仍被外部 `timeout 15s` 终止（exit 124）。因此“仅因 keeper 在错误线程 deleteLater”不是充分根因。

### 已知不变量与排除项

- 基础 preview/import keeper 测试均能 adopt→release 并通过，keeper registry 的一般路径可用。
- Factor worker snapshot 直接运行测试通过，说明 `model_copy + FactorPrepareResult` 本身不死锁。
- hang 仅在 `PreparationPage + running worker + shutdown/adopt` 组合出现；没有断言失败，pytest-timeout 的 signal 也未能给出栈。
- queued relay 修复后仍 hang，不能继续对 deleteLater 顺序做无证据微调。

### 新策略（强制切换）

- 停止产品 mutation；使用外层 Python 启动 pytest，并在 5 秒后由 `faulthandler.dump_traceback_later()` 输出所有 Python thread 栈，定位阻塞发生在 `shutdown_workers`、`qtbot.waitUntil`、页面 teardown 还是 Qt signal handler。
- 若栈显示 GUI thread 在 keeper ownership wait：改为 GUI-thread `QTimer` reaper 轮询 `isFinished()`，测试等待稳定的 keeper signal/counter，不依赖 deleteLater。
- 若栈显示页面 teardown 重入 `shutdown_workers`：增加 idempotent shutdown state，并确保 adopted job 与 page 完全断连。
- 若栈显示 worker 未离开 blocked function：检查 test Event、token checkpoint 和 direct `thread.quit` 顺序，必要时用 worker `terminal` 单一信号统一收尾。
- 只有精确栈证据出来后才恢复代码修改。

### faulthandler 定位结果

- 5 秒 dump 明确显示 GUI 主线程阻塞在 `PreparationPage._on_prepare_failed` 第 247 行的 `QMessageBox.warning()` 模态循环；调用发生在 `qtbot.waitUntil` 处理 Qt events 时。
- shutdown/adopt 分支只断开了 `worker.completed -> page`，没有断开 `worker.failed -> page`。因此 worker 结束阶段任何异常仍能进入已取消页面，弹出无人关闭的 modal，并表现为“pytest/Qt teardown hang”。
- queued keeper release 无法修复此问题，因为 keeper ownership 不是阻塞源；第三次证伪是有效的边界收敛。
- 最终修复策略：adopt 前断开 completed/failed 与 page 的所有连接；页面 failure slot 以 active cancellation token 做 stale guard；异步失败改写页面状态文本而非模态 QMessageBox。keeper release queued relay保留，因其仍满足 QObject affinity。
- modal 修复后进一步暴露 keeper relay 类型错误：PySide `Signal(int)` 映射 C++ signed 32-bit，无法承载 64-bit Python object id，warning 明确显示 value exceeds limits。registry key 信号必须使用 `Signal(object)`，不能用 Qt int。

## 3-Strike RCA：Task 27.5 PreviewController terminal cleanup race（2026-07-17）

### 三次证据

1. preview 全域首轮在 cache rewrite 的 idle wait 超时（前 10 项通过）。
2. preview 全域第二轮同一点失败：29 passed / 1 failed；缩小的 5-test 顺序无法复现，确认累积调度竞态。
3. 将无 context lambda 改为 controller-owned queued signal 后，全域在 8 个用例后停滞并被外部 45s timeout 终止（124），说明当前 relay 时序反而丢失了 terminal cleanup。

### 当前最强假设与策略切换

- `_wire_thread` 先连接 `thread.finished -> thread.deleteLater`，后连接 queued terminal relay。queued relay携带 QThread/worker wrapper，可能在 GUI 处理 MetaCall 前 wrapper 已 DeferredDelete，导致 `_on_thread_finished` 不执行或参数失效，`_active/_jobs` 永久不清。
- 停止产品 mutation，先用 faulthandler 包装完整 preview，定位第 9 个用例的 wait 栈并捕获 pytest-qt Qt exceptions。
- 若证实 active/job 未清：移除 `_wire_thread` 中提前 `thread.deleteLater`；由 GUI-thread `_on_thread_finished` 在清状态、pump pending 后统一 deleteLater。必要时用 per-job QObject relay（receiver context 明确）而不是传 wrapper 的 class signal。
- 不再重复扩大 timeout 或随机 sleep。

### faulthandler 定位结果

- 第 8 个 `test_rescan_invalidates_inflight_preview` 卡在 `_wait_controller_idle`；teardown 随后明确报错：controller 的 `_jobs` 仍引用 thread，但 `thread.requestInterruption()` 抛出 `Internal C++ object QThread already deleted`。
- 这证明 deletion-order 假设成立：`thread.finished -> thread.deleteLater` 已销毁 C++ wrapper，而 queued controller cleanup 尚未清 `_jobs/_active`。
- 修复边界：保留 `thread.finished -> worker.deleteLater`（Qt worker-object推荐模式）；移除提前的 `thread.deleteLater`；在 GUI `_on_thread_finished` 完成状态清理和 pending 调度后再删除 QThread wrapper。shutdown 同时容忍历史 deleted wrapper，避免 teardown 二次异常。

## Phase 27 / Task 27.5：线程生命周期最终不变量（2026-07-17）

- 高负载 worker 输入必须是 deep snapshot，输出必须是 DTO；live `ProjectDocument` 只在 GUI slot 中、且 token 未取消并仍绑定同一 target 时提交。
- `quit()` 不能中断正在执行的 Python/C/NumPy函数。取消由 engine `CancellationToken` 表达，IDW/方向趋势每个 cell chunk 前 checkpoint；页面销毁时即使计算暂未返回，也只会延迟一个 chunk 后退出，stale result不会 commit。
- soft deadline 后不能清空最后引用或仅 `setParent(None)`。`DetachedJobKeeper` 挂在 QApplication 生命周期，持有 thread+worker 到 finished，然后在 GUI queued slot释放。
- terminal signal 的 Qt 时序必须明确：无 receiver-context Python lambda 可能在 worker thread执行；QThread wrapper 不能在 controller queued cleanup 前 deleteLater；import report必须先在 GUI handler apply/emit，再 quit thread。
- async error不得打开 modal QMessageBox：shell rebuild/pytest event loop中会形成无人关闭的嵌套循环。制备错误改为页面内非模态状态，shutdown断开 completed/failed page slots并用 token二次拒绝 stale 回调。
- media preload 先 stat，读取上限 64 MiB；避免后台 read_bytes + GUI decode 的双份无界内存峰值。

## 数据管理思维 (Data Management Mindset)

> 数据页不是「资源摘要卡片」，而是**工程级数据 / 成果 / 文件管理中枢**。后续任何数据页改动、导入链路、预览与性能优化，都先对齐这套思维。

### 1. 管什么（资产宇宙）

数据页管理 `ProjectDocument` 上**一切文件型资产**，不限于测井/地震：

| 类别 | 典型内容 | 模型落点 |
|------|----------|----------|
| **输入数据** | 测井 LAS、地震 SEG-Y、层位、井分层、时深、表格 | `resources`（`artifact_role`≈input） |
| **参考资料** | PDF/文档、影像、历史图件、WLP 等 | `resources`（document / image_reference / …） |
| **成果 / 导出** | 单因素图、预测结果、成图 PDF、导出物 | `export_artifacts` + 派生 resource |
| **异常** | missing / warning / failed / error | 同一表，状态着色 + 目录「异常」 |

原则：**一张表看全工程文件面**；目录按「角色 + 类型」切片，不是按 UI 装饰分区。

### 2. 项目登记 vs 磁盘真相

- 工程文件（`.paleo.json`）登记的是 **路径 + 元数据 + checksum**，默认**不拷贝**进工程目录。
- **导入** = 扫盘 / 选文件 → 分类 → **去重**（path 优先，checksum 次之）→ 写入 `ProjectDocument`。
- **移出项目** = 从工程登记删除，**绝不删磁盘文件**。
- **重新扫描** = 用磁盘刷新元数据；文件没了 → `status=missing`，记录仍在，便于补路径。
- **打开目录** = 定位源文件所在位置，方便外部工具编辑。

思维口诀：**登记可丢、磁盘不碰；缺失可标、源文件可找。**

### 3. 工作台隐喻（怎么用）

数据页是**文件管理器 + 多格式阅读器**，不是报表 dashboard：

```
[摘要条：就绪/计数]
[工具栏：导入 | 搜索 | 列设置 | 目录/阅读器开关]
┌────────────────────┬────────────────────┐
│  资产表（主工作面）   │  阅读器（选中即读）   │
│  虚拟滚动 / 筛选     │  有界预览，非元数据卡  │
└────────────────────┴────────────────────┘
  浮动「目录」          浮动「操作」
  （overlay，不抢宽）    （导入/扫描/移出/状态）
```

- **表 + 阅读器** 是第一视口；目录/操作是**可收起 overlay**，禁止再改回「三列固定卡片抢宽度」。
- **选中即读**：支持的格式立刻给出可读预览；不支持的给清晰 message，管理动作仍可用。
- **阅读器优先于元数据卡片**：元数据做 header/次要信息，主体是 PDF 翻页、表格预览、文本、图件等。

### 4. 操作闭环（用户心智）

1. **进工程** → 打开/新建 → 数据页反映当前 `ProjectDocument`  
2. **补数据** → 导入文件/目录（后台线程）→ 表 + 目录计数一次刷新  
3. **找数据** → 目录分类 / 搜索 / 列显隐 → 只动过滤视图，不读文件体  
4. **看数据** → 点行 → loading → 有界预览（cache 命中则秒开）  
5. **管数据** → 重扫 / 移出 / 开目录；状态与侧栏上下文同步  
6. **交给下游** → 测井/地震/制备/编图等页消费同一批 `resources` / artifacts  

数据页是 workflow 第一步（`data_check` / 数据管理）的**常驻中枢**，不是一次性检查表。

### 5. 预览边界（安全默认）

| 做 | 不做（数据页内） |
|----|------------------|
| 有界文本/表（行列表上限） | 全文件编辑 |
| PDF 按页阅读 | 深度 OCR / 全文检索引擎 |
| 图按视口缩放 | 批量缩略图流水线 |
| LAS / SEG-Y **有界预览**（LAS 曲线轨；SEGY 中剖面 + **滑条 scrub**） | 全道集体可视化、OpenGL 解释工作台（属地震预测/可视化页） |
| 失败降级 message | 崩溃或阻塞 UI |

深度可视化属于 **测井预测 / 地震预测 / 可视化页**；数据页只保证「认得、管得住、能预览到可用程度」。

### 6. 规模与响应（性能思维）

目标体感：**2000+ 行仍可滚、可筛、可切预览**。

| 路径 | 原则 |
|------|------|
| 表 | 虚拟 model/view；`data()` 永不读文件体 |
| 筛选 | 内存 `FilterIndex`；防抖搜索；不触发预览 |
| 预览 | 后台/串行队列 + generation；UI 线程 LRU；stale 丢弃 |
| 导入 | 后台导入；完成时 **一次** 批量 refresh |
| 生命周期 | page 销毁 / shell rebuild 时 shutdown worker |

成功标准是**体感流畅**，不是 CI 硬 latency SLO。

### 7. 与项目管理的关系

- **工程** 拥有资源列表；**数据页** 是编辑/检视该列表的主界面。
- new/open 会 rebuild `AppShell` → 新 `DataPage(project=…)`；数据状态以当前工程为准。
- 保存工程 = 持久化登记信息（含相对路径策略），不是打包全部二进制。

### 8. 决策检查清单（改数据页前先问）

1. 这是在**管理工程登记**，还是在做专用可视化？后者考虑别的页。  
2. 会不会**误删磁盘**？默认禁止。  
3. 会不会让**表/阅读器失去第一视口**（固定侧栏回潮）？禁止。  
4. 大列表/大切换会不会**堵主线程**？要有界、异步、可丢弃。  
5. 导入完成是否**一次刷新**？禁止逐条重绘风暴。  
6. 缺失/不支持是否**可解释**且管理动作仍可用？

### 9. 关键规格（按时间线）

| 文档 | 贡献的思维 |
|------|------------|
| `2026-07-06-datamanagementpage-design.md` | 工程级资产中心、目录分类、去重、非破坏删除 |
| `2026-07-07-datapage-ui-management-performance-design.md` | 阅读器主表面、有界预览 |
| `2026-07-09-data-management-page-redesign.md` | 工作台 + 浮动目录/操作、表\|阅读器 |
| `2026-07-10-datapage-ui-perf-optimization-design.md` | 2000+ 虚拟化、异步预览、缓存与导入批量刷新 |

---

## Project Architecture

- **Two repos:** `paleo_workbench` (root, business logic + UI shell) + `geo-viz-engine` (submodule, visualization rendering engine)
- **Tech stack:** Python 3.12, PySide6 6.6+, Pydantic v2, pytest+pytest-qt
- **Design system:** Standalone HTML prototype (`古地理图编制系统 (standalone).html`, 3.7MB minified bundle) is the single source of truth for UI. Colors/fonts/dimensions extracted via headless browser computed-CSS inspection.
- **数据管理思维：** 见上文「数据管理思维」——工程文件中枢、非破坏登记、表+阅读器工作台、有界预览、规模体感优先。

## Design Tokens (extracted from prototype)

### Colors
| Token | Value | Source |
|-------|-------|--------|
| Primary | `#1f6fe0` | Primary button, active accents |
| Accent | `#6f47cf` | Prediction, step 3 |
| Success | `#1f9d57` | Completion/success |
| Teal | `#0f93a4` | Step 2 indicator |
| Warning | `#c47e12` | Step 4 indicator |
| Coral | `#e2705b` | Step 5 indicator |
| BG Body | `#eef0f4` | Main content area |
| BG Header | `#f3f5f9` | Menu bar, header toolbar |
| BG Sidebar | `#ffffff` | Text sidebar |
| BG Search | `#eef2f7` | Search box, status bar |
| Rail gradient | `linear-gradient(#1f5fbf, #184c97)` | Icon rail background |
| Text Primary | `#28323f` | Main text |
| Text Secondary | `#7e8794` | Status/secondary text |
| Border | `#e2e6ec` | Card/sidebar borders |
| Error Red | `#dc2626` | Failed/missing indicators |

### Typography
- Family: `"PingFang SC", "Microsoft YaHei", system-ui, -apple-system, "Segoe UI", sans-serif`
- Base: 12.5px, Status: 11px, Nav label: 9.5px/500, Sidebar secondary: 10.5px

### Dimensions
- Menu bar: 36px, Header: 38px, Icon rail: 60px, Sidebar: 248px, Status bar: 24px
- Nav item: 46x46px, radius 8px. Badge: 30x30px, radius 8px
- Button radius: 5px, Card radius: 9px, Panel radius: 10px

## Prototype Navigation (9 pages)

The prototype has 9 icon-rail navigation items (initial screen inventory said 7, corrected after browser extraction):

1. 首页 (HomePage) — project dashboard
2. 数据 (DataPage) — multi-source data management
3. 测井预测 (WellLogPredictionPage) — well log + prediction
4. 地震预测 (SeismicPredictionPage) — seismic + prediction
5. 层序格架 (SequenceFrameworkPage) — sequence stratigraphy
6. 可视化 (VisualizationPage) — composite visualization
7. 制备 (PreparationPage) — factor map preparation
8. 编图 (MappingPage) — paleogeographic map
9. 成图审核 (ReviewExportPage) — QC and export

## Workflow Model

6 compilation steps (STEP_ORDER in `workflow/service.py`):
1. data_check → 数据管理 (blue #1f6fe0)
2. factor_map → 数据转换 (teal #0f93a4)
3. prediction → 制图数据制备 (purple #6f47cf)
4. map_compile → 沉积相预测 (amber #c47e12)
5. qc → 古地理图编制 (coral #e2705b)
6. export → 质控与导出 (gray #7e8794)

Step statuses: pending, ready, running, complete, warning, failed, skipped, mock

## Data Models

- `ProjectDocument`: meta, stratigraphy, resources, factor_map_tasks, prediction_tasks, compilation_runs, quality_reports, export_artifacts
- `ResourceItem`: name, path, type (well_log/seismic/horizon), format, status, crs, tags, source, parsed_summary, checksum, external, artifact_role
- `WorkflowStep`: step_type, status, required_input_resource_ids, produced_ids, blocking_issue_summary, provenance_summary
- `CompilationRun`: name, target_horizon, sequence_scheme_ref, status, workflow_steps

## Key Technical Decisions

1. **Icon rail uses QToolButton** (not QPushButton) with `ToolButtonTextUnderIcon` for icon-above-text layout
2. **Active state via QSS property selectors**: `setProperty("navItem", True)`, `setProperty("active", True)`, with `style().unpolish/polish` to force re-evaluation
3. **Icons extracted from prototype** as SVG files (stroke-based, 18-19px, `currentColor`, viewBox 0 0 24 24)
4. **Cards use inline stylesheet** referencing tokens (not global QSS) since they are page-specific
5. **SDD (subagent-driven development)** for all implementation: fresh subagent per task, review after each, final whole-branch review

## Browse Skill Notes

- Browse binary at `~/.claude/skills/gstack/browse/dist/browse` (NOT `gstack-backup`)
- standalone HTML is minified — use `js` command with `getComputedStyle()` for CSS extraction, `snapshot -i -c` for structure
- JSON return from `$B js` requires `JSON.stringify()` — `console.log` goes to browser console, not stdout
- Current model does NOT support image input — text-based DOM extraction only

## Errors Encountered

| Error | Resolution |
|-------|------------|
| JSON parsing failed on long Write/Bash content | Split into bash `cat >>` heredoc appends |
| SVG files written to wrong directory (`paleo_project/` instead of `paleo_workbench/`) | Moved files, deleted wrong dir |
| `empty_label` dangling reference in RecentActivityCard | Fixed: persistent label with show/hide instead of recreate |
| Status coloring dead code in ResourceTable | Fixed: apply `setForeground(QColor(status_color))` |

## PreparationPage (Phase 4) Notes

### Prototype 制备 Page Structure (3 panels)

Extracted from standalone HTML via headless browser:
1. **Left (单因素图清单)**: target horizon label + interpolation method combobox (克里金/IDW/样条) + "批量生成单因素图" button + 8 task rows (name + method/grid + status badge 已生成/待生成) + footer "已制备 6 / 8 个单因素图".
2. **Center (单因素图集预览)**: header "{horizon} 单因素图集（{method}插值 · 网格 50×50 m）" + 2-col grid of cards (factor name + value range + R²) + 沉积相概率体 + 初始岩相边界 preview placeholders.
3. **Right (初始岩相边界制备)**: probability threshold (0.55) + smoothing (中) + min area (0.5 km²) + participating facies chips + "生成初始边界并送入编图" button.

### New Tokens Added

- `TASK_STATUS_COLORS`: complete→SUCCESS, pending→TEXT_SECONDARY, running→PRIMARY, failed→ERROR_RED
- `TASK_STATUS_LABELS`: complete→已生成, pending→待生成, running→进行中, failed→失败
- `INTERPOLATION_METHODS`: ["克里金", "IDW", "样条"]
- `SMOOTHING_LEVELS`: ["弱", "中", "强"]

### Data Model Note

`FactorMapTask.method` from `create_mock_factor_map` is the literal string "mock" (not "克里金"). Displayed as-is — the method combobox and preview header will show "mock" for mock-generated tasks. A future task could map mock→display method.

### AppShell Integration Pattern (split-loop)

To insert a real page mid-stack while keeping index alignment with PAGE_NAMES, AppShell uses a split-loop:
```python
self.page_stack.addWidget(HomePage())        # 0
self.page_stack.addWidget(DataPage())        # 1
for name in tokens.PAGE_NAMES[2:6]:          # 2,3,4,5
    self.page_stack.addWidget(PagePlaceholder(name))
self.page_stack.addWidget(PreparationPage()) # 6
for name in tokens.PAGE_NAMES[7:]:           # 7,8
    self.page_stack.addWidget(PagePlaceholder(name))
```
This pattern will be reused as more pages gain real content.

### Errors Encountered

| Error | Resolution |
|-------|------------|
| FactorPreviewGrid defaulted grid metric to "—" instead of "50×50" (spec deviation) | Fixed: default "50×50" + regression test; found in task review before merge |
| Card had double padding (stylesheet + layout margins) | Fixed: removed stylesheet padding, kept layout margins (sibling convention) |
| BoundaryPanel labels drifted from spec wording (岩相阈值 vs 概率阈值 etc.) | Fixed: aligned to spec strings (概率阈值/边界平滑强度/最小图斑面积) |

## ReviewExportPage (Phase 5) Notes

### Prototype 成图审核 Page Structure (3 panels)

Extracted from standalone HTML via headless browser. QC-centric page:
1. **ActionHeader**: title (map horizon) + 3 buttons (运行检查/规则配置/导出检查报告) + rules chips row.
2. **QCIssueTable**: 检查项目/检查说明/结果说明 columns, one row per QC rule, result ✓通过/!警告/!待处理.
3. **ResultSummary**: 通过项 N/警告项 N/待处理项 N counts + advisory text + export artifacts list.

### New Tokens Added

- `WARNING = "#c47e12"` (standalone; previously only embedded as STEP_COLORS[3])
- `QC_RESULT_COLORS`: pass→SUCCESS, warning→WARNING, error→ERROR_RED
- `QC_RESULT_LABELS`: pass→"✓通过", warning→"!警告", error→"!待处理"
- `DEFAULT_QC_RULES`: 6 prototype rule names
- `RULE_DESCRIPTIONS`: maps BOTH Chinese prototype rule names AND engine rule keys (facies_polygons_present, target_horizon_present) to descriptions — bridges the engine's English rule IDs to Chinese display text

### Severity Mapping Decision

Engine (`run_basic_qc`) emits severity "warning"/"error". Prototype displays 通过/警告/待处理. Mapping chosen: warning→警告 (amber), error→待处理 (red, treated as needs-action). The advisory text "待处理项" reinforces error=needs-action. Counts are one-result-per-rule (matches prototype's 通过项 5 / 警告项 2 / 待处理项 1 semantics).

### Shared Helper Pattern (qc_helpers.py)

Final review caught a divergence bug: QCIssueTable (last-issue-wins) and ResultSummary (error-precedence) derived per-rule results independently, so they could disagree when a rule had multiple issues of different severities. Fixed by extracting `derive_rule_result(rule, issues) -> (severity, text, color)` in `qc_helpers.py` with error-takes-precedence semantics, called by both widgets. This pattern (shared derivation helper for cross-widget consistency) should be reused if future pages derive display values from the same source data.

### AppShell Integration (split-loop, continued)

Page construction now uses three segments to keep index alignment with PAGE_NAMES:
```python
self.page_stack.addWidget(HomePage())            # 0
self.page_stack.addWidget(DataPage())            # 1
for name in tokens.PAGE_NAMES[2:6]:              # 2,3,4,5
    self.page_stack.addWidget(PagePlaceholder(name))
self.page_stack.addWidget(PreparationPage())     # 6
for name in tokens.PAGE_NAMES[7:8]:              # 7 (编图)
    self.page_stack.addWidget(PagePlaceholder(name))
self.page_stack.addWidget(ReviewExportPage())    # 8
```

### Data Model Note

QualityReport carries rule keys that may be either Chinese display names (prototype) or engine keys (facies_polygons_present). RULE_DESCRIPTIONS maps both, so QCIssueTable's description column works for either source. The integration test confirms engine output renders descriptions correctly, not raw keys.

## Data Management Center Redesign Notes

### Current DataPage Limit

The current DataPage is a narrow resource-management page:
- `ResourceSummaryBar` displays readiness counts.
- `ResourceTable` displays five columns.
- `ActionPanel` contains import/convert buttons but they are not wired to behavior.

User clarified that the Data page should manage all project data, results, and files, and preview supported data types. This is broader than the current Phase 3 DataPage implementation.

### Existing Backend Pieces

- `scan_resources(root, project_path=None)` recursively scans files and creates `ResourceItem` records with name, path, type, format, status, source, `parsed_summary["size_bytes"]`, checksum, and external flag.
- `classify_path(path)` classifies LAS, SEGY/SGY, DAT variants, spreadsheets, documents, images, reference maps, WLP files, and unknowns.
- `ProjectDocument.resources` stores imported/reference resources.
- `ProjectDocument.export_artifacts` stores export outputs.
- `ProjectManager.save()` relativizes resource paths and export output paths.

### Design Decision

For the first Data Management Center implementation, keep the existing data model:
- Use `ProjectDocument.resources` for data/reference files.
- Use `ProjectDocument.export_artifacts` for generated export files.
- Use `ResourceItem.artifact_role` to distinguish input/reference/derived/export roles where needed.
- Store lightweight preview metadata in `ResourceItem.parsed_summary`.

Avoid introducing a new `ProjectFileItem` model until real usage proves the current model insufficient.

### Testing Gap

There are currently no standalone `tests/test_resources_scanner.py` or `tests/test_resources_classifier.py` files. The Data Management Center implementation should add direct tests for classifier, scanner, import service, dedupe, and preview strategy behavior.

### Implementation Notes

- Added direct classifier/scanner coverage in `tests/test_resources_classifier.py` and `tests/test_resources_scanner.py`.
- `DataImportService` normalizes paths against `project_path.parent` when a project path is available, so saved relative resource paths dedupe correctly against newly selected absolute files.
- Import reports separate `added`, `skipped_path`, `skipped_checksum`, and `warnings`; the UI can surface these counts without inspecting service internals.
- Preview strategy returns immutable `PreviewState` records and is intentionally metadata-only for heavy formats. Image resources expose an image path, but no image bytes are decoded in the strategy layer.
- DataPage now treats `ProjectDocument.resources` and `ProjectDocument.export_artifacts` as the two project-wide asset sources. Generated files are displayed as artifacts; derived resources can still be represented through `ResourceItem.artifact_role`.
- File dialog behavior is behind `_choose_import_files()` and `_choose_import_folder()` seams so tests can exercise import refresh without launching native dialogs.

## Data Preview Format Notes

- Text preview reads at most 8192 bytes and 20 lines.
- `txt` and `xml` use `PreviewState.mode == "text"`; `csv` and `dat` use `PreviewState.mode == "table"`.
- Binary-looking text-like files fall back to metadata-only with a safe-summary warning.
- Missing text/table/professional files return metadata mode with `"文件不存在"`.
- Image decoding is UI-only via `QPixmap`; `preview_strategy.py` returns only the image path.
- `DataDetailPanel` scales image thumbnails to fit a 220x160 preview area and shows `"图片预览加载失败"` for invalid images.
- PDF preview renders the first page to a thumbnail via `QPdfDocument.render()` and avoids `QPdfView` because the widget segfaulted under offscreen tests.
- PDF preview now keeps a `QPdfDocument` in a custom `PdfPreviewPanel`, renders the current page via `QPdfDocument.render()`, and exposes previous/next page controls instead of embedding `QPdfView`.
- Other heavy professional formats remain metadata-first until dedicated parsers/viewers are introduced: LAS, SGY, SEGY, XLSX, XLS, PPT, PPTX, WLP, and DFB.

## Data Page V2 Interaction Notes

- The lower data workspace uses `QSplitter` with catalog, asset table, and detail preview panels; the action panel remains fixed-width outside the splitter so buttons do not collapse.
- `DataDetailPanel` uses `setMinimumWidth(240)` instead of `setFixedWidth(260)`, allowing the preview panel to expand for PDFs and images.
- Data actions are non-destructive: `移出项目` unregisters resources but never deletes source files.
- `重新扫描` handles missing files by setting resource status to `missing` and preserving the project record.
- `TextSidebar` no longer uses the "上下文面板 (待实现)" placeholder. It renders page-specific context text for every AppShell page and receives live data counts from `AppShell.update_data_page()`.

## Project Management V1 (Phase 14) Notes

### Architecture Decision: Window-Level Controller

Per spec, project lifecycle logic lives in `PaleoWorkbenchWindow` (`app.py`), not a separate controller class. V1 scope is small enough (4 actions, no autosave/recent-projects/command-history) that a controller class would be premature.

### Shell Rebuild Pattern (critical for new/open)

When the active project changes (new/open), the entire `AppShell` is rebuilt rather than individually updating each page. This avoids stale references — `DataPage` and other pages are constructed from `AppShell.project` at build time, so a new project requires a new shell.

Decomposition:
- `_refresh_shell()`: tear down old shell (`removeWidget` + `setParent(None)` + `deleteLater()`), build new `AppShell(project=self.project)`, call `_apply_project_to_shell()`, re-add to layout.
- `_apply_project_to_shell()`: extracted from `__init__` — runs `set_project_name` + all `update_*` calls. Called by both `__init__` and `_refresh_shell`.
- `_wire_toolbar()`: connects the 4 HeaderToolbar signals to handlers. **CRITICAL**: called from BOTH `__init__` and `_refresh_shell`, because each rebuild creates a new `HeaderToolbar` whose signals would otherwise be dead. Guarded by `test_toolbar_signals_wired_after_refresh`.

### Non-Destructive Open (atomicity contract)

`open_project_path(path) -> bool` loads into a local var FIRST, then assigns `self.project`/`self.project_path` only after success. Any exception (JSONDecodeError, ValidationError, OSError) → return False, current project fully unchanged. This ordering is the airtight part — never assign self.project before load() completes.

### Extension Normalization

`save_project_as` normalizes the filename to end in `.paleo.json`: appends if missing, does NOT double-append if already present. Handles `"p"` → `"p.paleo.json"`, `"p.json"` → `"p.paleo.json"`, `"p.paleo.json"` → unchanged. Uses `Path.with_name()` so directory components are preserved.

### Dialog Testability Seams

`_choose_open_project` / `_choose_save_project` / `_show_project_error` / `_show_properties` are isolated private methods, monkeypatched in tests. NEVER instantiate real `QFileDialog`/`QMessageBox` in tests (would block CI). The path-based public methods (`open_project_path`, `save_project_as`) are the testable surface; dialogs are thin wrappers.

### Save Flow Amendment

`save_project()` final design: if `project_path` set → save there; else call `_choose_save_project()` and save to chosen path (or return None on cancel). This makes `_on_save_project` a one-liner. A Task 2 unit test premise ("returns None without dialog") had to be updated in Task 3 to monkeypatch the dialog — expected cross-task evolution.

### Baseline Lesson (geo-viz-engine deps)

07-06 接入 geo-viz-engine-backed pages (Seismic/WellLog/Visualization/Mapping) but did not declare the engine's heavy deps (scipy/segyio/pyqtgraph/PyOpenGL/matplotlib/shapely) in the main project. The engine's subpackages declare their own deps, but only get installed if each subpackage is `pip install -e`'d individually — they are NOT published to PyPI and the engine's top-level pyproject lists them as external deps that pip can't resolve.

Resolution: `requirements-geoviz.txt` lists all 8 subpackages in dependency order for `pip install -r`. The `pytest.ini pythonpath` makes tests work without installation, masking the gap. **Future pages adding geo-viz imports must ensure the subpackage is in `requirements-geoviz.txt` + `pythonpath`.**

## Data Page UI/Perf Optimization (Phase 15) Notes

### Architecture decisions (approved design Approach A)

- **Surgical only:** keep `DataWorkspace` (table | reader) + floating catalog/actions; no card-layout rollback.
- **Virtual table:** `QTableView` + `AssetTableModel` with `_filtered_rows: list[int]`. Never materialize thousands of `QTableWidgetItem`s. Column defs in `data_table_columns.py` to avoid circular imports.
- **FilterIndex:** pure category + substring filter over precomputed haystacks. Category semantics must match catalog (`全部` / role buckets / `异常` / `CATEGORIES` type map). Currently still imports `CATEGORIES` from `data_catalog_panel` (Qt panel) — purity nit for later.
- **Single model reset:** production path uses `set_assets_filtered(assets, rows, column_keys=...)` once per apply; avoid triple `beginResetModel`.
- **Preview pipeline:** UI-thread `PreviewRequestController` + generation tokens; `PreviewProvider.preview` is pure (no shared dict cache). Worker only builds `PreviewResult` dataclasses (no Qt widgets).
- **PreviewCache:** LRU 32 on controller (UI thread only). Key = kind, id, path, type, format, checksum, optional `(size, mtime_ns)` from `Path.stat()`. Type/format in key so rescan reclassification is a miss without model field changes.
- **Serial latest-only queue (post-review fix):** at most one in-flight `QThread`. Newer cache-miss requests replace `_pending`; superseded assets never start. Prevents unbounded concurrent LAS/SEG-Y work.
- **Shutdown:** `controller.shutdown()` on `DataPage.closeEvent` and `QEvent.DeferredDelete` so shell rebuild (`deleteLater`) does not destroy live threads.
- **Import path:** still one `_apply_import_report` → `update_state` → one table reset; does not rebuild reader for prior selection.

### Data page public contracts to preserve

- `DataPage.update_state(state, resources, artifacts=None)`
- Import / rescan / remove / open-folder
- `data_context_changed` payload (counts + selection + reader_mode)
- Toolbar search, catalog category, column settings
- Floating panels as overlays (not splitter children)

### Test patterns learned

- After selection via DataPage, **always** `qtbot.waitUntil` for reader mode (async). AppShell sidebar tests must wait before asserting `阅读器: text`.
- Tests that spin workers should `_wait_controller_idle` (jobs empty) before teardown.
- Import batch: assert `modelAboutToBeReset` count == 1, not just final row count.
- Rescan vs in-flight: gate first provider call with `threading.Event`, rescan, release, assert FRESH not STALE.

### Residual (non-blocking) perf notes

1. ~~Image/PDF still decode on UI thread after path-only async result~~ → **fixed**: worker `preload_media` loads image/PDF file bytes; small payloads kept in LRU (≤512KB); path-only cache hits re-read via `_MediaPreloadWorker`; UI only does QPixmap/QPdfDocument from bytes (Qt affinity). PDF structure parse/render still UI-bound (QtPdf not worker-safe).
2. `FilterIndex.rebuild` runs on every filter apply; could rebuild only when asset list changes (table path may already gate).
3. ~~Floating catalog tab does not sync toolbar check state~~ → fixed.
4. ~~Search haystack uses raw English type keys~~ → fixed (Chinese labels).

### Delivery trail

- Spec: `docs/superpowers/specs/2026-07-10-datapage-ui-perf-optimization-design.md`
- Plan: `docs/superpowers/plans/2026-07-10-datapage-ui-perf-optimization.md`
- PR: https://github.com/WindWang2/paleo-workbench/pull/1 (merged `bc8b68b`)
- Worktree used: `.worktrees/datapage-ui-perf` on `feature/datapage-ui-perf`

## Mapping Editor V1 + C++ core notes

- **Layout:** GIS shell (toolbar / layer tree / MapEditView / attribute table), not the old fixed three-column display page.
- **Edit path:** QGraphicsScene items; geometry ops via `map_edit_api` façade.
- **Native:** `map_edit_core` pybind11 module under `native/map_edit_core/`. Hot path preference; Python fallback always works. Install with `pip install -e native/map_edit_core`.
- **Document:** `line_features` / `label_features` on `PaleoMapDocument`; save draft writes memory document (disk via project save).
- **Post-V1 shipped:** facies polygon draft tool; geometry hit-test select; line/facies vertex edit; **图面预览** mode; **forced topology rebuild** (shared-node snap + adjacency), merge/split (shapely), CI `HAS_CPP`.
- **Out of scope still:** QGIS, full multi-page print cartography, advanced shared-edge topology constraints.
- **Preview mode notes:** `preview_payload_from_*` converts editor rings → GeoJSON Feature and wells → `{lng,lat}` for canvas; unsaved dirty scene geometry is preferred over document; edit tools disabled while preview on; sidebar shows `模式: 编辑|图面预览`.
- **Topology rebuild:** pure-Python shared-node clustering; merge/split prefer shapely; undo via `BatchVertexEditCommand` / `CompositeCommand`.
- **CI:** Ubuntu job installs pybind11, builds `native/map_edit_core`, asserts `HAS_CPP`, runs full suite offscreen.

## Visualization geo-viz adapter (Phase 17) notes

### Adapter boundary

- **`paleo_workbench/viz/` is pure** — no Qt widgets, no AppShell page construction. Allowed bridges only: `mapping_helpers.preview_payload_from_document`, prediction mock helpers (`well_log_data_from_prediction`, `seismic_volume_from_prediction`).
- **UI owns canvases** — `CompositeVisualizationPanel` hosts `WellLogCanvas` / `SeismicView` / `CrossWellWidget` / `PaleoMapCanvas`; adapter only produces `VizPayload`.
- **Soft failure contract:** `resolve` and `from_prediction` never raise into UI handlers; missing/corrupt/unreadable → `kind="message"` with human text. Message path **clears** well/cross-well/map so prior graphics do not linger (seismic has no empty-clear API).

### Bounds constants

| Loader | Constant | Default |
|--------|----------|---------|
| LAS | `MAX_CURVES` / `MAX_SAMPLES` | 12 / 2000 (stride long curves) |
| SEGY | `MAX_DIM` / product budget | 64 / 64³; set `payload.warning` when downsampled |

### Jump wiring

1. Data page: `supports_resource` → enable 「在可视化中打开」 → emit `open_in_visualization(VizRef)` with `source="data_page"`.
2. Window: `icon_rail.set_active(PAGE_INDEX_VISUALIZATION)` + `_switch_page(5)` + `VisualizationPage.open_ref(ref)`.
3. Visualization: `adapter.resolve(ref, project_or_stub)` → `load_payload` + `trace.update_ref`.
4. Refresh: `_reload_current` re-resolves `_current_ref`; if no ref, `update_state(prediction_tasks)` mock fallback.
5. Load priority (测井/地震): current `VizRef` → else prediction mock → else empty.

### Tests / packaging notes

- Monkeypatch dotted paths into `paleo_workbench.ui.pages.*` can fail because pages package uses lazy `__getattr__` — patch the imported module object instead.
- Jump tests must drain/shutdown data-page preview QThreads before teardown (offscreen abort risk).
- Tab identity in tests: prefer `tabs.tabText(...)` over hard-coded indices (古地理 may move).

## Multimodal Preview Formats (Phase B) Notes

### Pipeline Extension Pattern (confirmed)

The preview pipeline is a clean 3-stage chain; each new format adds exactly 3 touch points:
1. `PreviewProvider._build_preview()` — format-set dispatch branch (before TEXT_FORMATS/IMAGE_FORMATS), returns `PreviewResult(mode=..., <fields>)`.
2. `preview_widgets.py` — concrete render widget.
3. `DataReaderPanel.render()` — stack slot + dispatch branch (before message fallback).

The existing `PreviewCache` (LRU 32), generation-based invalidation, and off-thread media preload apply automatically. New modes only need preload extension if they carry file-bytes payloads (`geotiff` needed it for cache-stripped thumbnails).

### Dispatch Ordering (load-bearing)

`GEOTIFF_FORMATS` overlaps `IMAGE_FORMATS` (both contain tif/tiff) — GeoTIFF dispatch MUST precede IMAGE_FORMATS. GeoTIFF takes precedence; non-GeoTIFF tiffs fail rasterio → image fallback → same outcome. Similarly MARKDOWN/JSON/AUDIO all precede TEXT_FORMATS (`.json` was removed from TEXT_FORMATS to eliminate the latent ordering trap).

### Worker-Thread Safety Invariants

- ✅ Pure off-thread: markdown→HTML, json.loads, rasterio.open/read, Pillow PNG encode.
- ❌ UI-thread-only: QStandardItemModel population, QPixmap.decode, QMediaPlayer.setSource.
- Payloads crossing threads: strings (`rich_html`), Python objects (`json_payload`), bytes (`image_bytes` PNG), scalars (`media_path` path only — no media decode off-thread).

### GeoTIFF Triple-Fallback

`_geotiff_preview` has 3 independent failure paths all routing to `_image_fallback`:
1. `ImportError` (rasterio not installed)
2. rasterio open/read `Exception` (corrupt file, not a raster)
3. Pillow encode `Exception`
Each returns `mode="image"` + warning "地理元数据读取失败，仅显示图像" + raw file bytes.

### JSON Large-Array Lazy Expansion

`JsonTreePreviewWidget._build_row`: arrays >100 items → collapsed "[N items]" node storing the list in `Qt.ItemDataRole.UserRole` with 0 children. The `expanded` signal handler reads UserRole and populates children on first expand, guarded by a `rowCount()==0` check (idempotent). The full parsed payload always ships from the worker (5MB cap); only the tree-model rendering is lazy.

### GeoTIFF Cache-Strip Edge Case

`cacheable_result` strips `image_bytes` >512KB. A large GeoTIFF thumbnail exceeding this becomes path-only in cache; on re-select, `needs_media_preload` (extended for geotiff mode) re-reads bytes off-thread. Note: this re-read gets RAW TIFF bytes (not the decimated PNG), so `GeoTiffPreviewWidget` depends on Qt's TIFF image plugin for the thumbnail — metadata table still renders from cached `geo_metadata`.

### Known Upstream Warning

rasterio 1.5.0 + numpy 2.5: `dataset.read(out_shape=...)` emits a DeprecationWarning (numpy shape mutation). Harmless; will need a rasterio bump when numpy hard-removes the API.

## DEVONthink Three-Pane Layout (Phase A) Notes

### Layout Migration

DataPage went from `QGridLayout` + 2 FloatingPanel overlays (catalog top-left, actions bottom-right over a 2-way QSplitter) to a fixed 3-segment horizontal QSplitter: NavigationTree | DataAssetTable | RightColumn(vertical QSplitter: DataReaderPanel | InspectorPanel). Both splitters `setChildrenCollapsible(False)`.

### Category Contract Preservation

The critical invariant: NavigationTree emits the SAME category-name strings (`CATEGORIES` dict keys) that `FilterIndex._matches_category` consumes. `FilterIndex`/`AssetTableModel`/`DataAssetTable` source is untouched. The tree is purely a new view over the existing filter model. `CATEGORIES` was moved from `data_catalog_panel.py` to `filter_index.py` (its canonical semantic home) to resolve a circular import.

### Count Logic Extraction

`compute_category_counts(resources, artifacts)` extracted from the deleted `DataCatalogPanel.update_counts` into `filter_index.py`. Pure function, Counter-based. Both NavigationTree and (formerly) DataCatalogPanel consume it.

### Signal Rewiring (Task 5 integration risks)

Two bugs caught during integration:
1. **Signal double-fire**: legacy per-button `clicked.connect` lines remained alongside the new toolbar-signal connections → handlers fired twice. Fixed by removing the redundant per-button wiring.
2. **Reader-toggle direction**: `_toggle_reader_from_toolbar` keyed off `reader_panel.isHidden()`, but `set_right_visible` hides the parent `right_splitter` (which makes `reader_panel.isHidden()` return True even when it was "visible"). Fixed by keying off `right_splitter.isHidden()`.

### What was deleted

- `DataCatalogPanel` (replaced by NavigationTree)
- `ActionPanel` (buttons moved to DataToolbar)
- `FloatingPanel` (no longer used — fixed panes replaced overlays)
- Their tests (`test_data_catalog_panel.py`, `test_floating_panel.py`)

### Known display refinements (deferred)

- `reader_btn` labeled 阅读器 but hides the whole right column (reader + inspector). Relabel pending.
- 成果/参考资料/异常 group headers show 0 (no children — they're aggregate-only groups). Display refinement.
- `测井参考` (well_reference) type has no leaf in the tree (omitted from TYPE_LEAVES) — counted under 参考资料 aggregate but not individually clickable.
- Lost selection-status text (legacy ActionPanel.selection_status_label gone; inspector empty/populated state conveys selection instead).

## Concurrent Resource Scan (Phase C) Notes

### Why ThreadPoolExecutor (not Process/async)

- `stat()` releases GIL during the kernel call.
- `hashlib.sha256` is a C extension that releases GIL during hash computation.
- File `open/read` is I/O (releases GIL).
- So threads achieve real parallelism for both I/O and CPU portions. ProcessPool would add ResourceItem serialization overhead + spawn latency; asyncio wouldn't help the checksum CPU work.

### _process_file Extraction

The per-file loop body extracted to a module-level `_process_file(path, project_path, skip_checksum_over_bytes) -> ResourceItem | None`. Module-level (not nested) so it's independently testable and monkeypatchable. Stateless — all transitive helpers (classify_path, _checksum, relativize_path) are pure functions with no shared mutable state.

### Graceful Vanished-File Skip (behavior refinement)

stat OSError (file vanished between rglob and processing) → `_process_file` returns None → filtered from results. Previously this would raise uncaught, abortting the whole scan. The graceful skip is strictly safer. checksum OSError behavior is unchanged (sets checksum_error flag, still includes the resource).

### S5 Stress Validation

Env-gated (`DATAPAGE_STRESS_S5=1`, N override via `DATAPAGE_STRESS_S5_N`). At small N (100) thread-pool overhead makes concurrent slower than serial — expected and irrelevant (the win is at N=10000 with real checksums). The test asserts correctness only (count + order), prints both timings, no wall-clock gate — consistent with Phase 21's measurement philosophy.

### Phase C Scope Discovery

Original plan had 3 items (virtual scrolling, import concurrency, search debounce). Exploration revealed Phase 15 already shipped virtual scrolling + debounced search (measured non-hotspots: S1=4ms, S2=0.5ms at N=2000), and Phase 21 shipped checksum skip. The only real gap was serial scan — so Phase C became a focused single-improvement spec rather than a 3-part project. YAGNI applied: a real inverted index for FilterIndex was considered and rejected (linear scan fast enough at measured scale).

---

## 2026-07-16 — Full-project audit findings (Phase 22)

### Already fixed before this session (prior deep_audit)
- chart_engine `utils` import, `_well_names` init, seismic `setShading`/loader `f`, hash()-based colors, `nice_number` negatives, IDW empty → NaN, WellLog path cache / mouseMove.

### Fixed this session (high confidence)

| Severity | Issue | Fix locus |
|----------|-------|-----------|
| high | DTW paint `QPainterPath.DashLine` AttributeError | `geoviz_cross_well/correlation_layer.py` |
| high | Multi-ring polygon drag uses outer-ring index only → holes jump/(0,0) | `edit_commands.MovePolygonCmd`, `edit_engine` |
| high | `geoviz_map` ScreenPathCache ignores pan center | `geoviz_map/screen_path_cache.py` (port paleo `_zoom_center`) |
| high | Sonic integration labeled TWT but was OWT | `well_tie/calibration.from_sonic` ×2 |
| high | `_apply_curve_meta` dropped `unit` | `qpainter_builder.py` |
| high | Map draft save stripped prediction properties | `mapping/document_io.apply_features_to_document` |
| high | Reference layer paths not relativized on project I/O | `project/manager.py` |
| high | GDAL datasets never closed | `mapping/reference_layers.py` |
| high | SEGY preview double full-trace pass | `viz/seismic_load.py` single pass |
| high | Import QThread destroyed while running on shell rebuild | `data_page._shutdown_import_jobs` |
| high | Mapping `update_state` always load last doc + wipe dirty | preserve `prefer_id` + skip reload if same dirty doc |
| high | Document tree switch discards dirty with no prompt | Save/Discard/Cancel |
| high | Project save did not flush map scene | `app._flush_mapping_draft` |
| high | PaleoMapAdapter GeoJSON always empty FeatureCollection | serialize `layers`/`features` |
| medium | QC `StopIteration` / status never `error` | `workflow/qc.py` |
| medium | Non-atomic project write; stale `updated_at` | tmp + `os.replace` |
| medium | Closed-ring insert_vertex opened ring | re-close after insert |
| medium | factor_tasks never passed to mapping page | `update_mapping_page(..., factor_tasks=)` |
| medium | Line vertex cancel only restored facies | `FaciesPolygonItem \| LineItem` |
| medium | Media kept playing after leave preview | `MediaPreviewWidget.stop` |
| medium | Page fade left previous page at partial opacity | clear previous effect |

### Still open (backlog)

1. **Seismic Auto-Tie:** ✅ `SeismicView` connects `auto_tie_requested` → `current_seismic_trace` → `panel.auto_tie`; `synthetic_changed` → IL/XL overlay.
2. **Hidden layer hit-test:** ✅ `hit_test_at` / `_feature_item_at` skip layers with `layer_is_visible=False` (export still full).
3. **Demo draft append:** ✅ `compile_map_draft` replaces same-generator demo (stable id); user maps untouched.
4. **Path escape:** ✅ relative paths confined to project dir (`ProjectPathError`); absolute external still allowed.

### Architecture notes from audit

- Prefer **vertex-id maps** over positional lists for multi-ring topology commands.
- Screen-space path caches that bake `center_world` must invalidate on pan **and** resize.
- Shell rebuild via `deleteLater` must shut down **all** page-owned `QThread`s (preview + import), not only preview.
- Export adapters that write placeholders should either implement real geometry or surface explicit warnings (now: geojson real + warnings).

---

## Subproject boundary: geo-viz-engine

`geo-viz-engine/` is a **git submodule** of paleo-workbench and the **visualization algorithm + widget library** for the product:

| Layer | Owns | Does not own |
|-------|------|----------------|
| **geo-viz-engine** | SEGY/LAS/map/plot pipelines, `PreparedPreview`, QPainter/OpenGL widgets, slice scrub, DTW/colormap math | Project file lifecycle, DataPage catalog, import/dedupe |
| **paleo_workbench** | AppShell, project I/O, pages, `VizAdapter` wiring, sample pipeline | Low-level seismic/well-log render kernels |

Install: editable subpackages via `requirements-geoviz.txt` + root `pythonpath`. Prefer fixing viz bugs **in the engine**; workbench only integrates.

---

## 2026-07-16 — SEGY data-page slice scrub (Phase 23)

### Product intent

Data page SEGY preview is **bounded 2-D slices**, not full 3-D OpenGL. Users need to **scrub position** along the current axis without leaving the reader pane. Implementation is **engine-side** so any host of `SeismicPreviewWidget` gets scrub for free.

### Design decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Memory model | Keep middle-slice preload; scrub re-reads **one** slice from disk | Large SEGY cannot fit full volume in preview worker budget |
| Axis metadata | `SeismicAxisSpec(start, step, count)` on payload | Slider index → SEGY line/sample without re-inspect |
| Package boundary | `load_preview_slice` lives in **geoviz_seismic**, not engine-only | Widget must not import `geoviz` engine (layering) |
| Debounce | 80ms single-shot QTimer | Avoid open/read/close per mouse pixel |
| Failure | Overlay text `切片加载失败: …` | Reader stays up; no crash |

### UX

```
[Inline ▾]  [========●========]  Inline: 105
[ ProfileWidget heatmap…              ]
```

Mode change resets slider range from `axes[mode]`; preloaded middle position used when present.

### Interaction capability

`PreviewCapabilities.interactions` includes `slice_scrub` alongside `slice_switch`, `zoom`, `pan`.

---

## 2026-07-16 — Visualization modularization (Phase 24)

### Target architecture
Workbench **hosts** engine product surfaces; does not reimplement parse/render.

| Host | Engine widget | Load API |
|------|---------------|----------|
| WellLogHost | WellLogCanvas | `build_qpainter_tracks(load_las_preview(...))` |
| SeismicHost | SeismicView | `load_segy(path)` → fallback `load_demo(volume)` |
| CrossWellHost | CrossWellCanvas | multi WellLogCanvas via package API |
| PaleoMapHost | PaleoMapCanvas | `load_features` (edit stays MappingPage) |
| EnginePreviewHost | GeoVizPreviewHost | `GeoVizEngine.prepare/render` (DAT/plots/scrub) |

### Rules
1. Production imports: only `geoviz` facade names in allowlist.
2. Dual LAS/SEGY loaders removed: engine is single source of truth.
3. Composite panel must not grow domain logic — route payload to hosts only.

### Still deferred
- Wire composite export button to engine `export_*`
- Well-tie workspace tab
- Full SeismicView horizon/attribute project wiring

---

## 2026-07-16 — Module-by-module review (goal: find issues)

### Method
- Static AST boundary scan (workbench → geoviz facade only): clean
- Runtime smoke import/export/viz/qc: clean
- 3 parallel read-only reviewers: resources I/O · viz hosts · project/mapping/workflow
- Fix high-confidence bugs + **66 passed** focused suite

### Module scorecard

| Module | Status | Top issues (before fix) |
|--------|--------|-------------------------|
| **resources/import** | OK after enrich | Roles/summary good; UI must pass project_path (residual medium) |
| **resources/export** | Fixed | Inventory menu unwired; relative path not resolved |
| **resources/classifier** | OK | geojson/vector/csv |
| **viz/hosts** | Fixed | Stale tabs; seismic full-volume OOM risk; clear incomplete |
| **viz/adapter** | Fixed | False SEGY message; formation_tops alias |
| **ui/data_page** | Fixed | Import slots off UI thread; inventory; reclassify roles |
| **ui/visualization** | Fixed | project never wired; export registration dead |
| **app lifecycle** | Fixed | save ignored failed map draft flush |
| **mapping/document_io** | Partial fix | normalize_facies now keeps attrs; FaciesPolygonItem extras |
| **workflow/qc** | OK (prior) | residual: reports only append |
| **adapters/paleo_map** | OK geojson | residual: pdf/svg placeholder |

### Fixed this review pass
1. Wire 工程清单 export action
2. Import finished/failed → QueuedConnection (GUI thread)
3. `load_payload` always `_clear_all` before apply
4. SeismicHost prefers budgeted `load_demo(volume)`
5. `update_visualization_page(..., project=)`
6. `_flush_mapping_draft` returns bool; gate project save
7. `normalize_facies` + FaciesPolygonItem extras round-trip
8. formation_tops → well_stratification for engine prepare
9. Manual reclassify updates artifact_role/tags
10. export_service resolves relative asset paths

### Residual (not fixed this pass)
- Import/rescan still often omit real `project_path` from window
- Demo map generate without dirty prompt
- Reference layer offline status
- QC report append inflation
- SVG/PDF button enable gating by tab (tooltip only)
- Non-geojson PaleoMapAdapter placeholder formats
## 2026-07-17 系统级 GIS 重构审计（本轮启动）

- 用户授权全自动审计、重构与自愈，范围聚焦 `ProjectDocument`/`.paleo.json` I/O、层序格架页、数据制备页、编图页及 `geo-viz-engine` 核心边界。
- 根仓库当前位于 `main`（`0e86375`），启动时存在用户未跟踪内容：`SCRATCH/` 与 5 个 `docs/superpowers/plans/*.md`；本轮视为用户资产并保持不动。
- `geo-viz-engine/CLAUDE.md` 确认当前架构是 PySide6 单进程、独立可安装的 GIS/地质可视化包；重计算与专业解析向 engine 下沉符合既有包边界。
- 本轮遵循：先复现/取证，再提出单一根因假设；修复必须有失败测试；连续三次失败即在本文件做 RCA 并更换策略。
- 历史 Phase 22 已修复两项同类高危问题：engine `MovePolygonCmd` 由位置索引改为 vertex-id 映射，以及根项目 `insert_vertex` 保持闭合环；本轮必须用跨外环/洞环与首尾顶点回归测试重新验证，而不能仅信历史记录。
- 历史路径逃逸项标记为已修复（`ProjectPathError` 限制相对路径、允许明确绝对外部路径）；本轮重点核对所有资源、artifact、reference layer 与页面适配器是否统一经过同一解析入口。
- 现有 DataPage 线程设计目标是“单 in-flight + latest-only pending + generation 丢弃 stale + DeferredDelete/closeEvent shutdown”；审计应验证实际实现覆盖 preview、media preload、import/rescan 全部 worker，而非只检查主 controller。
- 初始路由检索发现当前测试明确断言 `len(tokens.PAGE_NAMES) == 10`，说明 PWF 头部仍写“9 页”的描述已陈旧；需以当前 `tokens.py`/`AppShell` 实现建立 10 页真实映射并同步文档状态。
- 发现多个线程实现入口：workbench 预览/导入/制备 worker，engine `geoviz_seismic.workers`、`SeismicView` 和 `geoviz_plots.interpolation.scipy_grid.InterpolationWorker`。其中 `SeismicView` 仅见到 `wait(500)`，需检查 500ms 后仍运行时的销毁行为。
- 断层屏障 IDW 的真实现位于 engine `geoviz_plots/interpolation/idw.py`；workbench `ConstraintLine(kind='break'|'direction')` 已有领域模型，因此重点是验证页面到 facade 再到该算法的完整调用链，而非重新实现公式。
- 10 页真实顺序已由 `tokens.PAGE_NAMES` 与 `AppShell` 对齐：新增第 6 页“地层对比”，随后可视化/制备/编图/审核索引整体后移到 6/7/8/9。`PAGE_INDEX_*` 常量已覆盖 0–9，但 `_setup_shortcuts()` 仍只注册 `1..9`，第 10 页“成图审核”没有数字快捷键；记录为 ISS-ROUTE-01。
- `ProjectManager.save()` 在构造 payload 和原子写入之前直接修改 `project.meta.updated_at`。若序列化、临时文件写入或 `os.replace` 失败，磁盘文件保持旧版本但内存时间戳已前移，违反“失败不改变内存状态”的事务语义；列入 ISS-STATE-01 根因候选。
- `ProjectManager` 已统一处理 resources、export artifacts、reference layers 三类路径，并用临时文件 + fsync + `os.replace` 原子提交；下一步核对 `project.paths` 对 `..`、symlink、绝对外部路径的精确定义。
- `project.paths.resolve_project_path()` 对相对路径先 `resolve()` 再执行 `relative_to(project_dir)`，因此普通 `..` 与指向工程外的 symlink 均会被拒绝；绝对路径按“明确外部资产”策略允许。该底层实现本身符合边界，剩余风险是调用方绕过它或丢失 `project_path`。
- AppShell 的 10 个页面构造顺序与 `PAGE_INDEX_*` 一致，窗口跳转到可视化/制备/编图均已使用常量；但测井、地震、层序的 update/widget helper 仍硬编码 2/3/4，属于新增页面后容易漂移的维护缺陷，应在 ISS-ROUTE-01 中收拢。
- `_switch_page(index)` 未显式校验范围，并直接访问 `tokens.PAGE_NAMES[index]`；正常 icon rail 信号受控，但公共/测试调用若越界可能形成负索引侧栏错配或 IndexError。可用同一条路由边界测试修复。
- 三条指定数学模型均已有实现与直接测试：MAD/砂地比在 `workflow/well_qc.py`，异向趋势在 `workflow/directional_trend.py`，IDW/断层屏障核心在 engine `geoviz_plots/interpolation/idw.py`。因此“Mock 痕迹”主要不是公式缺失，而是算法所有权分裂：MAD、砂地比、方向趋势和 orchestration 仍在 workbench `workflow/`，与“重计算收拢至 geo-viz-engine”目标不完全一致（ISS-ARCH-01）。
- `factor_interpolation.py` 对 IDW 通过 facade/engine 的程度尚需逐行确认；检索显示其运行时动态导入 workbench `directional_trend`，说明方向趋势当前肯定不是 engine 单一真源。
- MAD 公式常规路径严格等于 `0.6745*(x-median)/MAD`，非有限值保持 NaN；但 `MAD < 1e-15` 时对所有有限值统一返回 0。对于 `[0,0,0,100]` 这类“多数相同 + 极端异常”，MAD=0 却并非全相等，当前实现会把 100 错判为正常，属于 ISS-ALG-01 数据完整性缺陷。建议定义：等于中位数者 0，偏离中位数者按符号为 ±∞（从而稳定触发阈值），并用回归测试锁定。
- 砂地比常规边界正确：拒绝非有限、`Ht<=0`、`Hs<0`、`Hs>Ht`，有效输出自然落在 `[0,1]`。缺失任一厚度目前返回 `(None, 'ok')`，后续 MAD 会把无主值行标成 missing；语义虽分两阶段但结果可解释。
- 异向距离与趋势公式逐项正确：北向方位角旋转、`sqrt((u/a)^2+(v/b)^2)`、非负 `exp(-d^2)*q*b_i`、归一加权均已测试。风险在于 `directional_trend_grid` 一次分配 `(H,W,N)` 的 dx/dy/u/v/d/w 多个三维数组；N=2000、较大网格时会产生高峰内存，必须在 engine 化时按网格块计算并由 worker 调度（ISS-ASYNC-01/ISS-ARCH-01）。
- `directional_distance` 对负/零半轴直接夹到 `1e-15`，会将调用错误静默放大为极端距离；公开核心 API 应验证 `a>0,b>0`，配置解析层才负责回落默认值。
- engine IDW 也一次构造 `(H,W,N)` 的 dx/dy/dist/weights，并在断层开启时进入 Python 四重级循环（网格×采样点×断层段）；这是 N=2000+ 压测下的主要计算/内存风险（ISS-ALG-04）。
- `segments_intersect` 使用严格 ccw 判定，无法识别共线重叠、端点接触等 GIS 屏障常见情形；控制点连线恰好触碰 fault vertex 时可能错误穿透。需要健壮 orientation/on-segment 语义与数值容差测试。
- IDW 只过滤 `NaN`，不过滤 `±inf`，公开 engine API 可能把无穷坐标/值传播为 NaN/无意义结果；workbench 当前上游虽过滤有限值，但核心包不应依赖单一宿主防御。
- `factor_interpolation._leave_one_out_r2` 对 N 个点逐个重跑插值，至少 O(N²)，断层场景还乘以屏障段；N=2000 时不适合作为每次生成的同步完整质控。应在 engine 核心提供有界/向量化 LOO 或对大 N 做确定性抽样，并在 worker 中运行。
- `synthetic_sample_points()` 声称 deterministic，却用 Python 进程随机化的 `hash(factor_type)` 生成 base；跨进程结果会变化，影响 demo/snapshot 可复现性（ISS-REPRO-01）。
- 制备 worker 当前把**活的 `ProjectDocument` 引用**传入后台线程并直接 mutation；虽然注释要求页面期间不要访问，但 AppShell、保存、编图与其他页面没有全局读锁，因此后台生成与保存/刷新可并发观察半成品状态，属于 ISS-STATE-01/ISS-ASYNC-01 的核心竞态。正确边界应是 worker 接收不可变 snapshot，返回结果 DTO，由 GUI 线程一次性 commit。
- `PreparationPage.shutdown_workers()` 对正在执行纯 Python/NumPy 的 `worker.run()` 只调用 `thread.quit()`；quit 只能退出事件循环，不能中断当前长函数。`wait(3000)` 超时后代码仍无条件清空最后引用，存在 `QThread: Destroyed while thread is still running` 风险。现有测试只覆盖 idle no-op，完全没有 running shutdown 回归。
- `_on_contour_draft_requested()` 在 GUI slot 内直接同步调用 `compile_contour_drafts_for_project`，全图等值线提取明确仍会阻塞 GUI；不满足用户 N=2000+/全图等值线体感目标。
- 当前异步生成没有 cancel token、generation/project identity 校验。若 shell rebuild/new/open 发生在旧 worker 完成前，即便线程未崩，也可能把旧工程结果写入不再可见的 project 实例并触发已销毁页面 slot。
- DataPage preview 的正常路径设计较好：asset 深拷贝 snapshot、单 active/latest pending、generation 丢 stale、worker 只传纯数据；但 shutdown 的“最后兜底”仍不安全。超时后 `_jobs` 被清空、`_active=None`，而 QThread 是 controller 的 child；controller 随页面销毁会删除仍运行的 child thread，注释所称“leave OS thread”与实际所有权矛盾，仍可能触发 QThread destroyed race（ISS-THREAD-01）。
- Preview worker 的 interruption request 没有被 provider/engine 重计算路径轮询，因此 `requestInterruption()` 当前基本只是标志，不能终止 LAS/SEGY/GeoTIFF/磁盘读取。需要把 cancellation token 贯穿 engine prepare API，或使用可安全脱离页面且全局托管到 finished 的 job owner。
- `preload_media()` 对 image/GeoTIFF/PDF 直接 `Path.read_bytes()`，没有文件大小上限；大 PDF/栅格会在 worker 内一次性占用整个文件大小，随后还可能在 Qt 解码阶段复制。虽不堵 GUI 读盘，却仍是内存峰值/泄漏体感隐患，应改为 provider 先做有界预览 payload，禁止通用整文件 preload。
- DataPage import shutdown 同样在 `wait(5s)` 超时后 `setParent(None)` 并清空唯一 jobs 列表，没有持久 owner 保证 thread/worker 存活到 finished；这是另一条 QThread 销毁竞态。导入任务使用纯 snapshot 并在 GUI 线程 apply，状态模型比制备更安全，但生命周期仍不闭合。
- 现有 preview lifecycle 测试只模拟 0.2 秒 worker；即使配置 1ms soft wait，内部 hard-cap 仍有 2 秒，故线程总能在页面删除前结束。它没有覆盖“provider 超过 hard-cap/不响应 interruption”的真正失败分支，无法证明 shutdown 安全。
- engine `SeismicView.cleanup()` 对 `_segy_worker`/`_synth_worker` 仅 requestInterruption + wait(500)，不检查 wait 返回、不保留到异步完成、也未在检索中发现 worker 主动轮询 interruption；这是 engine 内独立的 QThread 销毁竞态（ISS-THREAD-01）。
- `SeismicView.load_segy()` 是同步兼容 API，直接 inspect + `get_volume_downsampled(factor=(1,1,1))` + 三切片读取 + renderer load。若 Thin Host 在 GUI 线程调用它，会同时造成全体积内存和 UI 阻塞；需要核对 host 路径并限制该 API 或改用有界异步 load spec。
- `SeismicHost.apply()` 通常优先使用 adapter 的 budgeted volume，但当 payload 只有合法 `seismic_path` 时会在 GUI 线程调用上述同步 `load_segy()`；因此危险 fallback 是真实可达路径，不只是遗留 API。
- `load_segy_async()` 在已有 worker 运行时只 disconnect 回调，不 requestInterruption/wait，也立即覆盖 `_segy_worker` 引用。旧 worker 仍以 view 为 parent 继续读盘；快速连续打开多个 SEGY 会并发多个重载、增加内存/句柄峰值，并在 view 销毁时留下无法逐个 cleanup 的 child threads。
- `SegyLoadWorker.run()` 没有 `finally: loader.close()`；仅成功路径主动 close，inspect/volume/slice 任一步抛错都会泄漏 SEGY 句柄。worker 也完全不检查 `isInterruptionRequested()`。
- async worker 固定 factor=(4,4,2) 而不是按目标体素预算求 factor；超大地震体仍可能产生大 volume。回调还把 `_ds_factor` 误设回 `(1,1,1)`，导致后续原始/显示索引映射元数据不一致。
- Workbench 编图编辑器当前 schema **明确丢失多环**：`normalize_facies()` 对 GeoJSON Polygon 只取 `coords[0]`，holes 被静默抛弃；对 MultiPolygon 则层级识别错误，可能把 ring list 当 point list，随后 scene 构造失败/跳过。`apply_features_to_document()` 也只写单一 `coordinates` ring。
- `FaciesPolygonItem` 基于 `QGraphicsPolygonItem` 且只保存 `_coordinates: list[point]`，无法表达 holes/MultiPolygon；Move/Vertex/Batch 命令同样只接受单 ring 坐标数组。这意味着 engine 的 vertex-id 多环修复没有覆盖用户实际使用的 workbench 编图页，ISS-TOPO-01 是现存 P0，而非仅需复验。
- 当前 root `validate_ring`/重建/merge/split 只针对单 ring。即使 Shapely 能验证 Polygon，holes 与外环的包含/相交约束在进入 Shape 前已经丢失，形成“界面看似可编辑但保存破坏数据”的完整性风险。
- 修复方向：以 engine 可序列化 polygon topology（stable vertex ids + rings）作为核心，workbench host 使用 `QGraphicsPathItem` OddEvenFill 表示外环/洞；最小兼容层同时接受 legacy 单 ring 与 GeoJSON Polygon/MultiPolygon，保存时保持原 geometry 层级。
- Engine `MovePolygonCmd` 的 vertex-id snapshot 确实覆盖 outer+holes，拖拽跳到 `(0,0)` 的历史根因已修复；但现有 `test_move_polygon_cmd` 仍只构造单外环，缺少真实 hole 回归，故历史修复没有强测试门禁。
- Engine ring 的闭合点复用首点同一 vertex id。`DeleteVertexCmd` 用 `list.remove(vertex_id)` 只删第一次出现：删除首/闭合 vertex 会留下末尾重复 id，而新首点不同，立即把闭合环打开。`EditEngine.delete_selected_vertex` 又用 `index(vertex_id)` 总命中首项，因此该破裂路径真实可达（ISS-TOPO-01）。
- `TopologyBuilder` 对 MultiPolygon 直接 flatten 所有 polygon rings，`TopologyModel.to_geojson()` 又一律输出 Polygon；多个独立外环会被错误解释成一个外环加 holes，导致 Shape 语义与面积/包含关系冲突。需要在 FeatureRef 保存 polygon part 分组，或明确拆成稳定子 feature，不能扁平化。
- Builder 不主动补闭合、`to_geojson` 也不强制首尾一致；任一命令或脏输入打开 ring 后可直接持久化无效 GeoJSON。核心 mutation 应执行 closure invariant，并在 commit 前做 Shapely/纯 Python 结构校验。
- Root `MapEditScene` 的 vertex state 只有单一 `vertex_index`，`refresh_topology`/save gate/forced rebuild/merge/split 全部读取 `item.coordinates()` 单 ring；因此多环支持必须贯穿 handle 地址、命令 payload、渲染和 I/O，不能只修 normalize 函数。
- 2026-07-17 全量 offscreen quiet 基线复现历史 Qt stall：进度到 51% 后无节点/无 timeout 诊断，持续 3m26s；这类 quiet 单进程命令不能作为开发循环的唯一门禁。后续用 focused 测试推进，最终以 `-vv --timeout=60` 获取节点级证据。
- `geoviz` facade 已用 lazy `_COMPATIBILITY_EXPORTS` 暴露 `interpolate_idw/scipy`，新增 MAD/砂地比/方向趋势纯函数可沿同一机制公开；workbench wrappers 无需 deep import，符合现有 independence contract。

### Phase 28 调用链核验（Review 修复）

- `MapEditScene.merge_selected_facies()` 与 `split_selected_facies_by_line()` 在执行删除命令前均调用 `FaciesPolygonItem.coordinates()`；该兼容接口只返回首个 Polygon 的首个外环，因此带洞 Polygon / MultiPolygon 必须在原操作进入前 fail-closed，不能继续沿用旧 ring 算法。
- 编辑器 `to_record()` 已输出完整标准 `geometry`，但 `facies_to_geojson()` 对非 Feature 记录优先读取紧凑 `coordinates`，这是预览丢洞与 MultiPolygon 嵌套列表进入 `_close_ring()` 的直接根因。
- `SeismicHost.clear()/apply(volume)` 和 `SeismicViewPanel._show_empty()/_show_volume()` 未统一使异步 SEGY generation 失效；仅关闭 `_loader` 不能阻止仍在运行的 worker 回调覆盖新视图。
- `preload_media()` 在判断 mode 与已有 bytes 前执行 stat/open/read，导致文本、表格、地震等非媒体结果及已有缩略图的 GeoTIFF 仍发生无效读取。
- 修复策略：复杂几何旧操作明确拒绝且保留原对象；预览优先完整 geometry；在 engine 暴露统一 pending-load 取消入口并由所有非文件视图切换调用；媒体预载先做模式/载荷守卫。
- 现有测试落点已确认：复杂 merge/split 可扩展 `test_map_topology_rebuild.py`，完整几何预览可扩展 `test_map_preview_mode.py`，预载守卫可扩展 `test_preview_async.py`；engine 已有 stale-generation worker 测试，可直接补“切换 demo/取消后旧结果无效”契约。
- Engine `SeismicView.cleanup()` 已有 generation/interrupt 逻辑但不是可复用视图切换 API；`load_demo()` 完全不取消 pending SEGY，`load_segy_async()` 则重复手写关闭/中断。应抽取公开 `cancel_pending_segy_load()`，让 demo、同步/异步文件加载和 cleanup 共享同一生命周期边界。
- Workbench `SeismicHost` 当前直接读写 engine 私有 `_loader`，既未覆盖 worker，又违反 Thin Host；修复时删除该私有耦合。`SeismicViewPanel._show_empty()` 因不调用 `load_demo()`，需显式调用公开取消 API。
- RED 首跑在产品实现处已出现至少两项预期失败；但 `Path.stat` 的全局 monkeypatch 同时破坏 pytest 自身 `Path.exists/is_dir`，产生 INTERNALERROR，须改成“仅目标 path 抛错、其他路径委托原实现”。Engine 命令需在 `geo-viz-engine/` 工作目录执行。
- 可信 root RED：`7 failed, 42 passed`。失败精确覆盖完整 editor geometry 被忽略、complex merge 未拒绝、4 种 preview guard 仍构造 Path、panel empty 未取消 pending load；没有出现测试夹具内部错误。
- Engine 从父仓直接 collection 缺少 `geoviz_seismic` package path；需在子模块 cwd 运行其 pytest（与 Phase 27 engine gate 相同）。
- Engine 自带 `.venv/bin/pytest`，README 明确要求激活该 venv；系统 pytest 即使在 engine cwd 也无法导入 workspace packages。后续所有 engine gate 统一使用 `.venv/bin/pytest`。
- Engine `.venv/bin/pytest` 脚本 shebang 仍指向迁移前路径，不能直接执行；`.venv/bin/python` symlink 有效，Phase 27 记录的真实入口为 `.venv/bin/python -m pytest`。
- Engine RED 最终可信：`1 failed, 3 passed`，`load_demo()` 后 stale worker 的 `interrupted` 仍为 false，直接证明旧异步结果可覆盖 demo/volume 状态。
- GREEN 结构已落地：`SeismicView.cancel_pending_segy_load()` 成为唯一 generation/worker/loader 边界，load_demo、同步/异步 SEGY 与 cleanup 复用；workbench host 不再访问 `_loader` 私有状态。
- Focused GREEN 无回归：root 相关 map/preview/seismic 四文件 `49 passed`；engine seismic workers `4 passed`。本轮产品修复未产生 strike。
- Version-control 核验仍显示 reviewer packaging 风险尚未收口：root 三个必需文件与 engine 多个 API/测试文件仍 untracked，父仓 gitlink 仍为 `dc321a5d`。无关 `SCRATCH/` 与 5 个历史 docs plan 必须继续排除。
- 本轮 diff 静态检查 root/engine 均无 whitespace error；workbench seismic host 已不再访问 engine `_loader`，生命周期边界仅使用公开 API。
- Phase 28 全量回归通过：root `1000 passed, 4 skipped, 8 deselected`；engine `1027 passed, 2 skipped, 134 deselected`。新增 7 个 root contract case 未引入既有回归，engine 总数不变是因 stale 场景扩展在既有 worker test 内。
- Engine 已形成独立可引用提交 `957cb3f5`（22 files，含此前 untracked jobs/analytics/directional/seismic tests）；父仓下一提交必须记录该 gitlink，clean checkout 才能导入 `CancellationToken` 等 facade API。
- Parent code commit `540decc` 已记录 engine gitlink `957cb3f5`，并显式新增 reviewer 指出的 `contour_draft_worker.py`、`thread_keeper.py` 与 seismic async contract test；无关 scratch/docs 未入提交。
- Clean-checkout attempt 1 已成功从父提交检出并将 submodule checkout 到精确 `957cb3f5`；验证脚本因 `Path.cwd()` 仍是原仓而错误断言 import path，属于 harness 缺陷，worktree 已自动清理。重跑须通过环境变量传入 expected checkout。
- Clean-checkout attempt 2 全绿：`AppShell` 实例化成功，`geoviz.__file__` 明确来自临时 submodule，`CancellationToken/JobCancelled` 与两个新 workbench 模块均可导入；reviewer root cases `8 passed`、engine workers `4 passed`。临时 worktree 已清理，父 gitlink与 engine HEAD 都是 `957cb3f5`。
- 最终静态门禁：root/engine diff-check 与 compileall 均 exit 0。Reviewer 六项已全部形成代码、测试、提交及 clean-checkout 证据，Phase 28 可关闭。
- 最终合并 root+engine pytest 尝试因 engine 根目录的 `tests` package 遮蔽父仓 `tests` 而 collection error；这证明两套 suite 不应在同一 Python import namespace 混跑。恢复父仓标准入口后 reviewer root cases `8 passed`；engine 证据仍使用隔离 engine/clean-checkout 入口的 `4 passed` 与全量 `1027 passed`。

### Phase 29 PDF 预览诊断

- 环境正常：Qt 6.11.1，`PySide6.QtPdf.QPdfDocument` 与 `QtPdfWidgets.QPdfView` 均可导入。
- 工作区实际 PDF `geo-viz-engine/勘探管理图件图册编制规范.pdf` 为合法、未加密 PDF 1.6，44,610,769 bytes、248 页；`pdfinfo` 正常。
- `QPdfDocument.load(path)` 返回 `Error.None_`，pageCount=248、status=Ready，排除文件损坏与 Qt PDF 插件缺失。
- 初次 bytes 诊断显示 `QPdfDocument.load(QBuffer)` 返回 Python `None`；现有 `PdfPreviewWidget.load()` 将 `_load_document()` 返回值与 `QPdfDocument.Error.None_` 比较，故可能把成功的 QIODevice load 误判为失败。下一步确认 document status/pageCount 与 widget 状态。
- 根因确认：同一 QBuffer load 返回 `None`，但 document 为 `Ready / Error.None_ / 248 pages`；`PdfPreviewWidget` 随后却为 `_load_failed=True / 0 / 0 / PDF 预览加载失败`。错误发生在 `preview_widgets.py` 对 QIODevice overload 返回值的同步错误码假设，与 PDF 内容无关。
- Qt 6.11 官方 API 明确区分 overload：`load(QIODevice*) -> void`，`load(QString) -> Error`；document 提供 `statusChanged(Status)`、`status()`、`error()`。批准的修复必须围绕状态机，而不是给 `None` 打补丁。
- 隔离 worktree baseline：quiet `test_preview_async.py` 首次在 12 dots 后异常无输出并被人工 TERM；同 suite 使用节点级 `-vv --timeout=30` 随后 `30 passed in 6.04s`，未复现测试级失败。作为环境性 quiet-run stall 记录，不计产品 strike。
- TDD RED 使用 `QPdfWriter` 生成真实单页 PDF，读取 bytes 后删除源文件，强制 QBuffer-only 路径；document pageCount 已为 1，但 widget `_load_failed=True`，精确命中误判而非 fixture/文件错误。
- GREEN 状态机兼容两种 overload：path 的显式 Error 仍参与判断；QIODevice 的 `None` 被忽略，document status/error/pageCount 决定终态。Loading 时禁用翻页并等待 statusChanged；Ready 渲染，Error/零页失败。
- Focused 回归覆盖 82 个节点：真实 path/bytes PDF、QPdfView/fallback、fake document success/failure、revision reload、异步预载/缓存/线程收尾全部通过。quiet 多文件命令仍可在 teardown 无输出，`-vv` 同集完整通过，确认非功能回归。
- 用户实际 44,610,769-byte PDF 经新 widget bytes 路径为 `_load_failed=False / Ready / Error.None_ / 248 pages / 1 / 248`，真实场景已恢复。
- Worktree full quiet attempt 1 到 57% 后无节点信息停住并被 TERM；与两次 focused quiet stall 同模式。必须用 `-vv` full gate取得最后活动节点与可信最终结果。
- Full `-vv` 将停顿精确定位在既有 `test_datapage_stress.py::test_stress_s3_rapid_select`；该节点在全新进程 `1 passed in 0.51s`。说明长寿命 Qt 测试进程的全局状态污染/teardown stall，而非 PDF 修复或 stress 节点自身失败。最终门禁应分段运行 collection。
- Segmented full gate 前两区间通过：A（action→data）210 passed；B（datapage stress→pre-map）174 passed、8 deselected。每区间独立进程后 stress 节点与其后测试稳定完成。
- Segmented full gate 后两区间通过：C（map→pre-preview）188 passed、4 skipped；D（preview→末尾）429 passed。四区间合计 `1001 passed, 4 skipped, 8 deselected`，与 collection `1013 total / 8 deselected / 1005 selected` 精确守恒。
- Diff self-review 发现真实 PDF 只覆盖立即 Ready；新增可控 fake-document contract，要求 Loading 阶段保持 pending/非失败，并在 statusChanged(Ready) 后渲染。该测试锁定批准设计中的异步状态分支。
- 补强 contract 通过：真实 QBuffer Ready 与 fake Loading→Ready 共 2 pass；完整 preview widget 文件 16 pass。状态机即时与延迟两条路径均有门禁。
- Phase 29 implementation complete：产品 diff 仅 `preview_widgets.py`，测试 diff 仅 `test_preview_widgets.py`；其余为三份 PWF。无依赖、预算或 worker I/O 行为变化。
- `cf2676e` 已 fast-forward 合并到 main；合并态 focused 83 pass，实际 44.6 MiB PDF 仍为 Ready / None_ / 248 pages / 1 / 248。
- 自建 worktree 因含 submodule 元数据需先 deinit，再在已确认 clean 后 `worktree remove --force`；功能分支用非强制 `branch -d` 删除，现仅保留 main worktree。

### Phase 30 重复实现初步审计

- 当前 root `main` 的产品代码停在 `cf2676e`，PWF 收尾提交为 `39f7f9e`；只有既存 `SCRATCH/` 与 5 个历史 plan 文件未跟踪，本轮继续保持不动。
- 最大的可确认重复职责是 Qt 后台任务生命周期：`data_page.py`、`preparation_page.py`、`mapping_page.py`、`preview_worker.py` 和 engine `seismic_view.py` 均各自实现 QThread 创建、moveToThread、requestInterruption、generation/stale 丢弃、deleteLater 与 wait。现有 `thread_keeper.py` 只覆盖部分页面，尚未形成跨页面一致契约。
- 算法检索表明 MAD、方向趋势和 IDW 已有 engine 实现；workbench 仍有 factor orchestration、contour 编译与兼容调用。这里需要区分“必要的薄适配”与“重复算法”，不能按同名函数机械删除。
- 预览链存在两套 source revision/stat 生成：`fallback_preview.py::_revision()` 与 `preview_provider.py::_safe_stat()` / `_resource_revision_token()`；应核对 token 语义后再决定统一入口，避免缓存失效行为变化。
- 几何链至少包含 `mapping/geometry_schema.py::normalize_facies()`、`ui/pages/mapping_helpers.py::facies_to_geojson()` 与各 adapter；它们可能分别承担 canonicalization、展示转换和 I/O 兼容。需先画完整调用/数据契约再收敛，尤其不能重现 holes/MultiPolygon 降维问题。
- 大文件热点包括 engine `renderer_3d.py`（1807 行）、`seismic_view.py`（1575 行）和 workbench `map_edit_scene.py`（1381 行）。文件体积是审计信号，不等于功能重复；Phase 30 的成功指标应以职责单一、调用方减少和行为测试为准。
- 初步建议把“线程生命周期统一”作为第一批：重复证据最强、横跨多个页面、且直接降低泄漏/竞态风险；算法与几何需要更严格的兼容面审计后再动。
- 用户选择第一批处理线程生命周期（选项 1）。
- `DetachedJobKeeper` 当前只解决“页面释放后仍在运行的 QThread/worker 由 QApplication 托管”，不负责启动、信号连接、取消令牌、generation 或结果提交；可将它保留为底层最后防线，并在其上增加单任务 coordinator。
- Preparation 的 prepare job、Preparation 的 contour job、Mapping 的 contour job 三处重复保存 thread/worker/token/target，重复连接 terminal→quit、finished→deleteLater/clear，并在 shutdown 时重复 disconnect + wait + adopt。两处 contour 路径尤其接近同构，是最安全的首个抽取目标。
- PreviewController 的“单 in-flight + latest-only pending + cache/generation”是业务调度策略，不应被通用 runner 吞并；它只能复用底层 owned-job 生命周期原语，否则会把预览缓存状态与通用线程管理耦合。
- DataPage import 同样有多 worker 列表与页面级业务状态，适合第二步复用 shutdown/adopt 原语，不适合第一步强行改成 PreviewController 状态机。
- Engine `geoviz-seismic` 被明确要求是独立可安装包，不能导入 `paleo_workbench.ui.thread_keeper`。跨仓统一只能通过相同契约/engine 自有基础设施，或把真正通用且无 workbench 依赖的 runner 下沉到独立 engine 包；直接共享 workbench QObject 会破坏包边界。
- 现有测试已覆盖 prepare running shutdown、DataPage keeper、Preview blocking shutdown 与 contour off-GUI；Mapping contour shutdown/stale 的直接覆盖较弱，进入实现前需要先补契约测试。
- 用户确认采用 Workbench 优先边界（选项 1）：第一批收敛 Preparation、Mapping、Data、Preview 的共有生命周期原语，不修改 engine 包内部实现。
- 最终设计采用持久 `OwnedWorkerJob`，而不是 helper functions 或全局 scheduler：前者能集中状态和 identity 防护；后两者分别去重不足或过度统一业务队列。
- DataPage 当前虽用 `_import_jobs` 列表，入口通过 `_import_in_progress` 严格限制为单任务，因此可安全收敛为单 `_import_job`，不改变并发能力。
- DataPage 正常完成依赖 worker result 以 QueuedConnection 先提交 GUI，再由 `_finish_import_job()` quit/wait；通用 handle 必须保留结果连接顺序，不能在 thread.finished 过早清掉 target。
- Preview 的 `_thread_stopped` relay 与 `QTimer.singleShot(0, _pump_pending)` 是为规避 Shiboken teardown 竞态，迁移时必须保留“thread 真正停止后再 pump”的时序，而不只是替换字段名。
- Contour/Factor worker 将 CancellationToken 私有保存为 `_cancellation_token`；页面迁移后不应窥探该字段。业务槽以 `job.target is self._project` 判定当前结果，shutdown 则由 handle 先断开业务连接再调用 token.cancel，组合后覆盖原 token+target 双守卫语义。
- Preview teardown 暴露通用 handle 的 lambda 捕获风险：`thread.finished -> lambda -> self._thread_stopped.emit` 在页面/handle 已删除后仍可能执行。QObject bound slot 使用 QueuedConnection 才能让 Qt 在 receiver 销毁时自动断连，并保证 registry mutation 在 GUI thread。
- 静态去重结果：Data/Preparation/Mapping/Preview 四个目标文件已无 `QThread()`、moveToThread、requestInterruption、wait 或 keeper adopt；这些原语只在 `owned_worker_job.py` 单一实现中存在。
- 旧 `_prepare_*`/`_contour_*`/`_import_jobs`/Preview `_active,_jobs` 状态只保留在“属性必须不存在”的架构测试或测试名称中，没有产品兼容别名。
- Diff 自审显示 tracked 部分删 423/增 268；新增 handle 与两个测试文件尚为 untracked，最终提交必须显式纳入，避免重现 reviewer packaging 缺陷。
- Clean-checkout harness attempt 1 并未验证产品：Git 默认拒绝本地 file transport，submodule 未初始化；Python cwd 又解析到主工作区；脚本缺少 fail-fast 使末尾 worktree list 掩盖中间失败。必须使用 `protocol.file.allow=always`、显式 PYTHONPATH/cwd 和 fail-fast。
- Clean-checkout attempt 2 的产品门禁可信通过：本地允许 file transport 后 submodule 精确 checkout `957cb3f5`，AppShell/OwnedWorkerJob 从临时 checkout 导入，8 个 focused contracts pass，status 为空。普通 worktree remove 因 submodule 元数据 exit 128，但 EXIT trap 的精确 force-remove 成功，后续 worktree/path 独立检查 exit 0。
- 独立 reviewer 对 `13288e4..f86defc` 未发现 Critical/Important。唯一低置信 Minor 是 shutdown 捕获 RuntimeError 后视作 joined；该异常代表 Shiboken wrapper 已删除，线程对象已无法安全查询/托管，当前 defensive cleanup 与既有调用路径相符，接受而不扩展 API。
- Thread batch 实际收敛结果：四个页面删除各自线程原语，统一到 142 行 OwnedWorkerJob；tracked+new 总 diff 为 592 insertions / 428 deletions，其中大量新增来自测试/PWF，产品页面净删除显著。
- Merge-state standard full attempt 1 在约第 150 节点的 pytest-qt `_close_widgets` 发生原生 segfault（exit 139），无 Python 产品栈。collection 定位该区间位于 DataPage 尾部；DataPage 全文件独立进程随后 52 passed，且同一产品提交在 feature worktree full 1010 passed。当前根因假设为长寿命 Qt 进程的非确定性全局 teardown 污染，合并验证改用四段独立进程闭合集合。
- Merge-state segmented gate 四段均通过并精确闭合：211 + 174 + 194 + 431 = 1010 passed，另 4 skipped / 8 deselected。A 段包含导致 full attempt 1 崩溃附近的完整前序/DataPage 链仍通过，支持“非确定性长进程 Qt teardown 污染”结论，无需产品修复。
- Feature worktree 普通 remove 即使 submodule 未初始化仍被 Git 拒绝；在已确认 status clean、路径精确且为本轮自建后使用 `worktree remove --force` 成功。功能分支随后用非强制 `branch -d` 删除，最终仅 main worktree。
- 计划自审通过：选定范围的启动/取消/托管/stale/正常结果顺序均有 RED 契约；无 engine 或业务算法变更。
- 隔离 worktree 的首次 `submodule update --init` 失败：远端缺少父仓锁定的 `957cb3f5` 对象，但主工作区 engine 本地仓库拥有该 commit。已从精确本地仓库 fetch 并 detached checkout 到同一 SHA；这再次说明该 engine commit 尚未推送，属于 clean-clone 交付风险，但不改变 Phase 30 的 workbench-only 边界。
- Phase 30 组合 baseline 在约 70% 后复现既有 Qt quiet-run 无输出 stall；此前已通过 Phase 29 节点隔离证明该类问题来自长寿命 pytest Qt 全局状态，而非单节点确定性失败。本轮基线改为 Preparation/Mapping、Data、Preview、Stress 四个独立进程。
-
## Phase 31 — 跨页项目数据流设计（初始记录）

- 用户明确要求重点关注编图页和制备页的数据读入/输出，及其与 `.paleo.json` 项目文件、数据页项目数据之间的关联。
- 当前先将问题限定为一条端到端数据契约：原始资产登记、制备派生、编图编辑、成果导出与回流；需要以现有实现证据确认每个边界，不能先假设重写。
- `/brainstorm` 设计门禁已生效：本阶段仅审计与设计，不修改业务代码；最终设计只写入根目录三份 PWF 文件。
- GUI 手工体验进程仍在既有终端会话中运行；本设计审计不干扰该进程。

### 第一轮代码证据

- 持久化对象图已有部分 lineage：`WellTable.source_resource_ids`、`FactorMapTask.input_resource_ids/output_resource_ids/well_table_id/input_snapshot_hash`、`ContourDraft.linked_factor_task_id/linked_map_document_id`、`PaleoMapDocument.linked_contour_draft_id`、`ExportArtifact.linked_id/source_task_ids`。
- 数据页展示的原始资源与导出物直接取自同一个 `ProjectDocument.resources/export_artifacts`；导入完成后扩展 live project，再通过 `update_state()` 刷新表格与预览，因此不是独立数据库。
- 制备页 Worker 使用项目快照计算，完成后在 GUI 线程替换 `factor_map_tasks` 或提交 `contour_drafts/paleomap_documents`；编图页也提供了一套等值线生成入口，二者复用 Worker/commit 服务，但页面触发与提示仍有重复。
- 编图页面把 `PaleoMapDocument` 作为已提交状态，把 `MapEditScene` 作为未提交编辑态；壳层刷新同一对象时会保护 dirty scene，项目保存前是否统一 flush 仍需继续核对。
- `.paleo.json` 保存具有原子替换，但路径规范化只显式覆盖 `resources`、`export_artifacts`、`reference_layers`；若专业计算参数或派生元数据中藏有文件路径，当前没有统一路径引用类型。
- 当前主要架构缺口不是“没有模型”，而是缺少统一的资产/派生结果提交协议：稳定身份、来源版本、结果失效、项目 dirty、输出登记与下游重新绑定尚未由一个服务集中保证。

### 用户确认

- 用户选择“项目单一事实源”方案：页面可以有暂存态，但只有经过确认提交的结果才进入 live `ProjectDocument` 和后续 `.paleo.json` 保存链路。
- 用户进一步限定制备页业务：同一项目需要制备多种单因素图，因此页面信息架构、任务组织和下游编图关联都要以“因素实例”为基本单位调整。

### 多因素制备实现差距

- `DEFAULT_FACTOR_TYPES` 目前固定为地层厚度、砂岩含量、砂地比、泥岩含量，但模型的 `factor_type: str` 没有限制扩展类型。
- `FactorTaskPanel` 只显示不可交互任务行；全页只有一个 `method_combo`，触发 `batch_prepare_factor_maps()` 后会对项目全部任务采用同一方法。
- `PreparationPage._resolve_display_well_table()` 取第一张井表，QC 在没有明确关联时也以第一项任务为回写目标；这会让多因素的字段选择、缺失值、异常值和砂地比约束混在一起。
- `FactorPreviewGrid` 仅展示完成任务的摘要卡，不能进入单因素详情、比对输入版本、查看失败原因或选择推送编图的特定成果。
- 制备成果网格留在任务 `parameters` 中，数据页只统一展示 `resources/export_artifacts`，因此“制备输出回流数据页”当前并未闭环。

### 因素目录决策

- 用户选择混合因素目录：内置标准模板保证地层厚度、砂岩厚度/含量、砂地比、泥岩含量等专业因素的字段语义、单位与 QC；同时允许新增孔隙度、渗透率、古水深等自定义因素。
- 该决策要求把“因素定义”与“某层位下的一次因素制备任务”分开，避免把模板规则重复写入每个页面和 Worker。

### 制备输入绑定决策

- 用户确认所有制备输入先进入项目资产目录：无论从数据页还是制备页选择文件，都复用同一导入/去重/路径相对化链路。
- 因素任务通过稳定 `resource_id` 和字段映射消费数据；文件路径只属于 `ResourceItem`，从而让项目移动、另存和重开后的引用仍可解析。
- 计算 Worker 应接收由资源版本、字段映射、层位和参数组成的不可变输入快照；完成时校验快照仍为当前版本，再允许提交。

### 制备成果版本决策

- 用户确认每次成功且经确认的因素计算生成不可变成果版本；大型网格/预览放项目 artifacts 目录，`.paleo.json` 只保存元数据、校验和、来源快照和相对路径。
- `FactorMapTask` 应作为长期任务身份，指向 active result version；`PaleoMapDocument`/参考图层固定引用某个 result version，而不是动态追随“最新版”。
- 新版本出现时，编图显示“有更新可用”，由用户显式切换；旧版本仍可复现，避免地图无提示变化。

### 总体架构路线确认

- 用户确认采用项目资产图方案，不采用页面最小补丁或完整事件溯源。
- 为兼容现有工程，设计应增量扩展现有模型：原始资源继续使用 `ResourceItem`，长期因素任务继续使用 `FactorMapTask`，重点新增因素定义、不可变结果版本和集中提交服务。
- 专业插值与栅格输出继续下沉 geo-viz-engine；workbench 的服务层负责任务快照、项目 lineage、artifact 写入和提交事务，页面仅负责交互。

### 多因素制备页设计提案

- 用户已批准总体架构边界，制备 UI 应围绕“选择因素 → 绑定项目资产/字段 → 因素级 QC/参数 → 异步试算 → 预览 → 采用不可变版本”组织。
- 为兼顾专家批量效率与单因素差异，左侧采用可多选任务导航，右侧保存任务级配置；批量默认参数可以覆盖未自定义任务，但不能静默替换已定制参数。
- 计算成功不立即覆盖项目 active result；待采用结果与已提交版本必须视觉区分，取消或失败不改变已有可用成果。
- 现有首张井表/首项任务假设必须移除，所有表格、QC、约束和预览均由当前 `factor_task_id` 与其显式关联解析。
## Phase 32 — 统一预览设置面板（初始假设）

- 用户要求所有预览格式共享一个内容设置面板，并授权直接采用推荐默认值执行到底。
- 推荐持久化边界是用户级 `QSettings`：预览表现是本机查看偏好，不应污染项目业务文档或导致项目保存提示。
- 设置必须进入预览请求身份/缓存键；否则修改内容上限、分页或渲染参数后可能命中旧缓存。
- 本阶段先按真实代码盘点支持模式与渲染宿主，再固定字段，避免面板出现没有消费者的伪设置。
- 用户“直接执行到结束”的授权覆盖 brainstorming 的交互确认步骤，但不取消设计自审和 TDD；推荐方案视为已批准。

### 第一轮预览代码证据

- `PreviewMode` 包含 `geoviz/pdf/image/text/table/well_log/seismic/rich_text/json_tree/geotiff/media/web_document`，另有 `empty/message` 状态；设置面板应覆盖实际内容模式，空态/错误态无需独立设置。
- Provider 的读取/解析限制均是模块常量，适合由不可变 `PreviewSettings` 快照替代；默认值可保持当前行为，降低回归风险。
- 异步控制器已有 generation 丢弃陈旧结果机制，但同一资产设置变化仍会命中旧 LRU/磁盘缓存，因此 settings fingerprint 必须同时进入两级缓存身份或设置变更时可靠清空。
- 推荐双保险：内存 cache key 加 settings fingerprint；设置应用时递增 generation、清 pending、清两级缓存并重发当前资产。磁盘缓存 schema/key 是否支持指纹仍需继续审计。
- 设置 UI 放入 `DataReaderPanel` 内部比新增独立 AppShell 页面更符合范围：入口始终与预览同处，且不挤占数据表主区。

### Host 与控件审计

- `DataReaderPanel` 是所有非映射数据资产的统一 mode 分发点，并保留 `_current_result`；它可在不重新解析文件时应用纯显示设置，也可发信号让 DataPage 对内容设置重新请求。
- `DataPage` 已保留 `_selected_asset` 并独占 `PreviewRequestController`，因此 settings change → controller update → request current asset 可在一个页面闭环，无需 AppShell 全局协调。
- `LocalVisualizationProvider` 当前固定调用 `engine.prepare(request, PreviewOptions.local())`；专业预览限制应从统一设置映射为 `PreviewOptions`，磁盘缓存已有 options fingerprint 结构，可参数化而无需重写格式。
- `GeoVizPreviewHost` 只负责 PreparedPreview 的 UI-thread widget 生命周期；计算内容设置应在 prepare 前生效，Host 不应重复实现专业解析参数。
- 普通 widgets 已集中在 `preview_widgets.py`：文本/富文本、表格/摘要、图片、PDF、JSON、GeoTIFF、媒体均有稳定控件实例，可增加 `apply_settings()` 而不重建页面。
- 推荐默认值保持当前解析上限，并采用安全显示默认：文本不换行、图片平滑适配、PDF适合整页、JSON展开两层、媒体不自动播放/音量70。

### 设置持久化与快照 API

- 代码库没有既有 `QSettings` 使用或 QApplication organization/application 命名；Store 必须自行使用稳定 namespace，并允许依赖注入，才能进行隔离测试。
- `PreviewOptions.local()` 的准确默认是 max_curves=12、max_depth_samples=2000、max_slice_axis=512、max_points=50000、surface_grid_size=256；统一设置默认直接复用这些值。
- Provider 不能只持有可变 `self.settings`：旧 Worker 可能在切换后读取新设置，却把结果写入旧 cache key。请求必须显式携带 frozen settings snapshot，使 key、Worker 与结果属于同一配置版本。
- `PreviewDiskCache` 已把 PreviewOptions 纳入 key，但目前硬编码 `PreviewOptions.local()`；改为实例持有当前 options 即可保持不同设置的磁盘条目隔离。
- `MediaPreviewWidget` 当前音量默认80；新推荐默认70，并保持 autoplay=false，以避免切换资产时突然播放。

### 兼容性与 fallback 结论

- 现有 `SlowProvider/DelayedProvider/FailingProvider` 等扩展均覆盖 `preview(asset)`；若 Worker 改为传 `settings=` 会造成 TypeError。采用 `with_settings()` 浅拷贝快照可保持旧接口并让内置 Provider 读取 frozen settings。
- 浅拷贝仅复制 Provider 外壳，GeoViz engine 仍共享；Worker 当前严格串行，因此不会增加 engine 并发风险。
- fallback 中 SpreadsheetML、ZIP 目录属于用户可见内容数量，应服从统一文本/表格设置；ZIP结构、内嵌图片、中央目录限制属于安全防线，不能由设置面板调大。
- 现有测试覆盖 Provider 纯度、bounded reads、异步 last-wins、ReaderPanel Host 生命周期和 cache LRU，可在这些契约上增量 TDD，无需重写测试体系。

### TDD 记录

- `T-PREVSET-01 RED-1`：`tests/test_preview_settings.py` 因 `ModuleNotFoundError: paleo_workbench.ui.pages.preview_settings` 收集失败，准确证明默认配置模块尚不存在。
- `T-PREVSET-01 GREEN-1`：最小 frozen dataclass 提供完整推荐默认字段，定向测试 1 passed。
- `T-PREVSET-01 RED-2`：新增校验、mapping/fingerprint、GeoViz options 与 QSettings round-trip/reset 契约；因 `PreviewSettingsStore` 不存在而收集失败，符合功能缺失预期。
- `T-PREVSET-01 GREEN-2`：`PreviewSettings` 完成强类型/范围校验、mapping、16位稳定 fingerprint、GeoViz options 映射；Store 完成注入式 QSettings round-trip/reset，定向 5 passed。
- PWF 同步曾因 Issue 清单锚点未匹配失败 1 次；改用 `rg` 精确定位当前文本后成功更新，未影响业务代码或测试。
- `T-PREVSET-02 RED-1`：Provider 快照、文本/表格/ZIP限制、JSON超限和 GeoViz options 共 5 项均因 `with_settings` 缺失失败；已有配置 5 项保持通过。

### Provider 细节

- `_read_preview_chunk`、CSV、Excel dataframe、LAS 曲线、Markdown/HTML、GeoTIFF decimation 全部直接引用模块常量，需统一改为 `self.settings`，默认仍与旧常量等值。
- JSON 当前先 `read_bytes()` 整文件，再按 5 MiB 截断并 `json.loads()`；既违背有界读取，也可能将合法大 JSON 误报为解析错误。新实现应先 stat/有界读取，超限直接给出可恢复提示。
- 现有 JSON 测试只覆盖正常小文件和 Widget 展示，没有依赖“截断后解析”这一不可靠行为，允许安全修正。
- JSON array collapse 属于 Widget 展示策略而非 Provider 解析策略，应由 `JsonTreePreviewWidget.apply_settings()` 接收阈值与初始展开深度。
- `T-PREVSET-02 GREEN-1`：Provider 浅拷贝 settings snapshot 已贯穿文本、HTML/Markdown、CSV/Excel/LAS、SpreadsheetML/ZIP、JSON、GeoTIFF 与 GeoViz；相关 69 项测试通过。
- JSON 超限路径现使用 stat + 有界读取，超过设置上限时给出可恢复提示，不再整文件读取或把截断 JSON 误报为格式损坏。
- 第二次 PWF 同步也因组合补丁中的 Issue 锚点未匹配失败；已停止修改该行，改为只更新精确定位的任务行并追加日志，避免第三次同类尝试。
- `T-PREVSET-03 RED-1`：settings fingerprint 参数、disk options 参数和 Controller settings 构造/更新接口均按预期缺失；结果 3 failed、10 passed。
- `T-PREVSET-04 RED-1`：面板 apply/persist、22字段 round-trip、reset/default 和13种 mode→category 契约因目标模块不存在而收集失败，符合预期。
- `T-PREVSET-04 FAIL-1`：面板实现后16项均在构造时因不存在的 `tokens.BG_PANEL` 失败；应使用现有 `BG_SIDEBAR`，行为逻辑尚未执行。
- `T-PREVSET-04 GREEN-1`：改用既有 `BG_SIDEBAR` 后 16 passed；面板完整覆盖22字段、8类别、13种 mode 映射、apply/store 与 reset/default。
- `T-PREVSET-05 RED-1`：普通 Widgets 缺少 `apply_settings()`，ReaderPanel 缺少 `settings_store` 注入/面板入口；3项按预期失败。
- `T-PREVSET-05 GREEN-1`：各预览 Widget 已统一实现 `apply_settings()`，ReaderPanel 注入 Store、嵌入按格式分类的设置面板并同步 Provider/显示状态；定向测试 `3 passed in 0.81s`。
- `T-PREVSET-06 AUDIT`：`DataPage` 当前创建 Controller 时未传 Reader 的设置快照，也未监听 `preview_settings_changed`；选中资产的唯一预览入口是 `_preview_controller.request(asset)`，因此正确接线应在设置变更时先 `set_settings()` 失效旧 generation，再重请求 `_selected_asset`，无需改动 ProjectDocument 或项目资产身份。
- `T-PREVSET-06 RED-1`：设置变更信号测试失败于 Controller 仍保留旧 `text_limit_kib=256`，且未重请求选中资产，准确证明 DataPage 接线缺失。
- `T-PREVSET-06 IMPLEMENTATION NOTE`：Controller `set_settings()` 本身负责 generation+1、清 pending、清内存缓存和更新磁盘缓存 options；DataPage 仅需传入初始 Reader settings，并在返回 `True` 时调用既有 `request(_selected_asset)`，避免重复实现生命周期逻辑。
- `T-PREVSET-06 GREEN-1`：DataPage 以 Reader settings 初始化 Controller，并监听变更；新设置先使旧代次失效，再重请求当前资产。定向 `1 passed in 1.37s`。
- `T-PREVSET-06 REGRESSION FAIL-1`：可见预览域首次回归 `3 failed, 82 passed`；三项均为测试/嵌入用 FakePdfView 不具备新 `setZoomMode/ZoomMode`，并非真实 PDF 加载失败。修复策略是在可选后端缺少缩放 API 时保留加载与导航能力，仅跳过设置缩放。
- `T-PREVSET-06 REGRESSION GREEN-1`：PDF后端能力降级后，可见设置/Panel/Reader/Widgets `85 passed`；Provider/fallback/GeoViz/cache/disk/strategy `92 passed, 1 lasio deprecation warning`。
- `T-PREVSET-06 ASYNC PLAN`：异步测试集中于 `tests/test_preview_async.py` 的27个函数（含参数化共31项）；鉴于此前单进程整文件在Qt teardown出现过一次segfault，继续按前14函数/后13函数两个独立进程覆盖，避免测试框架跨用例析构噪声掩盖业务断言。
- `T-PREVSET-06 ASYNC GREEN`：两个独立进程分别 `17 passed`、`14 passed`，完整覆盖31项；设置代次、last-wins、资产快照、shutdown、media preload与缓存生命周期均通过。
- `T-PREVSET-06 DATA GREEN`：DataPage + DataWorkspace `57 passed, 1 lasio deprecation warning`；compileall 与 `git diff --check` 均 exit 0。工作区中既有 `SCRATCH/` 与五个 docs plan 保持未跟踪、未触碰。
- `T-PREVSET-06 SELF-REVIEW-1`：配置模型/面板、Reader、Provider、Controller与缓存diff未发现项目数据身份旁路；设置持久化明确独立于 `.paleo.json`，而资产读取仍使用同一个 ResourceItem/ExportArtifact。需进一步核对 JSON 大数组 lazy expand 与 QPdfView 实际枚举能力后再全量。
- `T-PREVSET-06 SELF-REVIEW-2`：运行时 introspection 确认本机 QPdfView 同时具备 `Custom/FitInView/FitToWidth`、`setZoomMode`、`setZoomFactor`；兼容分支合理。JSON 大数组 lazy materialization 是既有实现并已有独立测试，本次仅将固定阈值参数化，不扩大重构范围。
- `T-PREVSET-06 FULL GREEN`：最终 `QT_QPA_PLATFORM=offscreen pytest -q` 返回 exit 0：`1051 passed, 4 skipped, 2 warnings in 49.69s`；warnings 仅为 lasio/pkg_resources deprecation 与 GDAL exception-policy future warning。
- `T-PREVSET-06 DELIVERY GATES`：已完整读取 requesting-code-review 模板与 verification-before-completion；因改动尚未提交，独立 reviewer 将以 HEAD `6b32b975` 对当前工作区 diff + 明确的新文件做只读审查，忽略既有无关 untracked。
- `T-PREVSET-06 REVIEW`：独立审查无 Critical；两个 Important 为（1）WebDocumentPreviewWidget 懒创建后首次加载前未应用当前 settings；（2）GeoTIFF decimation 向下取整且 decim=1 时仍选 overview，可能超目标或无谓降质。另提醒新增模块/测试处于 untracked，交付清单必须明确，用户未授权故不擅自 commit。
- `T-PREVSET-06 REVIEW FIX PLAN`：Web 回归需扩展现有隔离子进程 FakeWebWidget，记录 apply_settings 并断言先应用持久设置；GeoTIFF 回归用真实 rasterio 生成 513×257 栅格并检查PNG长边≤256，再生成带overview的64×32小图检查仍保留原尺寸。算法改为 `ceil(long_side/target)`，且仅 decim>1 时选择合适overview。
- `T-PREVSET-06 REVIEW RED`：三个 reviewer 回归均准确失败：Web事件只有load无settings；511×257缩略图仍为511×257；64×32带overview小图被降至32×16。证明审查意见可复现。
- `T-PREVSET-06 REVIEW GREEN`：Web懒创建立即应用当前settings再load；GeoTIFF使用整数ceil降采样且仅decim>1选择overview。三个回归 `3 passed, 4 NotGeoreferenced warnings`。
- `T-PREVSET-06 RE-REVIEW`：Web项确认解决；GeoTIFF仍有“所需倍率大于最大overview却回退最大overview”的 Important。首轮最终全量同时发现既有隔离 FakeWebWidget 无apply_settings导致1失败（中止时583 passed），需能力检测保持嵌入兼容。已新增overview倍率不足回归。
- `T-PREVSET-06 SECOND RED`：旧FakeWeb兼容与overview不足两节点 `2 failed`；最小修复为Web apply能力检测，以及仅在找到 `overview >= decim` 时替换计算倍率，否则保留严格ceil倍率。
- `T-PREVSET-06 SECOND GREEN`：Web新/旧后端与GeoTIFF三种边界合计 `5 passed, 6 NotGeoreferenced warnings`。
- `T-PREVSET-06 FINAL GREEN`：修复后的新鲜门禁 `python -m compileall -q paleo_workbench/ui/pages && git diff --check && QT_QPA_PLATFORM=offscreen pytest -q` 返回 exit 0：`1055 passed, 4 skipped, 8 warnings in 49.54s`。warnings 均为既知 deprecation/future 或测试栅格无地理参考提示。

## Phase 33 — 对话框迁移初始判断

- 用户明确指定应用工具菜单入口，设置应从 ReaderPanel 的局部展开区域移出；底层强类型配置和异步刷新链路无需变化。
- 推荐采用“菜单只发请求信号、应用控制层管理Dialog、DataPage应用设置”的边界，避免菜单直接查找页面子控件。
- brainstorming 的设计确认由此前“推荐默认、不用问、直接执行”授权覆盖；本阶段仍记录候选路线、自审与TDD，不创建PWF体系外设计文档。
- 当前 `MenuBar` 的“工具”只是 QLabel，不具备 QMenu；必须升级为按钮+菜单，而不是把 QAction 挂到不可交互标签。
- `PaleoWorkbenchWindow._wire_menu_bar()` 会在每次 AppShell 重建后重新接线，适合连接工具菜单；Dialog由Window持有并在回调中动态读取 `self.app_shell`，可避免打开/新建工程后指向已销毁DataPage。
- `PreviewSettingsPanel` 已封装全部字段、Store持久化与reset/apply信号，Dialog只做容器和窗口语义；Reader不再依赖Panel，但继续从相同Store读取启动设置。
- `T-PREVDLG-01 RED-1`：两个菜单节点因 `tools_menu_button` 与 `preview_settings_requested` 均不存在而失败，准确证明当前工具项不可交互。
- `T-PREVDLG-01 GREEN-1`：真实工具QMenu、预览设置action和语义signal完成；菜单全文件 `6 passed`。
- `T-PREVDLG-02 RED-1`：Dialog的modal/context/apply/reset三个契约因目标模块不存在而收集失败，符合预期。
- `T-PREVDLG-02 GREEN-1`：Dialog复用Panel/Store；应用转发设置并accept，reset转发默认但保持打开；`3 passed`。
- `T-PREVDLG-03 RED-1`：Reader仍含settings_panel；Window无 `_preview_settings_dialog` 且工具信号未接线。3项分别按预期失败，覆盖局部UI移除、当前mode同步和shell重建后动态应用。
- `T-PREVDLG-03 GREEN-1`：Reader瘦化、菜单打开、当前mode同步、应用后DataPage Controller更新及shell重建动态路由均通过；定向3项、菜单/Dialog/Reader集成域70项全绿。
- `T-PREVDLG-04 SELF-REVIEW`：全仓搜索确认生产代码无残留Reader `settings_panel/settings_button/_on_settings_applied` 引用；Panel现在仅被Dialog组合。Window回调始终在调用时读取当前 `self.app_shell.data_page`，Dialog跨shell重建安全；QSettings仍为唯一持久化源。
- `T-PREVDLG-04 REGRESSION-1`：DataPage/ProjectLifecycle/AppShell `89 passed, 1 lasio warning`；全包compileall与`git diff --check` exit 0。新Dialog文件和Phase32设置文件仍为task-created untracked，最终交付需明确但不擅自commit。
- `T-PREVDLG-04 REVIEW`：独立审查0 Critical；行为Important为Window集成测试使用生产Store导致真实QSettings被写font_size=21，必须注入临时Store。交付Important为新Dialog/测试尚未tracked（用户未要求git add/commit，最终明确列出）；Minor为ToolsMenuButton缺统一样式、未测reject丢弃暂存编辑。
- `T-PREVDLG-04 REVIEW RED`：临时Store注入与Tools按钮样式两个节点 `2 failed`；分别为Window构造器无注入参数、QSS无Tools选择器。检查生产配置发现除font_size=21外其余均为推荐默认，可确认该值由本轮测试污染，修复测试后恢复为12。
- `T-PREVDLG-04 REVIEW GREEN`：Window临时Store注入与Tools统一样式 `2 passed`；真实QSettings的测试污染已从font_size=21恢复为推荐默认12，后续集成测试只写tmp_path INI。
- `T-PREVDLG-04 FINAL`：reviewer复核行为Critical/Important清零；compileall、`git diff --check`、全量offscreen pytest均exit 0，最终 `1063 passed, 4 skipped, 8 warnings in 57.93s`。新Dialog及测试必须在未来提交时显式包含，当前未按用户未授权擅自stage/commit。
- `RUN OBSERVATION`：上一GUI会话退出前，地震3D渲染重复报告 `pyqtgraph.opengl.shaders` 缺少 `compileShader`，调用点为 `geoviz_seismic/renderer_3d.py:522`；进程最终exit 0。该兼容缺陷未在本次“运行”请求中擅自修改，需后续单独诊断。

## Phase 34 — 地震预览性能根因调查

- 复现日志不是单次慢计算，而是GLViewWidget每次paint都调用 `getCustomShaderProgram()`；因编译函数AttributeError发生在缓存赋值前，下一帧继续重试并打印完整traceback，形成高频异常/I/O洪泛。
- 当前环境 `pyqtgraph==0.14.0`；`pyqtgraph.opengl.shaders` 仅暴露 `ShaderProgram/VertexShader/FragmentShader/getShaderProgram`，不暴露旧式 `compileShader/compileProgram`。
- 同一环境的 `OpenGL.GL.shaders` 明确提供 `compileShader/compileProgram`；renderer当前使用raw GL纹理、uniform、attrib和 `with program:` 语义，仍需核对PyOpenGL返回Program对象是否支持上下文管理。
- geo-viz-engine工作树目前已有用户/前序改动，修复只触碰明确的renderer/test，禁止覆盖无关dirty内容。
- PyOpenGL `compileProgram()` 返回支持 `with program:` 的 `OpenGL.GL.shaders.ShaderProgram(int)`，与现有paint用法兼容；方案A不会破坏program上下文协议。
- pyqtgraph 0.14自身的 `opengl/shaders.py` 顶部也从 `OpenGL.GL` 导入内部名 `shaders`，其高层ShaderProgram最终仍调用PyOpenGL编译器；当前renderer误把pyqtgraph模块本身当成编译器。
- 额外风险：当前实际上下文是OpenGL ES 3.2，ES3 shader源码中定义了使用legacy `texture3D` 的函数（虽主路径调用modern函数）；需通过真实GL context最小实验确认驱动是否拒绝，再决定是否需同时清理源码。未验证前不修改。
- 真实GLES3.2 monkeypatch实验确认第二根因：切换到正确PyOpenGL编译器后，fragment shader在未使用的`compute_normal_legacy()`处仍编译失败，驱动报`texture3D` ambiguous。说明必须同时修正编译器命名空间与modern/legacy GLSL分支污染，否则只修import会把异常从AttributeError变为ShaderCompilationError。
- 第一次独立实验仅因未设置engine PYTHONPATH而未导入包；第二次显式包路径后成功建立GLES3.2 context并得到上述编译证据，策略已改变，未机械重复。
- 根因链已闭合：错误模块API → program未缓存 → 每帧重试；修正API后现代shader含legacy符号 → 仍无法缓存。两者均位于engine renderer，不应在workbench页面做节流补丁。
- `T-SEISPERF-01`测试文件已写入，但从`geo-viz-engine`根目录直接执行时，当前环境没有把`packages/geoviz_seismic`加入Python搜索路径，故首次RED停在`ModuleNotFoundError`。后续定向/engine测试必须显式设置`PYTHONPATH=packages/geoviz_seismic`（必要时追加相关workspace packages），以确保失败来自功能契约而非测试入口。
- 显式包路径后的功能RED已确认：`getattr(renderer, "gl_shaders", None)`为`None`。该失败与运行日志的`pyqtgraph.opengl.shaders.compileShader` AttributeError完全一致，测试确实锁定同一根因。
- 最小实现已完成：现代GLES/desktop源码不再包含`texture3D/texture2D` legacy helper，旧版源码不再包含`texture()` modern helper；编译统一调用`OpenGL.GL.shaders`。Fake context验证同一item两次取program只编译一次。
- PySide6的`QOpenGLWidget`位于`PySide6.QtOpenGLWidgets`而不是`QtWidgets`；首次真实验证脚本在导入阶段退出，没有形成新的shader失败证据。修正诊断脚本导入后再测同一目标。
- 修正诊断脚本后，真实GLES3.2驱动成功编译清理后的shader，返回program 3；再次调用返回同一PyOpenGL ShaderProgram对象。此前每帧重编译/异常的必要条件已消失。
- engine地震渲染、视图、雕刻和山体阴影相关域24项全绿，说明编译器切换未破坏已有体渲染控制逻辑。
- workbench从项目资产→GeoViz Provider→Host→Seismic View的预览链路124项全绿；本次engine修复无需改ProjectDocument或数据页资产身份，薄宿主边界保持不变。
- 两个“单进程全量”门禁分别表现为engine在Qt poll长期等待、根套件在pytest-qt teardown段错误；均发生在大量GUI用例累积后的事件清理阶段，且没有shader traceback或业务断言失败。该仓此前已用分段async验证规避同类Qt teardown崩溃，因此本轮改用按文件批次的新进程策略，而不是机械重复全量命令。
- 根测试前40个文件分成两个新进程后共358项全绿，包括此前单进程崩溃百分比覆盖的DataPage/Integration区域；支持“Qt对象跨大量文件累积析构”判断，而非本轮shader修复造成确定性崩溃。
- 根测试前80个文件已在4个隔离进程覆盖557 passed、4 skipped，无断言失败或segfault。
- 根测试前120个文件累计866 passed、4 skipped，预览异步、缓存、设置和项目生命周期均已在隔离进程稳定通过。
- 根157个测试文件已全部覆盖，分段合计1063 passed、4 skipped，恰好等于Phase33单进程全量基线；没有遗漏测试文件，也没有新增失败。Qt teardown仅影响一次性超长组合进程。
- Reviewer确认modern分支已清洁，但发现legacy GLES2与desktop分支的地平线采样仍写成generic `texture()`；这在GLSL ES 1.00/desktop 1.10–1.20不可用，即使雕刻关闭也会使整个shader编译失败。正确修复为两处`texture2D()`。
- PyOpenGL `ShaderProgram`公开`check_linked()`；在绑定attribute后二次`glLinkProgram()`后调用该方法，可避免把二次链接失败的program写入缓存。测试同时将编译器断言从“属性存在”加严为与`OpenGL.GL.shaders`对象identity一致。
- 实现时首次文本替换命中了modern GLES和legacy GLES两处；立即通过分支行号检查发现并纠正为精确矩阵：modern GLES/desktop=`texture()`，legacy GLES/desktop=`texture2D()`。未在错误中间态运行测试或交付。
- Reviewer修复GREEN：Fake modern compiler identity/link/cache + GLES2/desktop legacy源码共3项通过；真实GLES3.2仍成功编译program=3且缓存identity保持true，`check_linked()`未引入driver回归。
- Reviewer二次只读复核确认四分支纹理函数矩阵、PyOpenGL identity、link检查和缓存生命周期正确，Critical/Important均为0，Ready=Yes。真实legacy context未建立，但源码契约测试对本次函数名缺陷足够，真实现代GLES路径另有driver验证。
- 最终workbench链路新鲜验证124项通过；源码扫描确认错误的pyqtgraph compiler import/call已彻底消失，generic horizon `texture()`只存在modern GLES3/desktop分支，legacy两处均由回归锁定为`texture2D()`。
- 实际paint验证比单独编译更完整：Renderer3D真实显示、加载16³float32体、切换volume模式并处理30帧后，DualGLVolumeItem已缓存program=6；stderr只有pyqtgraph对GLES的通用RuntimeWarning，没有任何shader异常或每帧traceback。
- 新发现的“地震三维体不显示”不是shader或数据读取失败；`SeismicView`初始化时 `_3d_mode_combo` 默认停在“正交切片”，而 `Renderer3D.load_volume()` 只会保留当前 `_mode`。在新会话里若没有显式切到“三维体”，volume item 会被正确创建但立即隐藏，表面表现就是 3D 区域空黑。

## Phase 35 — 初始需求判断

- 用户明确要求DAT、LAS等预览采用“数据列表在第一选项卡、可视化在第二选项卡”的渐进式界面；性能关键契约是第二选项卡未点击时不得启动重解析/渲染线程。
- 当前目标不是简单延迟Widget显示：必须把重工作请求本身延后，并在资产切换/Reader关闭时复用现有generation与Owned Worker生命周期防陈旧结果。
- 用户此前对预览设置目标授权“默认推荐、不用问、直接执行到结束”；本轮仍按superpowers记录候选设计和自审，但以当前明确请求作为双选项卡/懒启动设计批准，并遵守只用根三份PWF文件的更高优先级约束。
- 当前`PreviewProvider.preview()`在一次后台请求中直接走`LocalVisualizationProvider`，LAS/SEG-Y/DAT若engine支持会先`engine.prepare()`并返回单一`mode="geoviz"`；这意味着资产选中时专业解析已经发生，Reader层“延迟创建Host”并不能防止后台重工作提前启动。
- `DataReaderPanel`目前用一个`QStackedWidget`按mode显示单个widget；geoviz result会立即创建Host并render。它已有延迟import/Host创建、`_safe_clear_geoviz()`和稳定失败message状态，可作为双选项卡可视层基础，但请求触发必须上移到DataPage/Controller的新“可视化请求”入口。
- `PreviewResult`已同时拥有summary/table字段和`engine_preview`，LAS fallback已生成摘要/曲线表；可复用DTO表达“轻量表格结果”，无需另建项目数据模型。DAT当前在基础Provider属于TEXT_FORMATS，但GeoViz engine也可能识别，需审计策略顺序决定哪些DAT启用双页。
- `PreviewRequestController`已有generation、latest-only、settings快照和缓存；正确方向应复用它的worker契约或抽取请求purpose，避免Reader自行管理裸QThread。
- `LocalVisualizationProvider._build_preview()`对任何engine-supported ResourceItem优先`engine.prepare()`，失败才调用基础Provider；因此LAS当前连轻量曲线表也被专业结果取代。要实现双页，必须提供明确的`preview_summary()`（绕过engine）与`preview_visualization()`（只走engine）两阶段契约。
- Reader的`update_asset()`同步测试入口目前直接`provider.preview()`，DataPage生产路径走Controller；新设计需保留同步入口兼容，但生产懒启动信号不能让Reader自行直接读项目对象。推荐Reader接收轻量result，同时保存不可变资产快照/identity并发出“visualization_requested”，由DataPage路由到专用Controller。
- `PreviewResult`的well_log/seismic模式已有`SummaryTablePreviewWidget`，最小UI可用一个只在可视化候选结果时出现的`QTabWidget`包住现有summary widget与懒加载容器；其他格式仍走原QStackedWidget，避免所有预览类型被无谓重构。
- Controller当前一个实例只允许单线程、latest-only；若轻量表和可视化共用同一controller，则点击第二页会自然递增generation并替换结果，但结果返回后Reader无法区分“替换整个预览”还是“填充第二页”。最小清晰边界是第二个`PreviewRequestController`，使用仅执行engine prepare的provider；两个controller均由DataPage持有/关闭，互不阻塞。
- 双controller必须共享同一资产selection generation语义：DataPage每次选择资产时先让visualization controller失效旧请求（可新增`invalidate()`而不启动任务），再请求summary；Reader发出的懒请求带不可变资产identity，DataPage只在identity仍等于当前选择时启动。
- 可视化cache可继续使用现有key/settings fingerprint，第二次切回页同步命中；summary controller应改用基础PreviewProvider，否则仍会提前engine.prepare。Reader仍可保留LocalVisualizationProvider作可视化provider来源，DataPage分别注入其“summary facade”和“visualization facade”。
- 已有async测试完整覆盖latest-only/cache/shutdown，Reader测试覆盖Host失败稳定态；新增测试应聚焦（1）选中LAS只调用summary；（2）首击visual tab才调用visual provider且loading留在第二页；（3）重复切tab只请求一次/命中缓存；（4）切资产使旧visual结果失效；（5）两个controller都shutdown。
- GeoViz默认backends明确覆盖：LAS well_log、SGY/SEGY seismic，以及语义类型为well_head/time_depth/horizon/well_stratification的DAT；DAT `supports()`本身会读header，但比`prepare()`轻，仍不应在GUI线程反复调用。
- DAT基础Provider当前按text展示，并非表格。用户要求“类似数据列表”，推荐新增通用有界DAT表格摘要解析：识别注释/header与首批数据行，按空白分列；若结构无法稳定识别则第一选项卡安全回退文本，不妨碍第二页专业可视化。
- 引擎的`prepare()`纯解析可在线程执行，`create_widget/render/release`强制UI线程；现有分层正好符合懒任务要求：第二页点击→worker prepare→主线程Host render。
- 一次广域`rg`误扫`web_dist/assets/index.js`导致输出超限；已收窄到engine.py和四个backend源文件，不再重复该搜索模式。
- writing-plans自审后将Reader复杂度隔离到新`lazy_visualization_tabs.py`，避免继续膨胀已有420行Reader；该组件只管理tabs/局部状态/Host UI，不持有资产或线程。
- DAT样例/测试表明格式含well_head、horizon、time_depth、well_stratification四种schema及大量注释/quoted token边界；基础轻量表只承诺有界列表展示，不重实现这些专业schema验证，专业判断继续由engine.supports/prepare负责。
- worktree检测：当前`git_dir == git_common`且branch=main，不是隔离worktree；工作树有Phase32–34未提交依赖。用户此前已授权直接修改当前项目，故不创建会丢失这些依赖的新worktree，也不提交/stage。
- Phase35相关6文件baseline单进程在约40%后于async wait发生Bus error，无断言失败；与已知Qt多文件累积析构问题同型。不能原样重跑，改用独立进程分段确认各域基线。
- Task35.1两个Provider文件独立运行稳定全绿（36项）；现有RecordingEngine测试可直接扩展supports/prepare计数，现有bounded text/table测试可扩展DAT有界行为，无需新增测试文件。
- DAT实际schema使用连续`#` header后跟数据行；井位/井分层有明确列名header，horizon用`# Field: N name`元数据，时深有`#TIME ...`。轻量解析策略锁定为：有界读取→shlex安全分词→从comment header中选择与首行宽度一致的最后候选列名；没有候选时生成“列1…列N”；数据行宽度不一致则回退text。
- Task35.1功能RED准确成立：Local provider缺`preview_summary/preview_visualization`三项，结构化DAT仍走text。不可分列DAT回退text测试立即通过，因为这是需保持的现有行为而非新增能力，保留为重构防回归契约。
- Task35.1最小实现：DTO仅新增bool capability；base Provider提供向后兼容两阶段默认；Local summary显式调用基础`_build_preview`以避免动态分派回engine；visualization单独supports/prepare。结构化DAT使用有界读取+shlex，宽度不稳定安全回退text。
- Task35.1 Provider全文件41项通过。Task35.2测试应使用真实PreviewRequestController/OwnedWorkerJob与行为型RecordingProvider，只在disk facade边界用最小fake记录访问，避免断言mock存在或添加测试专用生产API。
- `invalidate()`是生产所需生命周期API而非测试钩子：DataPage资产选择必须能使visual旧代次失效而不启动新任务；active worker继续合作式结束，其result因generation不匹配被丢弃。
- Task35.2 RED在controller构造边界统一失败，尚未进入线程，说明测试先锁定公共API再验证路由/缓存/代次行为；实现后若下层断言失败可继续精确定位。
- Task35.2最小实现用模块级`_build_for_request_kind`统一None/worker路由，避免三处重复分支；summary worker在判断`is_disk_cacheable`前短路，visual/default保持原disk行为。invalidate不强杀线程，只失效generation/pending。
- preview_async全文件现收集35项，按互补-k两进程15+20完整覆盖；purpose路由、cache、media preload、latest-only、asset snapshot、shutdown和新invalidate均稳定通过。
- Task35.3 RED验证普通text现有stack行为无需修改；三个新增行为分别在DataReader公共signal、组合tabs属性和局部visual render API处失败，适合由独立LazyVisualizationTabs组件一次收敛。
- `LazyVisualizationTabs`已独立封装summary、prompt/loading/error、一次激活signal和惰性Host；Reader只负责结果路由、标题/警告与安全clear。直接geoviz兼容路径现在也落到双页并默认显示visual tab。
- `T-PREVSET-03 FAIL-1`：实现后组合运行 settings/cache/disk/async 域，先出现 2 个失败，后在 `test_worker_uses_asset_snapshot` 等待 Controller idle 时发生 Qt segfault（exit 139），完整失败详情被崩溃截断。
- 新策略：先单独运行 settings/cache/disk（不含 async）获得确定断言；再按测试节点隔离 async 契约。禁止原样重复组合命令。
- 分段验证：settings/cache/disk 共 36 passed；新增运行中设置切换节点 1 passed。新 cache key、disk options 和 generation last-wins 功能本身已证实。
- async `--maxfail=2` 精确定位两个失败：旧测试用 `make_preview_cache_key(asset)` 查默认 Controller 缓存时得到空指纹键。已将省略参数语义改为“推荐默认 fingerprint”，保留旧调用兼容。
- 两个 cache 兼容失败节点复测 2 passed；async 文件收集为 31 项，后续按 16/15 分段，避免把多 QThread teardown 累积风险误判为单节点失败。
- async 采用互补 `-k` 分段后 14 passed + 17 passed，完整覆盖31项且无崩溃；证明先前 exit139 是长组合进程的 teardown 累积，不是单个设置切换节点的可复现崩溃。
## 2026-07-19 Phase 35 验证运行隔离

- `tests/test_preview_async.py`整文件在同一Qt进程中可出现顺序相关挂起（本次19项后超过90秒无输出），而互补筛选的两个全覆盖进程为22+15全绿。该问题不是测试断言失败，也没有QThread destroyed日志；完成门禁必须使用独立进程分段，避免将Qt全局事件状态跨测试累积误判为产品逻辑回归。
- 最终采用每个async节点一个独立Qt进程的最强隔离门禁，42/42节点全部exit 0；这覆盖新增cache/request双代次、DataPage两类clear-during-loading与错误重试语义，排除了单一功能节点的确定性失败。
- 第三轮只读复核结论为0 Critical、0 Important、READY。复核确认压缩在epoch锁外、最终publish受guard保护、clear后旧epoch不可复活、UI结果仍按request generation交付。
- 三项非阻断优化留档：LAS summary+visualization对超大文件仍有重复流式扫描；空LAS兼容依赖精确异常文本；超大/网络cache root的递归删除仍同步。它们不影响本轮“未点击不重解析”和并发正确性，后续宜用header元数据缓存、结构化错误码与rename后后台删除分别治理。
- Phase35最终数据流：ProjectDocument/ResourceItem选择只触发summary controller→有界DAT/LAS列表→Reader Tab0；只有Tab1激活信号才由DataPage以同一当前ResourceItem快照启动visual controller→engine prepare→UI线程Host render。两个controller分别持有request generation，缓存另持cache epoch，因而选择变化可拒绝陈旧结果，清缓存又不会让当前页面永久loading。

## Phase 36 — 首屏纯表格诊断

- 用户所说“属性值”对应`SummaryTablePreviewWidget.summary_table`，该表固定以`("属性", "值")`渲染`PreviewResult.summary_rows`；下方`detail_table`才是LAS曲线列表、DAT字段列表等目标数据表。
- 只需改变双选项卡首屏的组合组件，不应全局删除`SummaryTablePreviewWidget`的属性表：普通well_log/seismic单页预览及GeoTIFF元数据仍有独立既有语义。
- 最小安全边界是在`LazyVisualizationTabs`中直接使用`TablePreviewWidget`承载`table_headers/table_rows`；text fallback保持TextPreviewWidget，第二页惰性请求不变。
- 实现验证表明该边界成立：双页首屏不再消费`summary_rows/message`，但Provider仍可为普通单页预览保留这些DTO字段；项目资产、缓存键与线程generation均未改动。
- Phase36完整根回归仍为`1091 passed, 4 skipped`。B段一次Qt Bus error通过stress文件独立5 passed + 其余144 passed闭环，E/async继续用既定逐进程隔离；无业务断言失败。
- 最终UI语义：DAT/LAS等双页专业预览的Tab0只包含`table_headers/table_rows`，不再显示“属性/值”；普通非双页摘要组件保持原样，Tab1仍仅在用户激活后启动异步可视化。

## Phase 37 — 可视化交互一致性初步调查

- 引擎well backend的目标widget为`WellLogCanvas`，引擎seismic backend的目标widget为完整`SeismicView`；后二者都不是workbench复制实现。
- `WellLogCanvas`和seismic `ProfileWidget`均定义mouse/wheel事件，`SeismicView`还定义两行toolbar。用户报告因此优先怀疑宿主容器的焦点/尺寸/事件传播或准备数据链路，而不是在workbench另造交互。
- 根因已定位：`GeoVizPreviewHost`仅以零边距Stack承载engine widget，不截获鼠标；well backend却把原`QPainterWidget`降级为裸`WellLogCanvas`，遗漏`ZoomPanHandler.set_full_range`、滚轮转发、十字线和深度尺。Seismic backend则明确创建轻量`SeismicPreviewWidget`，并非engine原有的`SeismicView`，所以完整地震工具栏/3D/拾取等能力天然不可达。
- 修复边界应在geo-viz-engine backend：well backend创建/渲染原`QPainterWidget`，seismic backend创建完整`SeismicView(auto_load=False)`并将异步加载、cancel/cleanup归属engine widget；workbench继续只当薄Host，不能复制或重写这些交互。
