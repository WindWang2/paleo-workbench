# 04 — Native authoring: capture, snapping, topology（V9）

## 1. 捕获语义（W9，Goal §6/§12）

用户选择「物源方向线」这类地质目标时的完整链路：

```
StageActionDispatcher._create_role_layer（物源方向线…）
  ├─ create_layer(template=)              # 几何类型 + 模板 schema + 样式
  ├─ register_layer(role)                 # stage membership（角色权威）
  ├─ apply_capture_spec(layer_id)         # V9：角色 → 捕捉推荐 + 拓扑建议
  │     └─ SnappingService.apply_role_profile（写 per-layer 覆盖 + rationale 回执）
  └─ _sync_composition_now
        └─ snapshot metadata.role = role_of_layer()   # V9：单权威派生
              └─ qgis_mirror._fields_json_for_metadata → QgsFields/约束/控件
                    └─ _verify_published_schema       # V9：发布后读回比对
```

捕获执行（QGIS 权威）：原生 `QgsMapToolDigitizeFeature`（scratch 层 CRS
钉定 canvas destinationCrs，mid-change 拒绝——V7 既有）→ 完成几何 →
`_on_digitize`：

1. **CRS 守卫（V9 W7）**：`canvas_destination_crs` vs 会话层存储 CRS
   可证不同 → `commit_rejected`（「坐标帧不同的写入是静默损坏」）；
   任一侧未知 = 不比对（不新增假失败）。
2. `commit_geometry` → `VectorEditSession.add_feature`（命令/undo 链不变），
   默认属性 = 模板 `field_defaults()`；模板未指定时按角色 spec 的
   template_key 派生（`_capture_defaults_for_role`——与显式模板同注册表，
   无第二套默认）。

## 2. 捕捉（W4）

- 角色簇 profile 词表 + rationale（见 03-decisions D5）。
- 三个消费面：建层即应用（`apply_capture_spec`，全保真 per-layer 覆盖）、
  设置对话框行 tooltip（解释）+ 右键「按角色推荐」（全局模式框 + 行内
  顶点/线段/容差；endpoint/intersection/midpoint 的唯一表达面是全局框，
  accept 单写径不变）。
- 下推链：`_push_snapping_config` → `set_snapping_config` JSON（Advanced
  Configuration per-layer 条目 + endpoint/intersection flag + **V9
  `topological_editing`**（manifest 门控后才发））。

## 3. 拓扑（W2）

- **运行时错误计数**：`TopologyService.record_validation` /
  `refresh_error_count` / `cached_error_count` / `forget_error_count`
  （缓存设计见 03-decisions D2）。刷新点：save_edits/flush 校验、拓扑开关
  开启、`geometry_command`（merge/split 后）、undo/redo（含复合组整组）、
  `delete_selected`、`validate_active_layer_topology`、图层删除 forget。
- **QGIS 顶级编辑下推**：拓扑开关随捕捉配置推送
  `QgsProject::setTopologicalEditing`——原生数字化器在捕获时保持共享
  边界；宿主 `TopologyService`（顶点传播 + 保存校验）仍是权威，两层同向。
- merge 的 `topology_error_count > 0` 门禁从此有真实生产者。

## 4. 测试

- `tests/test_v9_snapping_capture.py`（19 项）：profile 词表、覆盖通道、
  RAW 无推荐、对话框集成（tooltip/右键应用）、controller 注入、快照
  metadata.role、捕获默认派生、模板键注册表不漂移。
- `tests/test_v9_interaction_facts.py`：计数缓存生命周期（未校验=0、
  会话终结不计、forget、merge 门禁消费）。
- `tests/test_qgis_v9_bridge_surface.py`：真桥上的 topological_editing
  推送、role 标注快照发布 → QgsFields 物化 → 读回验证（端到端闭环）。
