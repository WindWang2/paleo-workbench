Segfault bisect (agent-9): culprit = tests/test_geological_modeling_3d_page.py::test_geological_modeling_3d_page_splitter_layout — pre-existing offscreen pyqtgraph GL init failure (commit 603cc6c, 2026-07-22, predates mapping session); deterministic solo repro; mapping EXONERATED (crashing prefix has zero test_map_* files; pytest-free repro needs no native cores). Also FAILs offscreen (pre-existing). Report: .superpowers/sdd/segfault-bisect-report.md. Full suite re-run deselecting the killer in progress.
M1 全部 7 任务完成。终局审查 With fixes → 必修 4 项已修复 (df5aca23)。
M2 backlog（终局审查移交）: I3 screen_to_map 用 QPointF 不截断; I4 refreshCanvas 只同步本画布桥+去 processEvents; I7 shutdown/析构加生命周期锁; I8 巧合用户 extent 被吞; I9 setLayerVisibility/Opacity 加 owned_layers 守卫; addFeatures 返回值/空 GeoJSON 校验; hpp 注释 shutdown 必须先于析构; pyproject requires-python 与实际 3.13 对齐; welllog-engine PySide6 pin 放宽; 7/11 canvas 方法补测试; F2 测试走真实原生工具链; CI 防 cpython-312 .so 残留; README fallback 措辞收窄。

## Bugfix: 图层点击变色（root cause: shim set_layer_snapshot 清空重建不带 style → QGIS 随机色；参照 qgis_render_bridge.cpp apply_renderer_style/build_renderer_from_spec）
Bugfix 图层点击变色: complete (82cb6ab0+02c18d71, 复审通过; merged to main, branch deleted). 遗留 M2: scale_range 未转发(已在 shim docstring 标注)。

## QGIS 原生地图栈 M2 执行（plan: docs/superpowers/plans/2026-09-03-qgis-native-map-stack-m2.md, base: d9440e06, branch: feat/qgis-native-map-stack-m2）
Task 1: complete (commits 45702538 + fix c22146b2, review Critical×1+Important×4 全部修复并复审通过, 计划文本对齐 4512ab2a)
Task 2: complete (commits 4fac8795 + fix 1a7a86e6, review Important×4 全部修复; 注意: 修复 subagent agent-34 与复审 agent-35 各两次 2h 超时, 修复与复审由控制器直接完成并自测 16+42 绿; 独立性缺口留终局全分支审查补)
Task 3: complete (commit 925fcf7a + plan sync 9560adba; 因 subagent 连续超时由控制器直接实现; 5 例新测 + 21 例相关回归全绿; 关键坑已入计划: rowsInserted/rowsRemoved 非 rowsMoved、setData(EditRole) 假 false、moveRow 必须 clone-first 防 registry bridge 误删、可见性/重命名影子表)
Task 4: complete (commit a2a0a228, 控制器直接实现; 6 例新面板测试 + 8 文件相关回归全绿; 适配: test_workstation_shell 树断言改 tree_row_count(), test_composite_gis CRS 测试去掉快照重发断言(增量设计冲突); 新增 display_state_changed 信号→notify_display_changed; upsert 加 is_reference/is_editable 尾参; set_editing_layer 无 ✏ 视觉(报告注明); 搜索框/图例列表/上下移按钮未保留(QGIS 语义由树承担), 菜单 snap 勾选态未带(plain toggle)
Task 5: complete (commit 8e422755, 控制器直接实现; 3 例新测 + 8 文件回归全绿; execLayerProperties 模态 exec 真 QgsVectorLayerProperties, accept 后 renderer_to_xml + labeling save + opacity/name 回传; _open_layer_properties 在 QgisCanvasShim 下分流, _apply_native_layer_properties 复用写回语义(revision+1))
Task 6: 进行中。菜单端到端测试 tests/test_qgis_layer_panel_menu.py 3 例绿(offscreen 关键坑: 菜单事件须发 viewport 经 QAbstractScrollArea 转发; contextMenuAboutToShow 槽内 singleShot 触发动作; programmatic trigger 不退出 QMenu::exec 须显式 close; QPoint(5,5) 须命中行否则 currentIndex 被清空拿空菜单)。README/CLAUDE.md M2 状态已更新。全量回归运行中。
Task 6: complete (commits 79eb9bab teardown 守卫 + 197870d1 菜单端到端/文档)。全量回归对账：51F/6E 初跑中唯一真回归是 test_composite_editing teardown（QgisCanvasShim 已删 setFocus，isValid 守卫修复）；其余 51F/5E 全部在基线 d9440e06 worktree 上逐条复现（缺 layer_model_core/grid_render_core 环境性 + keyboard_shortcuts/shell teardown 预存 flake）。
终局审查 agent-37: With fixes（1C+4I+7M，报告 .superpowers/sdd/m2-final-review.md）。修复 commit 55fcb640：C1 树改名写回权威（include_names 仅 notify 路径，防 stale 面板副本回滚）；I1 零要素图层上树；I2 per-view 生命周期清理（关键坑：destroyed 信号内销毁含 py::function 的 std::function 会在 shiboken 延迟删除链上 GC_Del segfault——孤儿坟场延后到 shutdown/dtor 销毁）；I3 排序测试期望值修正；I4 显式记录接受删除（搜索框列 M3 候选）；M6 死信号删除。修复后 114 例相关套件全绿。
M2 终局全量回归（55fcb640 后）：51F/3E，与基线逐条核对全部预存环境性（缺 layer_model_core/grid_render_core）或预存 flake，零新增红。合并 main（fast-forward d9440e06→55fcb640），本地分支 feat/qgis-native-map-stack-m2 已删，临时 worktree 已清。剩余：用户真机验收（M2 DoD #5）。

## Mock 沉积相预测（plan: docs/superpowers/plans/2026-09-10-mock-facies-prediction.md, base: 7f8a4462）
Task 1: complete (commit 见上行, review clean: spec✅/approved; Minor 记录: clipped payload 含 NaN 需 NaN-aware 比较; seismic 诚实标记无显式测试(probe 已验证); _clip_ring 分支无测试; extent 非数值抛 ValueError 而非 InferenceInputError; ensure_mock_facies_models 耦合 providers 私有 helper)
Task 2: complete (commit 见上行, review clean: spec✅/approved; Minor: 单空键+无信号名的 unknown 回退未显式覆盖; 非 Mapping input_refs 两处分叉为修前已存在(暂 memo))
Task 3: complete (commit 见上行 + 未提交修改: stage_actions.py/mock_facies.py/providers.py/factor_layer_products.py, review clean: spec✅/approved; 阻塞已解: execute_run 剥 _ 前缀参数 → 选项A 双键回退; 偏离记录 D1 run状态="complete" / D2 execute_run 返回 result=None 不抛出(已加守卫) / D4 input_refs 只记本类; Minor 移交终局: mock_facies 错误文案只提 _ 键、stage_actions.py:376 注释易误读、诚实标记 e2e 断言 3/7 可补强)
Task 3 fix wave: complete (3 Important 修复 + 测试; 复审 Ready=Yes)
终局全分支审查: complete (agent-15, With fixes → 修复 → 复审 Yes; 9 条 Minor 全部裁定可留; 文档对齐 commit 见上行)
Task 4 (追加: 无初始相图默认工区空白相): complete (commit 见上行 + stage_actions.py 未提交修改, review approved 无 C/I; Minor: 层名/source 断言可加固、草稿侧死路对称用例、空白相建层失败无提示(极低概率))
Task 5 (追加: readiness 对齐 mock/空白相): complete (commit 见上行 + readiness.py 未提交修改, review approved 无 C/I; Minor 可留: real+mock 混合时计数为 len(real)(更诚实); ≥3 有限点规则两处实现靠注释互指)
Task 6 (基础层 name 字段 schema + 空白相淡化): complete (review approved; 原生探针: fields 有 name、文字像素 20→1236、遮挡缓解)
Task 7 (pybind11 能力探测修复): complete (review approved; _stack_supports_fields_json/_stack_supports_delta 真桥由恒 False 变 True——fields_json 与 delta 通道首次在真桥启用; Minor 可留: alpha 10.2%、_doc_declares 可限首行)
Task 8 (识别工具启用 + 悬浮框): complete (review approved; Important(a) palette 新鲜度已核实=实时 lambda, 无修; Minor 可留: 编修层不判可见口径注释、popup 单值截断、provider 缺席回落)
Task 9 (原生识别覆盖基础镜像层): complete (真桥端到端: 点击井点→回调→面板+悬浮; 引用参考层原生识别仍无覆盖=后续)
