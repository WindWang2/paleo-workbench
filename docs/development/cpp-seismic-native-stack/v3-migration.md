# Seismic Python → C++ 迁移台账（feat/cpp-seismic-native-stack）

> 逐面分类基线：origin/main `ff67dcf3` 的 Python seismic production surface。
> 分类：complete（C++ 等价且已接线）/ partial（C++ 有子集）/ core-only-unwired /
> Python-only / oracle-only。本线处置后，C++ 产品主链（导入 → 数据面 → 属性 →
> viewer）不再依赖任何 Python。

## 1. 本线替换（Python → native）

| Python surface | 文件 | 处置 | C++ 落点 |
|---|---|---|---|
| SEG-Y 结构读取（segyio 封装面） | geo-viz loader.py / paleo_workbench/viz/seismic_load.py | **native 替换**（读路径）；Python 版降级 oracle/legacy | `libs/seismic_io` inspect/tile read（format 1/5、乱序网格、NaN 透传、取消） |
| chunked 随机窗口访问（zarr chunked reader 的职能） | geoviz chunked.py、seismic_volume_source.py read_* | **native 替换**（PWBVOL1+SEG-Y tile 窗口读 + bounded LRU tile cache）；zarr 层列 removal-candidate | `libs/seismic_io` tile_read/tile_cache、`libs/seismic_service` tiled_volume |
| 字节预算 slice cache（RamSliceCache / seismic_volume_cache.py） | 同上 | **native 替换**（TileCache：字节预算、set_budget 收缩即逐出、统计、线程安全；env `PWB_SEISMIC_TILE_CACHE_BYTES`） | `libs/seismic_io` tile_cache |
| IL/XL↔x/y（BinGridGeometry，未接线的 seismic_volume_state.py） | seismic_volume_state.py | **native 替换并首次接入产品**（打开体时显示标定状态；catalog metadata codec） | `libs/seismic_io` volume_descriptor.hpp、`libs/seismic_service` spatial_context |
| SEG-Y→统一体访问的 `open_volume` 门面 | geoviz chunked.open_volume | **native 等价**（SeismicVolumeService.open_segy/open_pwbvol；zarr 分派不在 native 范围） | `libs/seismic_service` volume_service |
| 6 个 production attribute kernels（sweetness / relative_impedance / dip_il / dip_xl / dip_azimuth / curvature_mean） | paleo_workbench/seismic_attributes.py KERNELS 表 + geoviz attributes.py | **native 替换**（oracle fixtures 冻结，容差见 fixtures/manifest.json） | `libs/seismic_attributes` volume_attributes.cpp |
| 属性注册面（4→10 个核） | 平台显式注册 | **native 完成**（主链 10 核；c3 仍在 libs/algorithms） | `apps/paleo_workbench_platform` main_window.cpp 注册块 |
| GUI 线程重任务导入 + 不可取消 | platform importSegy（C++ 侧既有缺口） | **native 修复**（读→工作线程 + CancelFlag + QProgressDialog 取消；catalog 发布留在 GUI 线程） | `main_window.cpp` importSegyDialog/publish_segy_import |
| 打开体版本整卷驻留 | platform openVolumeVersion（read_volume_payload 全量） | **native 修复**（SeismicVolumeService tiled 打开，内存 O(预算)） | `main_window.cpp` openVolumeVersion |

## 2. 保留 Python（明确归类，非本线替换）

| Python surface | 分类 | 理由 / 后续 |
|---|---|---|
| SEG-Y→Zarr v3 转码 + shard 原子性 + 混源防护（seismic_transcode.py） | **legacy / removal-candidate**（依赖 segyio+zarr+psutil；C++ 产品链以 PWBVOL1+tiled store 承担同一职能） | 若未来需要 zarr 生态互通，独立立项（需 zstd/crc32c C++ 依赖） |
| 转码生命周期（stale/resume/lease，seismic_lifecycle.py） | legacy（依附 zarr derived store） | 同上 |
| Banded zarr 属性 job（`.done` 标记 / band resume / ROI halo 编排，seismic_attributes.py 后半） | legacy infra（zarr 专属编排）；halo/trace-global 语义已在契约文档保留引用 | C++ 主链 = TaskRuntime + 整卷核（中等规模；本线明确不做 100G） |
| SEG-Y 预览解析（seismic_parsers.py） | compatibility（UI Python 页自用） | C++ ingest 的 preview 可后续用 inspect_segy 补齐（独立小任务） |
| geoviz SeismicView 引擎（3D 渲染/多剖面/vd/wiggle/拾取/well-tie） | Python-only（主计划 M8/M10 后置） | 未排期 |
| 层位解释生命周期、预测页、井震联合页、harness/agent/provider | Python-only / harness / agent | 非 C++ 产品链范围 |
| Python oracle 生成器（tests/**/oracle/*.py） | **oracle-only（永久保留）** | 固定解释器冻结 fixtures；负自检已内置 |

## 3. C++ 产品闭环（本线后）

导入（工作线程+可取消）→ B 入库（PWBVOL1 Raw 版本）→ 属性（10 核，
TaskRuntime，真发布）→ 查看（tiled service，免整卷拷贝，切片/拉伸/选区/
坐标/时深关系不隐式换算）。全过程无 Python 参与；Python 仅作为
oracle/fixture 与 legacy 页面存在。
