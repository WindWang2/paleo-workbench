# 04 — 已知限制与后续（V12-C）

1. **QGIS 桥侧 `validate_many` 尚不存在**：本 Goal 未改 `native/`（边界 §4.4）。
   BASE 的 C++ `geometry` 子模块无批量校验函数（对预构建 BASE 桥实测
   `hasattr(validate_many) == False`）。因此**现版桥的生产拓扑校验仍走
   逐要素回退**（行为与 BASE 完全一致）；N→1 的收益在桥侧补上
   `validate_many(geometries) -> list[list[dict]]` 后自动兑现（Python 侧
   探针已就位，无需再改本仓）。**后续单轮**：桥侧实现 + 真桥批量路径的
   运行时验证。

2. **QgisMapRenderBackend 运行时验证**：本 Goal 对它只做了静态审查——
   未改动其任何代码路径（渲染侧改动全部在 `FallbackMapRenderBackend`）。
   镜像 Python 侧（`qgis_mirror`，QGIS 后端运行时会走）的改动由纯 Python
   fake 栈测试覆盖（lifecycle/delta/reset 全绿）；附加通道在真桥在场时
   `test_map_render_backend.py` 17 用例亦绿。**仍建议**在有完整桥构建
   （含 gdal 标量管线）的环境补一轮 `pytest -m qgis` 腿再合入主干。

3. **既有失败（非本 Goal 引入，未修）**：
   - `tests/perf/test_mirror_publish_scale.py::test_full_first_publish_within_budget[50]`
     （预算 60ms，基线实测超限）——提示词已声明的既有失败。
   - `tests/test_mirror_fields_sig.py::test_fields_json_signature_change_forces_republish`
     ——本 Goal 在 BASE 上实测复现同样失败（fields token 未进 no-op 判定，
     BASE 特性即缺失）。**后续单轮**：把 fields_json 签名并入
     `_LedgerEntry`/`unchanged` token 集。

4. **测试通道适配**：worktree 自建 venv 因网络超时未完成；测试全部经仓库
   canonical 的 `run_env.sh`（miniconda 3.13、无桥、offscreen）执行。
   CI（若有）与本地 3.12 venv 环境未逐一复跑全仓。

5. **缓存内存占用**：标量 QImage 缓存每活跃 scalar 层多持一幅自有 QImage
   （约 W×H×4 字节），随图层剪除/shutdown 释放；与 `_prepared` 同界。
   无 LRU 上限（与既有 `_prepared` 语义一致——按主体集合有界）。

6. **QImage 跨线程**：缓存 QImage 会被渲染 worker 线程与 GUI 线程导出路径
   （`render_to_painter`）先后只读使用；与既有共享的 `_prepared` numpy 数组
   同等暴露面（顺序使用、只读、不 detach）。未做跨线程并发写防护（既有
   管线本就不并发写）。

7. **保留的残留物（有意不清理，Karpathy surgical 原则）**：
   - `qgis_mirror` 发布循环里 `cached_signatures` 的预读（读了长度校验后
     未再消费）——BASE 即如此，迁移原样保留；如后续清理需先确认非
     预留接口。
   - `_PreparedLayer.feature_kinds` 与 `vertex_count` 无消费者——非本 Goal
     创建的孤儿，不动。

8. **性能数字的范围**：bench 数字来自本机（Linux，offscreen，软件渲染），
   绝对值随机器变化；相对结论（稳态帧零 rasterize/零全幅拷贝、调用数
   N→1）由计数断言而非墙钟保证。
