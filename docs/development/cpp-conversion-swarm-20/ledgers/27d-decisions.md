# 27d-decisions — CONV-27d bridge edit domain（native edit session / session set / gestures / render snapshot）

CONV-27（27b）D-27-01 把 QGIS 桥编辑域明确排除（"其消费面在 libs/qgis 桥切片"）。
UI-13（PR #1406，已合并）吸收了 `vector_layer.py` + `edit_delta.py` 的核心
（`libs/ui_composite/vector_layer.{hpp,cpp}`：VectorFeature / VectorLayer /
VectorEditSession / EditDelta / delta_from_command / geometry_hash）与
`INativeEditing` seam（仅接口，无任何实现）。本分支补齐剩余真缺口——全部
Qt-free 纯逻辑数据核，宿主（ui_composite / qgis 桥切片）可直接采用。

## Scope ledger

**In scope（本分支拥有）**
- `paleo_workbench/mapping/edit_session_set.py` → `libs/mapping_document
  edit_session_set.{hpp,cpp}`（EditSessionSet + JoinDecision 全量）。
- `paleo_workbench/mapping/edit_gesture_manager.py` → `edit_gesture_manager.{hpp,cpp}`
  （GestureRecord + EditGestureManager 全量）。
- `paleo_workbench/mapping/native_edit_session.py` → `native_edit_session.{hpp,cpp}`
  （NativeEditSessionController 全量：三段门禁、易失会话、committed 回写收集、
  读回规范化、属性写、全或无 commit + 补偿恢复、手势计划 undo/redo）。
- `paleo_workbench/mapping/map_document_snapshot.py` → `render_snapshot.{hpp,cpp}`
  （document_render_snapshot 适配器：分组要素单遍走查、正面积 extent 垫宽、
  owner 级 LRU 要素缓存、extent_for_snapshot、确定性内容修订）。
- Oracle：`tools/oracle/generate_map_document_bridge_fixtures.py`（Python 真源冻结）
  + `mapping_document_tests/fixtures/map_document_bridge_oracle.json`
  + `mapping_document.bridge_session` 测试（含负自检）。
- Python 遗留标注（四个模块尾注 + `CPP_EXTENSION.md`）。

**Out of scope（明确归类）**
- `vector_layer.py` / `edit_delta.py` 核心 → 已由 UI-13 移植
  （`libs/ui_composite/vector_layer`）；数据核**不**复制第二份（禁止平行架构）。
- `ZeroCopyEventBus`（edit_delta.py 的 numpy 消费面）→ 生产者本就是 C++
  （`native/qgis_render_bridge/src/edit_delta_pod.hpp`）；numpy ndarray 排水
  是 Python 专属消费脸，归类 legacy-consumer-only，不移植。
- `map_authoring.py` MapAuthoringDocument → 记录转换部分被
  `libs/ui_data_core/map_edit_items` 与 `libs/ui_map/map_chrome_core`（revision key）
  吸收；剩余面留 UI 桥切片（分类：partial / UI-absorbed）。
- QGIS 桥栈实现（QgsVectorLayer edit buffer 接线）→ libs/qgis 桥切片；本分支
  只定义抽象 `NativeEditBridgeStack` 面（duck-typed stack 的 C++ 形状）。
- `revision_cache.py` → 泛型缓存工具，消费方在 render backend（UI 域），非文档行为层。

**Shared/conflict files**
- `libs/mapping_document/CMakeLists.txt`：追加源文件 + 测试 target（append-only）。
- 根 `CMakeLists.txt`：无改动（mapping_document 已是无条件构建）。
- 其余全部为新文件；与 open PR #1400/#1402/#1404/#1408/#1409/#1410/#1411 无 hunk 重叠。

## Decisions

### D-27d-01 归属：数据核 libs/mapping_document，不进 UI 库
- **选**：四个模块进 `pwb::mapping_document`（Qt-free，仅依赖 Pwb::Domain）。
- **否**：塞进 `libs/ui_composite`。理由：session set / gesture manager /
  controller 是宿主侧纯逻辑（Python 同样无 Qt），UI-13 的 vector_layer 已在
  UI 库；把会话集合与手势计划也锁进 UI 库会让 qgis 桥切片与 workflow 宿主
  被迫依赖 UI 库。render 适配器消费 document_io（数据核内），同址。
- 与 ui_composite 的关系：本分支不改动 ui_composite；其 `INativeEditing`
  实现方（qgis 桥切片）可改用 `pwb::mapping_document` 的 controller + seam。

### D-27d-02 EditSessionSet 栈绑定：裸指针身份，无 weakref
- **选**：`const void*` 非拥有身份指针；`active_layer_ids(stack)` 按指针相等。
- **否**：weakref 等价物（std::weak_ptr）。Python 桥栈是任意对象；C++ 桥栈
  接口由宿主拥有生命周期。契约（头文件声明）：绑定期间调用方必须保活栈对象；
  close()/discard(空集合) 解绑。停发窗口查询的保守语义原样保留：未绑定或
  栈不匹配 → 空集合（不短路）。

### D-27d-03 桥能力面：虚接口默认实现 = 诚实降级
- **选**：`NativeEditBridgeStack` 抽象类，核心四操作纯虚
  （start/commit/rollback_mirror_layer + mirror_features_json）；旧桥缺失面
  （set_mirror_feature_attributes / mirror_layer_dirty /
  restore_mirror_snapshot / set_committed_callback / run_geometry_checks）
  以**虚函数 + 默认"不支持"实现**表达。`bridge_supports` 委托
  `stack.supports_native_editing()`（默认 true；覆盖前 M1 桥的适配器返回
  false，open() 以同文案拒绝——旧桥诚实降级在 C++ 下可复现）。
- **否**：getattr/callable 式运行时探测。接口化后能力是编译期事实；
  降级路径（属性写拒绝、dirty 未知 nullopt、无快照跳过补偿）由默认实现
  自然触发，行为与 Python"旧桥诚实降级"逐条对齐。
- committed 回调：`set_committed_callback(canvas_address, fn)` 默认实现为
  no-op（Python：异常仅 debug log）。Controller 另提供
  `handle_committed` 直连入口（桥宿主显式路由，等价 Python canvas_shim 存在
  时的同一路径）。

### D-27d-04 VectorLayer 消费面：ICommittedDeltaSink seam
- **选**：controller 依赖 `ICommittedDeltaSink`（id()/name()/crs() +
  `apply_committed_delta(delta, session_id, source_tool, gestures)`），不依赖
  任何具体 VectorLayer 类型。
- **否**：把 UI-13 的 `ui_composite::VectorLayer` 拖进数据核依赖，或复制
  VectorLayer。理由：Python controller 对 layer 的消费恰是
  `layer.apply_committed_delta(...)` + `getattr(layer, 'name', layer_id)` +
  `layer.crs`——seam 是该鸭子面的忠实最小投影；具体实现由宿主适配
  （ui_composite::VectorLayer 一行转发即可）。
- geotopo 门禁同理：`gate` / `geology` 是 `std::function`；拓扑门禁为
  `ICommitTopologyGate` 接口（enabled / run_for_commit（桥检查器路径，缺省
  nullopt = 旧桥回落）/ validate_records / record_validation）。
  geology 返回违规 JSON 数组（{layer_id, code, message, severity}；
  severity=="error" 拦截，warning 放行）。

### D-27d-05 错误面与消息文案：逐条复刻
- `(bool, string)` 返回对（Python tuple[bool, str]）；错误消息逐字符复刻
  （含全角标点与「」引号）：门禁拒绝 `reason or "门禁拒绝"`、
  `"当前 QGIS 桥不支持原生编辑（需重建桥扩展）"`、CRS 失配消息、
  `"该图层没有进行中的原生编辑会话"`、`"镜像层进入编辑失败：<err>"`、
  `"回滚失败：<err>"`、`"没有要修改的要素"`、`"没有要写入的属性"`、
  拓扑拒绝消息（前 3 个问题 + `（另有 N 个问题）` + `（全部编辑未提交）`）、
  地质拒绝消息（`<names>：<code>：<message>——共 N 个 error 级违规`）。
- session set 拒绝文案：`"编辑会话进行中——CRS 已冻结，请先保存或回滚编辑"`、
  `"图层「<id>」正在编辑会话中——字段结构变更被拒绝，请先保存或回滚编辑"`。
- Python 异常面在 controller 内部被吞（桥侧异常不逃逸，转错误串）——
  C++ 同构：桥调用包 try/catch，异常消息上浮进错误串。

### D-27d-06 会话集合为宿主持有，不做进程级单例
- **选**：`EditSessionSet` 是普通值类型；controller 构造时接受引用并持有
  （Python 的 `SESSION_SET` 进程单例是模块全局——C++ 由宿主作用域表达
  同一约束"工作台同一时刻至多一个编辑会话"）。controller 提供默认持有的
  构造（内部成员），测试/多工作台宿主注入外部集合。
- reset_session_set 的原地复位契约（引用稳定性）在 C++ 下自然成立
  （引用/指针不因 close() 失效）。

### D-27d-07 render 适配器：JSON 记录形状 + 确定性内容修订
- **选**：`document_render_snapshot(const Json& paleo_doc, Options, ...)`
  ——legacy 文档以 JSON 记录形状进（与 document_io 同一输入约定；
  facies_style / layer_state 为文档 JSON 键）。输出
  `RenderLayerSnapshot`/`RenderSnapshot` 值类型（Qt-free 投影，
  MapLayerSnapshot 渲染相关字段子集；renderer_payload/scale_range/metadata
  不投影——适配器从不产出它们，Python 默认值即空）。
- **否**：移植 map_render_backend 的完整值类型。Python 适配器只消费
  MapLayerSnapshot 的构造参数与 features/extent/data_revision 复用位；
  未消费字段不属于行为契约。
- `_stable_revision`：Python 小集合路径用内建 `hash()`（仅进程内稳定）——
  **不可跨进程复现**，oracle 无法冻结。C++ 契约：全尺寸确定性内容摘要
  （canonical JSON + SHA-256 截断，与 `geometry_hash` 同族）。oracle 冻结
  features/extent/可见性/宿主提供 revision 的复用行为；内容修订只测
  确定性 + 区分性（同内容同值、改内容变值），不测具体数值——
  expectation_source 诚实标注 `cpp-contract`。
- >1000 要素快速路径（#941-4 blake2b 增量）不再需要：C++ 全尺寸走
  单遍分组走查时顺手产增量摘要，无 Python 的 6.1s 退化形态。行为对齐点
  保留：非 feature 形状输入回落通用冻结（诚实降级不会 crash）。
- LRU 缓存：`(const void* owner, document_id, kind, revision)` 键，
  owner 指针身份校验 + 24 条上限 + LRU 驱逐（Python `move_to_end` 同语义，
  C++ `splice` 到 front）；
  C++ 侧缓存为可选 opt-in（传 cache_owner 才启用，与 Python 同）。

### D-27d-08 id 生成：FeatureIdGenerator 复用（D-27-04 延续）
- 补偿手势 id（`new_feature_id("gesture")`）经 `FeatureIdGenerator` seam；
  默认确定性 `gesture_%012x` 计数器，宿主可注入 uuid。
- VectorEditSession 的 session_id / duplicate id 不在本分支（UI-13 拥有）。

### D-27d-09 线程性与所有权
- 全部单线程契约（头文件声明）：controller/session set/gesture manager
  绑定 UI/工作台线程；桥回调（handle_committed）由宿主保证同线程投递
  （Python 同为同步回调）。
- controller 非拥有：栈与层以裸指针/引用进，会话期由调用方保活
  （Python 存强引用 dict——C++ 契约化而非隐藏所有权）。
  pending commits / compensations / gestures 归 controller 所有。

### D-27d-10 oracle 策略
- Python 真源冻结（`generate_map_document_bridge_fixtures.py`）：
  session_set_cases（open/join 拒绝与接受/CRS 失配/schema·CRS 互斥文案/
  停发窗口按栈绑定）、gesture_cases（finish 去重/undo 逆序/redo 正序/
  mark 幂等/clear/audit）、native_cases（gate 拒绝不 startEditing、旧桥
  降级、rollback、读回规范化、属性写矩阵、commit 全或无 + 门禁矩阵 +
  补偿）、snapshot_cases（分组/样式合并/revision 复用/extent 垫宽/
  前缀桥接）。
- 确定性：桥栈用 fake（Python 侧 FakeNativeStack 同型 C++ 侧），uuid 以
  计数器 patch；时间戳/内容修订不冻结（Python 侧 time.time() /
  process-hash 本就非确定），C++ 契约测试补位。
- 负自检：fixture 内嵌 negative 控制（篡改层序/文案/门禁序必须失败）。
