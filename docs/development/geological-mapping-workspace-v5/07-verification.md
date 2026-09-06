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

## 已知边界

- 测井预测是井曲线域结果（WELL_INTERVALS）：Phase 1 地图叠加支持
  VECTOR_POLYGONS 空间结果（地震相预测即此类）；曲线本身经测井 dock 联动
  查看（既有机制）。
- 单因素等值线叠加依赖 live 网格缓存（打开制备页后可用）；缓存缺失时诚实
  提示，不重算。
- 100GB 地震体经验基准：明确不做（Goal 边界）。
