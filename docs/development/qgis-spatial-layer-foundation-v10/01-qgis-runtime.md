# 01 — QGIS runtime foundation（V10）

## 1. 新包 `paleo_workbench/qgis_runtime/`

| 模块 | 职责 |
|---|---|
| `paths.py` | 单一发现权威：`PALEO_QGIS_BUILD_DIR`/`PALEO_QGIS_DEPS_DIR` 环境变量与默认根解析（`vendor_root`/`deps_prefix`/`pyside_dir`）；`QgisRuntimePaths`（paths.py:79）+ `resolve_runtime_paths()`（paths.py:109） |
| `loader.py` | 双配方加载：`LoadRecipe`（loader.py:49，self-contained vendor / conda Qt）+ `prepare_bridge_load()`（loader.py:153）；DLL 预载细节（`_conda_preload`、`_msvcp_pre_pin`、`_ensure_linux_protobuf_compat`）全部内聚于此 |
| `proj_data.py` | proj 数据发现与供给：`locate_proj_db`（proj_data.py:54）/ `ensure_proj_data`（proj_data.py:88）/ `_deploy_into_vendor`（proj_data.py:73） |
| `health.py` | `QgisRuntimeStatus`（health.py:35）+ `probe_qgis_runtime()`（health.py:130）；进程级缓存，`reset_runtime_probe_cache()`（health.py:74）供测试 |

### D1 — loader 收敛为单一权威

起点审计：桥加载逻辑在 5+ 处重复，默认根 3 套并存（repo 本地
`build/qgis-vendor`、`PALEO_QGIS_BUILD_DIR` 覆盖、Windows conda deps
默认前缀）。V10 起 `qgis_style.ensure_qgis_bridge_dll_dirs`
（mapping/qgis_style.py:101）与 `tests/conftest.py` 全部**委托**
loader——发现/加载只有 `qgis_runtime` 一个权威，旧入口保留为兼容转发。

## 2. 桥 0.6.0a0 与 manifest flags

版本漂移修正：`setup.py` 0.4.0a0 / bindings 0.5.0a0 → 统一 **0.6.0a0**
（00-baseline.md §B.4）。manifest 新增 flags（旧桥探测阴性 → 宿主诚实
降级，纪律沿 V9 D7）：

- `runtime_facts` — 一次性运行时事实 JSON（§3）
- `project_crs_push` — QgsProject CRS 推送（02-crs-transform.md §3）
- `map_settings_facts` — mapSettings 快照事实
- `provider_introspection` — provider 能力自省（06-provider-schema.md §1）
- `style_readback` — 样式回读（07-rendering.md §1）
- `layer_scale_range` — 比例尺可见域通道（07-rendering.md §2）
- `current_layer_clear` — 活动层清除通道（00-baseline.md §B.7 漂移位点
  收敛的桥侧配套）
- `digitize_scratch_honest_crs` — scratch 层诚实 CRS
  （02-crs-transform.md §4）

## 3. `runtime_facts()` 一次性 JSON

单次 C++ 调用返回全量运行时事实：QGIS/PROJ/GDAL 版本、prefix/svg
路径、`proj_context_get_database_path` 解析结果、provider registry、
CRS 探针（EPSG:4326/4490/4214/4610 解析有效性 + 4326→4490 变换探针）。
`health._probe_via_runtime_facts`（health.py:87）消费该面；旧桥/探针
失败的环境降级走 `_probe_via_canvas_roundtrip`（health.py:99）。
探针结果即 `runtime_crs_capable()`（02-crs-transform.md §2）的输入。

## 4. proj 数据供给（D2）

vendored build 的 `proj_9.dll` 按 **DLL 相对路径**搜索
`<dll-dir>/../share/proj`。V10 将 proj.db 部署进
`<vendor>/output/share/proj/`（`_deploy_into_vendor`，幂等、记日志），
使 vendor 配方下 CRS 解析可达（关闭 00-baseline.md §B.1）。

**刻意不设 `PROJ_DATA` 环境变量**：docs/adr/0060-vendored-gdal.md 禁止
进程级导出 `PROJ_DATA`——rasterio 自带的新版 PROJ 会抢先解析同一变量，
污染全局坐标链。kill switch：`PALEO_QGIS_PROVISION_PROJ=0`。

### D3 — 双配方并存 + 漂移诊断

默认 self-contained vendor 配方与 conda 配方都是一等公民
（`resolve_recipe()`，loader.py:68）。PySide6/Qt 运行时漂移（基线 §C：
本机 6.11.2 vs 6.8 时代 vendor）由 `probe_qgis_runtime` 诊断输出，
不再散落为难归因的 import 失败。

## 5. boot 顺序（审查 R1-3 修正）

权威钩子在 **`paleo_workbench/__init__.py`**：`load_local_env()` →
`prepare_bridge_load()` → `ensure_geoviz_on_path()`。关键约束是
**loader 必须先于 geoviz bootstrap**——`ensure_geoviz_on_path()` 会
`import geoviz`（→ numpy），numpy/PySide6 先占住进程 DLL 槽位后，conda
Qt 预载就永远晚了（表现 = 桥导入 ENTRYPOINT_NOT_FOUND；V10 loader
二分实证：仅 `import paleo_workbench` 即可复现/修复）。`main.py` 的
启动钩子保留为冗余保险（main.py:19–31）。

conda 配方两个审查修正（loader.py 注释在案）：

1. **预载必须在 add_dll_directory/PATH 之后**——预载 DLL 自身的依赖
   经这些路径解析；顺序反了会让错误的 sqlite3/zlib 抢位。
2. **MSVCP 预载钉仅限 VENDOR 配方**——conda 配方里先钉 System32 CRT
   反而制造 ENTRYPOINT_NOT_FOUND（conda 自己的 CRT 构建必须赢自己的
   槽位；legacy conftest 的 conda 分支从不预钉）。

详见 09-lifecycle.md §1（D15）。

## 6. 本机 boot 配方（2026-09-11 实证可用）

```
PALEO_QGIS_CONDA_QT=1
PALEO_QGIS_BUILD_DIR=C:\Users\wangj.KEVIN\paleo-qgis-build\qgis-vendor
PALEO_QGIS_DEPS_DIR=<conda deps 前缀，本机默认 C:\Users\wangj.KEVIN\paleo-qgis-deps>
```

默认（self-contained vendor）配方在 PySide6 6.11.2 本机不可用
（00-baseline.md §C）；该约束已记入 12-known-limitations.md 第 6 条。
