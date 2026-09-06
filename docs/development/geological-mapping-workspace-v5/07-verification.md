# 07 — 验证（本地测试与性能）

## 测试套件（全部本地跑，无 CI 依赖）

| 文件 | 数量 | 覆盖 |
|---|---|---|
| `test_mapping_workspace_domain.py` | 42 | 纯领域：stages/profiles/roles/组模板/视图状态/迁移/readiness/freshness |
| `test_qgis_layer_groups.py`（`-m qgis`） | 13 | 桥级组 CRUD/嵌套/上提/事件/XML 往返/controller reconcile/拖放校验 |
| `test_mapping_stage_ui.py` | 9 | 阶段条/面板/编辑目标不继承/显隐覆盖保持/RAW 门禁/持久化/降级 |
| `test_mapping_stage_e2e.py` | 5 | RAW→DERIVED、typed 约束、下游 STALE 不覆盖、Manager roundtrip |
| `test_mapping_stage_teardown.py` | 2 | 30× 生命周期循环、工程切换无泄漏 |
| 回归（composite/workstation/qgis 树/面板/XML） | 105 | 新旧两种桥配置下全绿 |

运行（fallback 路径无需桥）：

```bash
pytest tests/test_mapping_workspace_domain.py tests/test_mapping_stage_ui.py \
       tests/test_mapping_stage_e2e.py tests/test_mapping_stage_teardown.py
# QGIS 桥路径（worktree .so 优先）：
PYTHONPATH=native/qgis_render_bridge pytest -m qgis tests/test_qgis_layer_groups.py
```

## 性能基准（`benchmarks/mapping_stage_tree_benchmark.py`）

合成 50/200/500/1000 层 × 30 嵌套 factor 组，真实桥路径，3 次取中位
（本机实测，2026-09-06）：

| 规模 | 全量 reconcile | no-op reconcile | 阶段切换×2 | 每层全量 |
|---|---|---|---|---|
| 50 | 4.0ms | 0.7ms | 0.26ms | 81µs |
| 200 | 69ms | 1.9ms | 0.6ms | 345µs |
| 500 | 855ms | 5.1ms | 1.4ms | 1709µs |
| 1000 | 7677ms | 13.3ms | 4.2ms | 7677µs |

**Gate 语义（§69/§70）**：交互路径必须线性良好——实测 stage switch
16.7× / no-op 18.2×（线性参考 20×，即亚线性达标）；全量 reconcile 的
超线性为上游 QGIS `takeChild/insertChildNode` 信号转发固有成本（生产既有
`set_mirror_layer_order` 同曲线，非本分支回归），且只在工程装载/首次构建
发生一次——稳态全部走增量（no-op 13ms @ 1000 层）。批量放置 API
（`apply_tree_placements`）已把逐个 move 的 O(N²)（每次全树 find + 全画布
sync）压到单次建索引 + 单次同步。

## 三轮深度 review（本地，全部发现已修复）

1. **正确性轮**：P0×2（主工具栏/修复几何绕过 RAW 门禁——已下沉为单点门禁
   + 保存路径纵深防御）、P1×5（目标不重置/legacy 信封压平组/拖拽不落盘/
   stale 失真/拖放不自愈）、P2×5——全部修复并有回归测试。
2. **架构轮**：红线 2-7 符合（解耦/纯领域/中央画布/不重复造轮/窄模块）；
   红线 1 的三处悬空接线（拒绝不拉回/接受不落盘/失败显隐不重试）修复。
3. **UX/对抗轮**：三大反馈回路断裂（徽标/定位/编辑目标）接线修复；
   叠加动作幂等与井/震分类修复；诚实徽标 + 动态 tooltip。

## 已知边界

- 测井预测是井曲线域结果（WELL_INTERVALS）：Phase 1 地图叠加支持
  VECTOR_POLYGONS 空间结果（地震相预测即此类）；曲线本身经测井 dock 联动
  查看（既有机制）。
- 单因素等值线叠加依赖 live 网格缓存（打开制备页后可用）；缓存缺失时诚实
  提示，不重算。
- 100GB 地震体经验基准：明确不做（Goal 边界）。
- factor 树节点级状态 glyph（§26 的 ✓/⚠/● 装饰）未实现——factor 完成度与
  过期状态经就绪度清单/阶段条徽标呈现；组级聚合 API 已就绪待后续接线。
- 阶段工具栏命令过滤（§43 的 per-stage 命令集）以阶段面板上下文动作 +
  编辑目标门禁实现；MapActionController 全量命令仍可见（高级用户自由）。
- fallback 画布（无 QGIS 桥）为诚实降级：平铺树 + 「分组功能不可用」提示，
  阶段上下文（面板/动作/持久化）仍可用。
