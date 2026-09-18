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

## F-27-09 与并行分支的交互
- 本分支只新增 libs/mapping_document 文件 + CMakeLists 的 CONV-27 块 + 顶层 CMakeLists 的 CONV-27 option 块 + tools/oracle 新生成器 + ledgers/27-*。与 open PR #1346（data/workspace）、#1348（workflow）、#1349（prediction）、#1347（build/packaging）无共享文件冲突。
- 顶层 CMakeLists.txt 的插入点（# END CONV-02 之后）为机械追加块，冲突风险低。
