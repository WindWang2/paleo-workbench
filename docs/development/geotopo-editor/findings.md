# Findings（侦察结论，2026-09-14）

架构侦察（Explore agent 全量报告，关键事实摘录）：

## 双编辑权威
- Python 权威：`VectorLayer` + `VectorEditSession`（`paleo_workbench/mapping/vector_layer.py`），纯对象 undo 命令栈（before/after patch），无 Qt。
- 原生权威：桥内镜像 `QgsVectorLayer` 编辑缓冲 + QGIS 自有 QUndoStack（`beginEditCommand/endEditCommand` 每手势每层一个宏）。
- 桥接：`NativeEditSessionController`（`mapping/native_edit_session.py:35`），`commit_all()` 顺序提交 + 失败回滚后续层；**已提交层不回滚**（Ticket 5 要补的缝隙）。

## 跨界 POD 约定
- 几何运算（`geometry` 子模块）：GeoJSON 字符串进出，异常 → `QgisGeometryError`。
- mapstack 编辑操作：返回错误字符串（空=成功）。
- 快照/增量：feature dict `{id, wkt, attributes}`；编辑调用用 GeoJSON。
- 画布/树身份：`std::uintptr_t`。

## edit_tools 双模式
- v1 = 回调 Python 权威（镜像只读）；v2 = `setEditLayerProvider` 命中 M1 原生会话层后直接写镜像层 EditBuffer。
- 共享节点检测精确 1e-8（`kSharedNodeEpsilon`，edit_tools.hpp:58）；`avoidIntersectionsV2`、`addTopologicalPoints` 已在用。
- `emitGestureMulti`（edit_tools.cpp:855-904）已支持多层手势回执 `{"layer_doc_id","layers":[...],"gesture","undo_text","features":[...]}`。

## 构建与加载
- pyd 由 setup.py 构建（非 CMake）；源文件清单在 setup.py:335-345 **与 CMakeLists.txt:92-99 双处维护，必须同步**。
- vendor 复用：`PALEO_QGIS_BUILD_DIR` 指向主仓 `build/qgis-vendor`（或 junction 默认路径）；artifacts 齐 → 跳过 configure。
- 本 worktree：junction `native/qgis_render_bridge/build` → 主仓 build（.gitignore 覆盖 `native/**/build/`）。
- venv：uv 创建 .venv（py312.13），`uv pip install -e .` + pytest 栈 + pybind11/setuptools + pip。
- Qt 前缀 `C:/deps/Qt/6.8.0/msvc2022_64`；VS2022 Community vcvars64。

## 测试基建
- `@pytest.mark.qgis` 无 pyd 跳过（conftest.py:110）；`PALEO_REQUIRE_QGIS=1` fail-closed。
- 纯 Python 测试用 `FakeNativeStack`（test_topo_m1_native_editing.py 模板）；真桥测试用真 `QgisMapStack` + QTest 鼠标（test_qgis_topo_m1_native_editing.py 模板）。
- 命令：`QT_QPA_PLATFORM=offscreen python -m pytest -p no:randomly tests/...`。

## 相分类
- `resources/facies_taxonomy.json`：`_meta` + `tree`（8 相/24 亚相/66 微相），**无任何邻接/相序数据**——Ticket 4 需新增邻接资源。
- 加载器只读 `payload["tree"]`，_meta 附加键被忽略 → 独立 `facies_adjacency.json` 资源 + `from_project` 覆盖，最外科。

## 现有能力缺口（本任务要填）
- C++ 无任何 DCEL/polygonize；Python `polygonize` 仅 shapely（geometry_operations.py:464）。
- `split_mirror_features` 存在但无属性标记/自动拾取穿越面（Ticket 2 增量）。
- 无共边检测/共边联动重塑（Ticket 3 全新）。
- 无地质语义校验（Ticket 4 全新）。
- capability_manifest 被 test_qgis_capability_manifest 钉住 → 本任务不改 manifest，新能力走新 `geotopo` 子模块 + hasattr 探测。
