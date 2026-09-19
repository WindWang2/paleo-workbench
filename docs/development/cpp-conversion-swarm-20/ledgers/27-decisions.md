# 27-decisions — CONV-27 mapping_document 行为层（edit session / undo-redo / snapshot / IO）

每条记录：选择、被否的备选、理由。歧义裁定原则：对用户流程更诚实、更少抽象。

## D-27-01 范围：文档行为层，不做 QGIS 桥
- **选**：CompositionEditSession（components.py 全量）、命令模型、MapDocument 会话（layers.py 核操作的命令化）、统一 data/style/layout 修订与 dirty state、不可变快照、document_io（features 规范化 + 文件级原子写/恢复）、service 门面。
- **否**：`native_edit_session.py` / `edit_session_set.py` / `edit_gesture_manager.py`（QGIS 桥三段门禁/手势宏——prompt 明确"不做 QGIS toolbar"；其消费面在 libs/qgis 桥切片）、`vector_layer.py` 的 VectorEditSession 顶点命令流（同属桥编辑域）、`edit_delta.py`（矢量会话的可观测性派生物）、`map_document_snapshot.py` 渲染适配器（render backend 接缝，非文档快照）、registry/color_ramps 样式数据（CONV-02 D-10 维持）。
- **理由**：本分支负责"在 libs/mapping_document 数据核之上"的行为层；QGIS 桥切片需要真桥面与离屏画布验收，混入则无法本地验证。

## D-27-02 命令模型：纯 C++，不用 QUndoStack
- **选**：`DocumentCommand` 抽象 + `CommandStack`（undo/redo 栈、revision、组、observer）。稳定 id = 执行序 1 基序号。
- **否**：QUndoStack。理由：(a) 本库 Qt-free（CONV-02 起），拖入 QtCore 破坏 oracle 测试与依赖结构；(b) Python 契约"新命令清 redo、每次 apply/undo/redo revision+1、revert 闭包语义"与 QUndoStack 的 macro/child 命令语义不匹配；(c) 宿主需要 QUndoStack 时可在 UI 层适配。
- id 规则：Python 无 id（闭包），稳定 id 是 C++ 可观测性契约；被拒绝的命令不消费 id。

## D-27-03 错误面：逐条对齐 Python 异常类
- locked 拒绝 → `ComposerError : std::runtime_error`（Python ComposerError(RuntimeError)），消息逐字符复刻（含 `!r` 单引号 repr）。
- 未知元素 → `UnknownElementError : std::out_of_range`（Python KeyError），消息 `no composition element '<id>'`。
- scale 非正值 → `std::invalid_argument("component size must be positive")`；locked 检查**先于**正负检查（Python 顺序）。
- set_paper 未知纸型 → `std::invalid_argument("unknown paper size 'b5'")`（CONV-02 D-12 延续）。
- MapDocument 会话对未知 layer id：**无 Python 等价**（Python 无文档会话）——定为 fail loud（同 composition 的 KeyError 姿态）；而 Python 定义为安静契约的操作维持安静：`remove_layer` 未命中返回 nullopt **且不建命令**、`reorder_layers` 跳过未知 id（核语义）。

## D-27-04 id 生成：宿主职责（D-04 延续）
- `CompositionFactory` 支持注入生成器；默认确定性 `el_%010x` 计数器（测试/oracle 可复现）。document id `comp_<generated>`。
- `document_io` 的 `FeatureIdGenerator` 同理（geometry_schema.new_feature_id 用 uuid4）；默认 `<prefix>_%012x`。
- **否**：在核内引入 uuid 依赖。核保持确定性，产品宿主注入 uuid 生成器。

## D-27-05 组合级 C++ 契约扩展（无 Python 等价，同语义）
- 会话级 `set_paper` / `set_title` / `set_metadata`：与 components.py 既有命令同构（apply 前验证、捕获旧值、refused 不入栈不 bump）。Python 宿主直接改字段；C++ 宿主获得同一路径的可撤销编辑。
- **否**：把它们冻进 Python oracle。Python 会话没有这些方法，无行为真值——在 C++ 测试以内部一致性（undo 复原旧值、拒绝不改状态）验证，"expectation_source" 不撒谎。

## D-27-06 分组编辑 / 回滚：会话层宏
- `begin_group(label)` → 嵌套命令累积进组（首条嵌套命令即清 redo，同"新编辑失效 redo"规则）→ `end_group()` 入栈一条 `GroupCommand`（undo = 逆序 revert 嵌套）。嵌套每条仍各 bump revision（"每个已应用命令 revision+1"语义不变），组 undo 再 +1。
- `rollback_group()`：逆序 revert 已应用嵌套、丢弃组、**revision +1**。文档"变了又变回"，失效型消费者仍需刷新——不 bump 会留陈旧缓存。历史栈不收组条目（部分编辑从未入栈）。嵌套组禁止（std::logic_error）。
- rollback 时 observer 逐嵌套命令通知（map 会话按 kind 计数器各自 +1）。

## D-27-07 document IO：features 移植全量 + 文件层 C++ 契约
- **features_from_document / apply_features_to_document**（document_io.py + geometry_schema.py 的 normalize_facies/well/line/label 全量）：以 JSON 记录形状移植；well 坐标族（(x,y)→(lng,lat)→(lon,lat) 整族取用、绝不交叉配对）、partial x 保留、`coordinate_status` 上游标记不升级（audit #1162 契约）、畸形 label 跳过+诊断——全部冻结进 oracle。
- 已知偏差（诚实记录）：`normalize_line` 对真值但非数组/非 null 的 coordinates（dict/str），Python 的行为是病态的（str 会按字符展开成 `[["a"],["b"]]`）；C++ 按空数组处理。产品路径不可达，findings 已记。
- **文件级**：composition/map document JSON 的保存走 tmp+fsync+main→bak+replace+dir fsync（复刻 project/manager.py `_write_payload` 三段式——Python composition 面板是非原子 write_text，C++ 是**升级**不是平移）；加载恢复表复刻 `_load_data` v6：main 缺失→bak（backup-interrupted-save）、main 损坏→先验 bak 可用才隔离 `*.corrupt-<ts>` 并还原（backup-corrupt-main）、不可读→**绝不**回退 bak（ProjectUnreadable 同姿态）。
- **seam**：`DocumentStore` 抽象（read/write_atomic/rename/remove/exists），产品绑 `StdFileStore`，测试注入内存/故障实现；service 提供 set_store。
- 文件层期望值标注 `cpp-io-contract`（C++ 契约，Python 无此行为），测试以真实临时目录验证。
- **损坏判定包含语义级**：JSON 合法但 kernel parse 失败同样走隔离/还原（manager.py 把 ValidationError 视为 CORRUPTION）；仅当失败源是可信 main（kOk）才触发恢复，备份来源再失败则诚实 kCorrupt（主备皆坏姿态）。

## D-27-08 快照：值语义深拷贝 + 投影
- `capture_map_document_snapshot(doc, revision)`：id/revision(宿主钉的 staleness key)/title/crs/extent/active layer/input_version_ids(核函数 verbatim)/provenance(metadata run_id + provenance 载荷)/每层全字段（style/metadata/features/annotations/extras 深拷贝）。捕获后文档再变不影响快照（测试冻结）。
- 相等：`snapshots_equal` = 标量逐字段 + JSON 语义比较（层序敏感）。
- **否**：快照进 undo 栈（内存放大，且 Python 会话 undo 是命令级）；快照是宿主的 staleness/provenance 输入。
- oracle 冻结的是**文档状态**（Python 真值）；快照投影是 C++ 形状（expected 由冻结文档程序化构建，无手写数值）。

## D-27-09 修订与统一 dirty state：三类计数器 + 单调
- 文档级 `DocumentRevisions{data,style,layout}`：命令按 `RevisionKind` 归类；**apply 与 undo/redo 都 bump 同类计数器**（可逆状态对缓存也是新状态；计数器永不回退——layer 级 data/style_revision 同姿态，layers.py bump 助手语义）。
- `mark_saved()` 锁存 / `is_dirty()` 任一类漂移即脏。composition 服务用"保存时 revision"锁存（composition 无 Python dirty 契约，语义对齐 map 服务）。
- layer 载入式操作贴合 Python 助手：set_visible/set_opacity(clamp)/set_features(extent 重算+data bump，VectorMapLayer 契约含退化垫宽 1e-6 与 math.isclose rel_tol 1e-9)。
- Python 无 MapDocument 会话——会话*历史*语义是 C++ 契约，oracle 冻结的是每步**文档状态**（kernel op 真值）。

## D-27-10 service：每文档类一门面，load 重置历史
- `MapDocumentService` / `CompositionDocumentService`：拥有文档+会话+IO。`load_json/load_file` 成功后**重置会话**（composition_panel.set_document 每次装载新建会话——历史不跨文档）、锁存 saved 基线；`save_file` 原子写 + mark_saved；`snapshot()` 钉当前 revision。
- **否**：单一大服务同时管两类文档。两个小门面各自类型安全，共享 IO 层。

## D-27-11 kernel 变更最小化
- 仅新增 `known_paper_size`（会话需"先验证后建命令"；set_paper 本体不动）。
- 成员函数遮蔽核自由函数（add_layer 等）以匿名命名空间 wrapper 解决，不改头文件签名。
