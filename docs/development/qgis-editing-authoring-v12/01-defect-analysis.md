# 01 — 缺陷根因分析（Defect Analysis）

所有结论均在本机真桥环境实测过（命令与输出见 00 §3）。行号一律以基线提交 `9347f6cf` 为准。

---

## D-A（P0）v2 顶点拖动在 MSVC 上必然崩溃：参数求值顺序 + use-after-move

**现象**：设了画布当前层且原生会话打开时，在顶点上按下鼠标即进程级 `access violation`（不是"没反应"，是整个应用死掉）。`tests/test_qgis_topo_m1_native_editing.py`、`tests/test_qgis_topo_m2_cross_layer.py` 两套**已提交**的真桥用例在当前 Windows 构建下必然崩溃（F1）。

**证据（插桩定位）**：探针逐句输出到 `[PWB] BSD assign ok` 后即崩，说明崩在 `beginSharedDrag` 的后续成员写：

```
[PWB] press v2 shared=2 all_layers=0
[PWB] press v2 -> beginSharedDrag
[PWB] BSD enter this=00000265D70C1450 n=2
[PWB] BSD member ok
[PWB] BSD member data=0000000000000000 size=0
[PWB] BSD assign ok          ← 之后崩
Windows fatal exception: access violation
```

**机理**：`native/qgis_render_bridge/src/edit_tools.cpp:1031`

```cpp
beginSharedDrag(shared.front().pos, std::move(shared));
```

- `beginSharedDrag` 第二个形参是**按值** `std::vector<VertexRef>`（`edit_tools.cpp:493`）。
- MSVC 的实参求值顺序是**从右往左**：先求 `std::move(shared)` 并**移动构造**形参——调用方的 `shared` 被掏空（`data()==nullptr, size()==0`）。
- 随后才求 `shared.front()`：对**空容器**取 `front()` = `*begin()` = 解引用空指针，绑出一个指向地址 `~offsetof(VertexRef,pos)` 的引用。
- `beginSharedDrag` 里第一次**解引用**该引用的语句是 `drag_anchor_ = anchor;`（`edit_tools.cpp:498`）→ 访问违例。

**为什么一直没被发现**：GCC/Clang 的实参求值顺序是**从左往右**，同一个写法在 Linux 上先绑定引用、后移动容器（vector 移动是缓冲区易主，引用仍然有效），因此完全正常——M1/M2 的验收记录、V10 文档里的"已交付"都是 Linux 腿的结论，Windows 腿从未真正跑过这套用例。

**修复（已实测，一行）**：

```cpp
const QgsPointXY anchor_ = shared.front().pos;   // 先取锚点（此时容器仍非空）
beginSharedDrag(anchor_, std::move(shared));     // 再移动容器
```

修复后：`test_qgis_topo_m1_native_editing.py` **5 passed**、`test_qgis_topo_m2_cross_layer.py` **5 passed**（F4），共享节点跨层联动拖动、单宏撤销、提交增量、回滚、避免重叠裁切、追踪全部走通。

**同类隐患巡扫**：`git grep -E '\b(front|back)\(\)[^;]*std::move' HEAD -- native/` 全仓仅此一处；`edit_tools.cpp:615/800` 的 `const std::vector<VertexRef> refs = std::move(shared_drag_);` 是"移动后只用局部量"，安全。

**验收**：M1/M2 两套用例在 Windows 腿上必须进常规门（见 05 §M0-3、06 §2）。**只跑 Linux 腿的门禁是这次漏网的直接原因**——任何"平台相关求值/内存语义"的修复都必须双平台钉住。

---

## D-B（P0）新建图层永远不会成为画布当前层 → 顶点编辑静默失效

**现象**：用户报「顶点编辑不能用，在图上没法编辑顶点」；拖动顶点**什么都不发生**，也没有任何提示。

**证据（宿主级探针，真桥）**：`create_layer → 树选中该层 → start_editing()`（原生会话已开 = True）全流程中，桥侧**接受**的 `set_current_layer` 调用次数 = **0**（F5）：

```
--- after create_layer ---      call ('composite:layer_0aab…', False, 0)   ← 被桥拒绝
--- after re-select same layer ---  （无新调用）
   can_edit_layer: True
--- after start_editing ---      （无新调用）    native session open? True
RESULT: accepted current-layer pushes for new layer = 0
```

桥侧拒绝的原因：`set_current_layer` 对未知 `doc_id` 抛 `std::invalid_argument("unknown doc_id for current layer: …")`（`native/qgis_render_bridge/src/map_stack_service.cpp:5405`）。

**机理（三段链，缺一不可）**：

1. **推送早于发布**：`create_layer()` 在 `self._layers[layer_id] = layer` 之后立刻 `self.set_active_layer(layer_id)`（`composite_editing.py:895`），而镜像入项目发生在下一行之后——`layers_changed.emit()`（`:897`）→ `_sync_composition(immediate=True)`（`composite_document.py:1160`）→ `_sync_composition_now()`（`:4756`）→ `set_layer_snapshot()` → `mirror_snapshot_to_stack()`。**推的时候层还不存在**。
2. **失败被静默吞掉且没有重试**：`canvas_shim.set_current_layer` 把异常 `except Exception: pass`（`canvas_shim.py:853-856`），且没有任何补偿路径——镜像发布完成后**没有任何地方重推当前层**（`grep set_current_layer` 全仓仅两个生产调用点：`set_active_layer` 与 `_ensure_identify_layer_current`）。
3. **同 id 重入被短路**：`set_active_layer` 在 `layer_id == self._active_layer_id` 时直接 `return`（`composite_editing.py:1287-1288`）；`_on_user_active_layer_changed` 也先做 `if target == current: return`（`composite_document.py:3323-3332`）。于是**用户点树里的这一层也不会重推**——用户无法自救，只能"切到别的层再切回来"。

**后果**：桥侧 `editLayer()` 要求 `canvas->currentLayer()` 属于 `mirror_edit_connections`（`map_stack_service.cpp:5269-5282`），当前层为空/陈旧 → 返回 `nullptr` → `PwbVertexTool` 退化为 **v1 回调模式**（`edit_tools.cpp:1004` 起的 `if (QgsVectorLayer* layer = editLayer())` 分支不进）→ 走 `pickFeature/nearestVertex` 后发 `vertex_moved` 回调。

而宿主侧此时**没有可用的 Python 会话**：原生会话下 `layer.edit_session is None`，`VertexTool` 就是用 `session=None` 构造的（`composite_editing.py:2123-2126`、`:2156-2159`）。于是 `map_tools._commit_vertex` 里 `session.feature(...)` 抛 `AttributeError` → `except Exception: return False`（`map_tools.py:48-71`）→ `dispatch_edit_pick` 认为 `ok=False`……

**叠加缺陷 D-B2（P1）失败不上浮**：`dispatch_edit_pick` 只为 `vertex_inserted/vertex_deleted` 合成拒绝文案（`canvas_shim.py:334-337`），`vertex_moved` 失败时 rejection 为空 → **既不发 `commit_rejected` 也不发 `tool_operation`**，用户看到的就是纯粹的"没反应"（F6）。

**修复（四层防御，缺一层就还会复发）**：

1. **会话开启后重推当前层**（最小闭环）：`start_editing()` 在 `native_editing.open(...)` 返回 ok 之后、`_rebind_active_tool()` 之前，调用 `canvas.set_current_layer(layer.id)`（`composite_editing.py:1388-1394` 一带）；`join_native_layers()` 入集新层时同办（`:1731`）。
2. **同 id 也要能重推**：`set_active_layer` 的短路改为"id 未变**且**画布已确认该层为当前层"才 return（需要画布侧提供一个 `current_layer_doc_id()` 查询面；或在 `set_layer_snapshot` 成功后统一重推一次活动层）。
3. **桥侧兜底**：`editLayerProvider` 在 `canvas->currentLayer()` 不是会话层时，回落到"会话集合中唯一的可编辑层"（与 `PwbIdentifyTool` 那次修复同构——identify 早就不依赖 currentLayer 了，见 `map_stack_service.cpp` identify 工具段）。这样即使宿主推送链再断，v2 依然工作。
4. **拒绝可见化**：`dispatch_edit_pick` 给 `vertex_moved` 补同款合成拒绝；并且**工具激活期**就应拦截——若原生会话已开但 `editLayer()` 建立不起来，`set_map_tool("vertex")` 应返回失败原因（宿主已有 `native_tool_activation_failed` 通道，见 `composite_document.py:1206-1208`），而不是让用户拖半天没反应。

**验收**：新增宿主级用例——"新建草稿 → 开始编辑 → 激活节点编辑 → 断言画布当前层 == 该层 → 拖动顶点 → 几何改变"，Windows 腿必跑（当前 0 个用例覆盖这条链；现有真桥用例全部手工 `set_current_layer`，见 `tests/test_qgis_topo_m1_native_editing.py:58-59`）。

---

## D-B3（P1）全层档 + CRS 未知 → 候选全丢 → 落框选 → 静默

`discoverAllLayers` 逐层过滤 `if (!ref.layer->crs().isValid()) continue;`（`edit_tools.cpp:438`），并且跨层比较要求同 CRS。若镜像层 CRS 未声明（`qgis_mirror._qgis_crs_for_snapshot` 可返回 `""`）则**所有候选被丢弃** → `shared` 为空 → 进 `startBoxSelect()`（`edit_tools.cpp:1029-1032`）→ 短按（位移 < 10px）在 `finishBoxSelect` 里以 `callback_("pick_miss")` 收尾（`:559-567`）→ shim 对 `pick_miss` 直接 `return`（`canvas_shim.py:1287-1288`）→ 又是静默。

**修复**：① CRS 过滤改为"以编辑层 CRS 为基准，未知 CRS 的层参与但坐标按原样比较"或至少在过滤掉全部候选时回落到单层档；② `pick_miss` 上浮为可感知状态（状态条一行"未命中可编辑顶点（可能是图层坐标系未声明）"），不做无声死键。

---

## D-C（P1）图层栈序：面板与画布的三处不一致

**C-1 引用序反转（真 bug）**：`QgisLayerTreePanel._push_mirror_order`（`layer_tree_panel.py:417-434`）

```python
self._canvas.stack.set_mirror_layer_order([str(layer.id) for layer in self._layers])
```

但 `self._layers` 是**组装序（自下而上）**，同一文件在回声路径上明确反转（`:638-646`："桥回声 order 是 top-first……必须反转"），`qgis_mirror.py:1124` 也反转（`list(reversed(seen))`）。桥侧 `setMirrorLayerOrder` 把 `input[0]` 当**最顶层**（`map_stack_service.cpp` 的 `rbegin()..rend()` + `insertChildNode(0, node)`）。三者对照 ⇒ **只有 `_push_mirror_order` 少了一次反转，整栈被倒置**。

可达路径：洋葱皮时间轴 `_raise_layer_to_top` 循环调 `move_layer(id, -1)`（`ui/components/stratigraphic_timeline_slider.py:486-497`）——用户把某期次层"抬到最上"，实际落到了最下。

**C-2 组模式下整条推送静默 no-op**：`_push_mirror_order` 在 `self._group_controller is not None` 时直接 `return`（`:425-426`）。工作站默认就是组模式 ⇒ 洋葱皮置顶/复原**什么都不做且无提示**。

**C-3 回退面板与原生树上下语义相反**：回退 `LayerManagerPanel` 按 `_layers` 顺序铺行（`composite_document.py:770-777`），行 0 = `_layers[0]` = **最底层**；原生 `QgsLayerTreeView` 行 0 = **最顶层**（QGIS 约定）。而 `_move_up` 的 `move_layer(id, +1)` 语义是"index-1 = 更靠后绘制"（`:689`）——同一句"上移"，两套面板方向相反。

**C-4 新增层落点与 QGIS 约定不同**：新层被追加到「本组尾部」（`layer_tree_diff.py:228-235` 的 `LayerMove(new_parent, index)` + `layer_tree_plan.py:144-151`），即组内**最先绘制**（最下），而 QGIS 的 "new layer on top" 语义是置顶。面板与画布彼此一致（同一棵树），但与用户预期和扁平模式（新层追加到领域列表尾 = 顶层）不一致。

**修复方向**：① `_push_mirror_order` 补反转，或更彻底地**删掉这条旁路**，一律走 `LayerGroupController` 的 placement reconcile（单一权威）；② 组模式下 `move_layer` 必须改走组控制器的 placement 写入（否则就禁用并给出原因，不做无声 no-op）；③ 回退面板统一到"行 0 = 顶层"（含 `_move_up/_move_down` 方向），或明确废弃回退面板并将测试切到原生树；④ 新增层落点按 QGIS 约定置顶（在归属组的头部插入），并同步 `layer_tree_plan` 的默认带位。

**验收**：新增不变量用例（两栈各一）：`mirror_tree_order_top_first() == 面板行序 == canvas 图层序`，覆盖"新建 / 拖拽重排 / 洋葱皮置顶与复原"四个动作（现有 `tests/test_layer_order_parity_v11.py` 只比数据模型与桥序，**从不比面板行与画布像素序**）。

---

## D-D（P1）标注顺序：回退栈与原生栈语义不一致

**原生栈（已正确）**：标注在**几何之后单独一个 pass** 绘制，排序依据 `QgsLabelSorter`：先 `zIndex`，同 `zIndex` 时按画布图层序（top-first 列表里位置靠前的层最后画）⇒ **顶层标注压在最上**（`third_party/qgis/src/core/labeling/qgslabelingengine.cpp:56-83, 104`；画布层序见 `qgslayertreemapcanvasbridge.cpp:163-177` 与 `qgsmaprendererjob.cpp:546-549` 的"从栈底开始画"）。

**回退栈（不一致）**：点层标注在**该层绘制过程中内联**画出（`mapping/map_render_backend.py:1558-1571`，由 `_paint_layer_points` 调用），于是**下层标注会被上层几何覆盖**；只有 worker 路径把标注推迟到帧末统一画（`:940-970` 收集 `_LabelSpec` → `_finalize_frame` 的 `_paint_label_specs`），两条路径语义不同。

**第二处不一致**：QGIS 标注对话框产出的 `labeling_xml`（含 Priority / Z-Index / 避让设置）会原样下推原生栈（`style_codec.cpp:325-396`），但**回退渲染器的标注代码完全不消费它**（`_flatten_qgis_style` 只把它转发给原生线）。于是"用户在对话框里设了标注优先级"在回退栈静默失效。

**修复方向**：① 回退栈统一为"收集 → 帧末按图层序（自下而上）绘制"，保证与原生同序（顶层标注最后画）；② 至少在回退栈解析 `labeling_xml` 的 `zIndex/priority` 参与排序（或明确降级并在 UI 上提示"该设置仅在 QGIS 渲染路径生效"）；③ 加跨栈一致性用例：两层同锚点标注 → 断言顶层标注覆盖底层。

---

## 缺陷关系图（为什么"看起来是一件事，其实是两件"）

```
用户报「顶点编辑不能用」
        │
        ├─ D-B  宿主不推当前层 ──► editLayer()==nullptr ──► v1 回调 ──► session=None ──► 静默失败（99% 的现场）
        │                                                                            └─ D-B2 失败不上浮
        │
        └─ D-A  MSVC 求值顺序 ──► 只要 v2 真的被激活（例如用户切层切回来）──► 进程崩溃
                                                                     └─ 文档/用例都以为它"已交付"
```

**结论**：D-A 与 D-B 必须一起修。只修 D-A ⇒ 用户拖动变成"依然没反应"（v2 根本没被激活）；只修 D-B ⇒ 用户一拖就崩。两者的共同验收口是同一条链路用例（05 §M0-3）。
