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
- 计划自审通过：选定范围的启动/取消/托管/stale/正常结果顺序均有 RED 契约；无 engine 或业务算法变更。
