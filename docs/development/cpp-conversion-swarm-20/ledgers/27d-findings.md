# 27d-findings — CONV-27d bridge edit domain

## F-27d-01 真缺口裁定（与 UI-13 的边界）
CONV-27（27b）D-27-01 排除的"QGIS 桥编辑域"在 UI-13（PR #1406）中被部分吸收：
`libs/ui_composite/vector_layer.{hpp,cpp}` 已移植 `vector_layer.py` +
`edit_delta.py` 核心（VectorFeature/VectorLayer/VectorEditSession/EditDelta/
delta_from_command/geometry_hash），`composite_controller.hpp` 只声明了
`INativeEditing` seam（**仓库内无任何实现**）。本分支盘点后确认剩余真缺口为
四个纯逻辑模块（session set / gesture manager / native controller / render
adapter），全部落 `libs/mapping_document`，不复制 UI-13 已有面。

## F-27d-02 会话集合按需生长的拒绝路径
`open()` 在集合已开时只做 CRS 匹配检查（Python 同）——角色门禁在 `open`
入口已挡；入集（request_join）时不再复查 open 的 gate（Python 同：门禁复查
发生在手势波及的 request_join 调用点，宿主传入）。C++ 的 EditSessionSet::
request_join 接受任意 gate，宿主组合自由。

## F-27d-03 Python 病态/不可复现行为裁定
* `map_document_snapshot._stable_revision` 小集合路径用内建 `hash()`——
  仅进程内稳定（str 哈希随机化），跨进程/跨语言不可复现。C++ 契约：全尺寸
  确定性内容摘要（canonical JSON + SHA-256 截断）。fixture 中内容派生
  revision 冻结为 null，C++ 测试只验确定性与区分性（D-27d-07）。
* `#941-4` 的 >1000 要素 blake2b 快速哈希路径不再需要——C++ 单遍分组走查
  本就不存在 Python 的 6.1s 退化形态；确定性摘要全尺寸统一。
* `handle_committed` 对非 dict 解析结果（如 JSON 数字）的行为：Python 会把
  truthy 非 dict 存进 pending 并在 apply 时 AttributeError；C++ 诚实丢弃 +
  warning 诊断（产品不可达路径，记录不移植理由）。

## F-27d-04 补偿恢复的前置条件
快照捕获仅在 **≥2 层** 且全部会话的栈具备 `restore_mirror_snapshot` 时进行
（单层失败无"已提交层"可补偿；审查 Standards#7）。捕获本身是
`mirror_features_json(id, 0)` 的 JSON 字符串（Python str 传递；C++ 侧为
Json 值，RestorableStack fake 内做 str→parse 以对齐生产管道）。补偿失败的
层尽力回滚并记 warning，绝不在失败路径上再抛异常（D9 逃生口语义）。

## F-27d-05 拓扑门禁的桥检查器路径条件
Python 走桥检查器需同时满足：`topology.checker` 存在 **且** 栈有
`callable(run_geometry_checks)`。fixture 的 `_TopologyProbe` 用 `checker`
属性 + 栈上的 `run_geometry_checks` 能力位表达；C++ `ICommitTopologyGate::
run_for_commit` 返回 `available=false` 表示旧桥回落 `validate_records`。
首次 fixture 生成曾把该条件简化为 probe 单属性，被 oracle 生成过程纠正
（commit_gates 用例全部回落，冻结值与生产路径不符）——已按生产条件修正。

## F-27d-06 oracle 生成器的快照纪律（过程教训，防回归）
* 参与断言的可变状态必须**逐条目快照**：`layer_calls` 曾引用活 list、栈的
  `pending_delta`/`mirror` 曾按引用共享，导致 commit/pop 污染已"冻结"的
  期望值。修法：entry 构建时 `list(...)` / `json.loads(json.dumps(...))`
  深拷贝。
* fake 的能力面必须与 tests/test_topo_m1 的 FakeNativeStack 同型
  （`set_committed_callback` 在基类），否则 Python 侧行为系统性偏移
  （committed 增量永不回写）且 C++ 忠实移植反而"不一致"。
* 验证手段：生成器改动的每一步都用 `python3 -c` 直接断言 fixture 的
  相关 entry，而非只看"文件写出了"。

## F-27d-07 nlohmann 数字类型与语义比较
nlohmann 解析正整数存为 `number_unsigned`，`Json(long long)` 为
`number_integer`；`json_semantic_diff` 对**原始类型枚举**敏感（int vs
unsigned 视为类型差）。测试构造计数时用 `std::uint64_t` 与 fixture 对齐
（域库比较器的行为对既有测试是契约，不在本分支改动）。

## F-27d-08 渲染适配器的 records 覆盖与 null 语义
Python `records=None` 表示"从文档导入"；fixture 以 JSON null 冻结。
C++ `RenderSnapshotOptions::records` 为 `std::optional<Json>`——测试装载时
必须区分"键缺失/null"（不覆盖）与"数组"（覆盖）；`visibility` 缺 kind 即
可见（Python `dict.get(kind, True)`）。

## F-27d-09 分组走查的坐标边界
`_grouped_features.expand` 的形状契约：**2 长度数值叶即按点消费并返回**
（非有限对被丢弃且**不下钻**）；首两元素非数值才下钻。首版 C++ 用
is_finite_pair 失败后下钻，与 Python 在含 inf/nan 的嵌套环上发散
（facies 几何未经叶子校验、可携带非有限坐标），已按 Python 早返回语义修正。

## F-27d-10 资源门禁
共享重槽被并行任务（cpp-close-04-data-preview，Build 持锁）占用期间，本分支
仅做 targeted ninja `-j2`（≤ -j3 硬上限）：4 个新翻译单元 + 1 测试 TU +
既有测试复编译，无全树编译、无 OOM。Configure 直接 cmake（Configure 不属
重资源步）。

## F-27d-11 独立 review（Round A/B）修复记录
subagent 独立 review（parity + 架构）结论与处置：
- **P0-1 会话注册表保序**：controller 的 `sessions_` 原为 `std::map`（字典序），
  丢失 Python dict 的插入序（= 集合加入序，首层为活动层）。commit 顺序、门禁
  首个失败层、失败切分、checker 驱动栈、record_validation 序、
  session_layer_ids 全部依赖该序。修复：`session_order_` 向量承载加入序 +
  map 仅做查找；新增 `join_order_not_id_order_governs_commit` oracle 用例
  （zeta-9 先开先提交，字典序会误排 alpha-1 在前）作回归守卫。fixture 未抓住
  的原因：原用例 id 恰好按字典序加入。
- **P1-1 `value()` 抛出**：nlohmann `value(key, 字符串默认)` 对"存在但
  null/非字符串"抛 type_error.302。Python 对应路径是跳过/字符串化/放行。
  修复：record.kind / record.id / layer_state.kind / violation.severity 全部
  改为 find + `py_truthy`/`py_str`（severity 缺省 = error 拦，非字符串 =
  放行，与 getattr 语义一致）；document.id 同样防御。
- **P1-2 pending_changes 异常逃逸**：Python 捕获探针异常返回 None；C++ 补
  try/catch + warning 诊断 + nullopt。
- **P2-1/P2-2 Python float/or 语义**：读回 id 链与 geometry/exists 的 falsy
  判定改用 `py_truthy`；坐标数值化改用 `py_float`（bool 计 0/1、数字字符串
  可解析——与库内 `is_point_node` 的 bool 约定一致，且忠实 Python float()）。
- **P2-4 records 源惰性化**：features_from_document 移入首个需要走查的
  ensure_group（全缓存命中路径不再重复导入文档，#941/#461 语义保持）。
- **P2-6 生命周期契约补写**：open() 头文件声明 stack/layer 保活义务与
  callback 捕获 this 的销毁顺序（Python 栈持绑定方法强引用的 C++ 替代契约）。
- **P2-9 测试健壮性**：身份 token 改为独立哑对象地址（去掉 &token+N 的
  严格 UB）；补 handle_committed op 分支（防未来 fixture 扩展静默退化）。
- **P2-10**：决策文档"FIFO 驱逐"更正为 LRU（move_to_end ≡ splice-to-front）；
  错误串 helper 增加 string 重载免多余 Json 拷贝。
- 澄清一处 review 笔误：readback properties 非对象时 Python 确实是
  `dict(None)` TypeError 被外层 try 捕获后 **整体返回 []**（非向上抛）——
  C++ 现行为与之一致，注释保留。
