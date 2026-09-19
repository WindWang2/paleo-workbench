# 27-findings — CONV-27 mapping_document 行为层

盘点与移植过程中发现的事实记录。

## F-27-01 Python 三方会话面盘点（source of truth 地图）
- `composer/components.py`（431 行）：CompositionEditSession 是**唯一**有完整 undo/redo 真值的 Python 会话；产品调用方只有 composition_panel.py（每次装载新建会话、undo/redo 后 emit session.revision、锁切换可撤销）。测试：test_composition_components / test_composer_registry / test_composer_charts。
- `layers.py`（716 行）：MapDocument 的 add/remove/reorder/recompute 是直接突变、无历史；add_layer 每次调用 recompute_extent 且首个 layer 变 active；remove_layer 活动层回落首层；reorder 未列层尾随（全仓无产品调用方，但被 harness/pipeline 间接消费面依赖的 add/recompute 是真路径）。
- `document_io.py`（167 行）+ `geometry_schema.py`（230 行）：features 规范化胶水；well 坐标整族门禁（audit #1150/#1162）、畸形 label 跳过。
- `map_document_snapshot.py`（409 行）：**渲染适配器**（MapRenderSnapshot），不是文档快照；其 revision 语义（data_revision << 32 | session_revision）属 render backend。
- `native_edit_session.py` / `edit_session_set.py` / `edit_gesture_manager.py`：QGIS 桥编辑域（三段门禁、停发窗口、手势宏），本分支范围外。
- `edit_delta.py`：命令流的**派生**可观测性记录（不 apply/revert/persist）。

## F-27-02 composition_panel 保存是非原子 write_text
`ui/pages/composition_panel.py:851-907` 直接 `Path.write_text(json.dumps(...))`——与 project/manager.py 的三段式原子写不同。C++ document_io 对 composition/map document 文件统一走 tmp+fsync+main→bak+replace；Python 侧标注为 compatibility（升级空间留在 Python 面板，行为契约由 C++ 面提供）。

## F-27-03 Python `get_spec` 对未知类型降级 TEXT（不抛错）
registry.get_spec 把未知 element_type 降级为 TEXT spec（与 from_dict 的 forward-compat 载体同姿态）。C++ 以 SpecProvider seam 表达：registry 数据不移植（D-10），宿主 provider 复刻"未知→TEXT"策略；provider 返回 nullptr 时工厂 fail loud（诚实：C++ 侧没有隐式 TEXT 默认数据）。

## F-27-04 z-order 的 min/max default 语义
Python `min((e.z_index ...), default=0)` 的 default 仅对**空**集合生效；C++ 初值 0 会作为候选参与比较（全负 z 的 send_to_back 会错）。已按"首元素种子 + 全量比较"复刻（oracle z_order_ties 案冻结）。

## F-27-05 Composition element 引用在 sort 下不稳定
`elements.sort` 会移动 vector 元素——按引用捕获的 undo 闭包会悬垂/指错元素。所有字段级命令以 **id 在 apply/revert 时重新查找**（会话单线程拥有文档，查找恒有效）。Python 无此问题（sort 重排 list 不动对象）。这是一次移植期被 oracle 抓不住、靠架构 review 排除的隐患（闭包在 oracle 序列内恰好不跨 sort 复用）。

## F-27-06 normalize_line 非数组坐标的病态 Python 行为不移植
`raw.get("coordinates") or []` 为真值 dict/str 时，`[list(p) for p in coords]` 会迭代键/字符（str → `[["a"],["b"]]`）。产品路径不可达；C++ 按空数组处理并在此记录偏差。

## F-27-07 fixture 生成器的确定性 id
生成器 patch 了 `components.uuid` / `components._new_element_id` / `layers.uuid4` / `geometry_schema.uuid4`（各模块绑定点不同：`import uuid` vs `from uuid import uuid4`），共享一个十六进制计数器，**每个 case 重置**；C++ 测试用同规则的 CaseIds / FeatureIdGenerator 复现。层的 payload 冻结为完整 `to_dict()`（registry 烘焙的默认样式 + post_init extent 重算是冻结契约的一部分）。

## F-27-08 Python 侧标注
`paleo_workbench/mapping/composer/components.py`、`layers.py`（文档行为面）、`document_io.py`、`geometry_schema.py` 的 normalize 族：C++ 主链 `libs/mapping_document` 已有完整对应物（oracle 冻结对账）。这些 Python 模块转 role=oracle-only/legacy-reference：C++ 产品链（service 门面）不再需要 Python 即可工作；Python 继续作为 oracle 与 UI 过渡期实现。无 Python-only 残留缺口。

## F-27-10 review A（parity）确认的偏差边界（全部非产品路径）
- bind_template 的 binding key 非字符串标量（0/[]/True）：Python `or` falsy → ""，C++ dump 形态不同；key 输出形态仅影响消息级。context 值非 object：Python dict() 抛 TypeError 未捕获，C++ 跳过（C++ 更稳）。
- normalize_well/features 的 id/name 为非字符串标量：Python `or` 链保留原始类型，C++ 统一 py_str 字符串化。fixture 仅用字符串 id。
- apply_features 的 facies `style` 为真值非 dict：Python 原样保留，C++ dict_copy → {}；非 Mapping 的 feature：Python AttributeError，C++ 跳过（更稳，诚实记录）。
- `quoted()` 的 repr：含引号/控制符 id 的消息形态与 Python repr 有差异（消息级，不影响对账断言）。
- warn_unknown_fields 的 composition/map 判型是启发式（按 elements/paper_size 键）；误报只进诊断不进数据。
- 核 `reorder_layers` 重复 id 输出序与 Python dict 首插序的差异为 CONV-02 既有行为（unique id 下无差异），本分支未改。

## F-27-11 review B（架构）确认与修复
- 已修（P0/P1/P2）：Python 标注改为注释（原 RST note 破坏 import 链）；apply_features 空 coordinates 数组的 UB（Python len==0 → MISSING，len==1 → INVALID+partial x）；GroupCommand undo/redo 按**嵌套命令逐个**通知 observer（混合 kind 组正确 bump 各计数器，与 rollback 对称）；create_document 默认 id 生成器缺失；bind_template 空 fields 列表不过滤（Python `if fields:` falsy）；configure 校验顺序（locked 先于 properties 检查）；coerce_ring 非数值标量 → throw（整条 feature 跳过，Python ValueError 路径——`_is_point` 只排除容器不验证数值，实测确认）；normalize_line 标量元素 throw、字符串元素按字符展开（Python list(p) 语义）；StdFileStore replace 失败无条件 bak→main 回滚 + tmp 清理；语义级损坏（JSON 合法但 kernel 契约失败）同样走隔离/还原（manager.py ValidationError 分支）；隔离文件名加进程内序号（秒级时间戳防碰撞）；FeatureIdGenerator 拷贝共享计数器（shared_ptr，无悬垂 lambda）；service 禁用拷贝/移动（session 持文档指针）；会话 move 契约文档化（仅限空历史 rebind）；observer 契约（不得抛出）+ 栈内吞异常保护；rollback 先 revert 后通知（与 run 一致）；GroupCommand 补 id；getpid POSIX 守卫；_is_point 布尔坐标（Python bool 是 int）；py_isclose inf 分支。
- 文档化（P3）：clear_history 对 open group 不回滚（手势历史复位语义）；会话单线程契约（edit_command.hpp / document_service.hpp）。

- 本分支只新增 libs/mapping_document 文件 + CMakeLists 的 CONV-27 块 + 顶层 CMakeLists 的 CONV-27 option 块 + tools/oracle 新生成器 + ledgers/27-*。与 open PR #1346（data/workspace）、#1348（workflow）、#1349（prediction）、#1347（build/packaging）无共享文件冲突。
- 顶层 CMakeLists.txt 的插入点（# END CONV-02 之后）为机械追加块，冲突风险低。
