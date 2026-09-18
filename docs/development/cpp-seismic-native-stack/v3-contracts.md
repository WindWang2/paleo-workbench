# Seismic Native Stack — 契约 (feat/cpp-seismic-native-stack)

> 分支职责：把「Native IO → Native attribute pipeline → Native viewer/service」
> 补成不依赖 Python 的产品主链，并清理对应 Python runtime/glue。
> 基线 `origin/main ff67dcf3`；oracle 冻结源 `geo-viz-engine@08851951`
> （loader.py / models.py / cache.py / chunked.py / attributes.py）。
> 本线不做 100G 压测；中等规模（≤ 64³ fixture / 中等真实体）为准。

## 0. Scope ledger

### 本分支负责

| # | 项 | 落点 |
|---|---|---|
| N1 | SEG-Y/PWBVOL1 volume descriptor + metadata-only inspect（含 bin-grid 推断、SourceGroupScalar、nodata、dtype/endian、time/depth 域） | `libs/seismic_io` |
| N2 | chunk/tile 窗口读（半开索引窗，逐 trace/逐行 I/O，绝不整卷驻留）+ CancelToken | `libs/seismic_io` |
| N3 | bounded LRU tile cache（字节预算可配 + env 覆盖 + 统计 + 收缩即逐出） | `libs/seismic_io` |
| N4 | `pwb::viz::ISeismicVolume` 的 tiled 后端（SEG-Y/PWBVOL1），真 chunk_plan，接现有 SliceController/SeismicSliceWidget | `libs/seismic_service` |
| N5 | BinGridGeometry（方位角从北顺时针）+ 与工程空间上下文的稳定 seam（CRS 字符串 + x/y↔IL/XL，不猜 CRS） | `libs/seismic_service` |
| N6 | 6 个 production attribute kernels：sweetness / relative_impedance / dip_il / dip_xl / dip_azimuth / curvature_mean（语义 = geoviz_seismic.attributes，严禁新增算法） | `libs/seismic_attributes` |
| N7 | 平台产品接线：打开体版本改 tiled（免整卷拷贝）、SEG-Y 导入线程化+可取消、属性对话框补新核参数、bin-grid 标定状态显示（x/y 换算 API 由 service 提供，选点 x/y 显示留待 viewer 事件接线，见 v3-migration.md） | `apps/paleo_workbench_platform` |
| N8 | Python oracle（固定解释器）：IO 窗口/边界、6 kernel 数学、BinGrid 转换，含 negative self-check | `tests/cpp/seismic_*` oracle |
| N9 | synthetic 32³/64³ smoke（SEG-Y → tiled open → slice → attribute → publish） | `tests/cpp` |

### 明确不做（本分支外，已在迁移台账归类）

- Zarr v3 sharded 转码 + 生命周期（seismic_transcode/lifecycle）：Python legacy
  infra（zstd/crc32c/shard 原子性）；C++ 产品链以 PWBVOL1 + tiled store 承担
  同一职能（随机窗口访问、免整卷驻留）。转码层列为 removal-candidate。
- Banded 全量属性 job（`.done` 标记/lease）：zarr 专属编排；C++ 主链 =
  TaskRuntime + 整卷 kernel（中等规模）。halo/trace-global 语义记入 N6 契约。
- 3D 渲染、多剖面联动、vd/wiggle、拾取/层位解释、well-tie overlay、LOD 阶梯
  （主计划 M8/M10 明确后置）。
- SEG-Y 写路径（Python production 从不写 SEG-Y，无可迁移物）。
- Harness/agent/provider 层。

### 共享冲突面

- `apps/paleo_workbench_platform/main_window.cpp`：并行 PR（#1349/#1351/#1353
  等）可能触及；本分支只改 seismic `#if defined(...)` 区块与 CMake 可选链接段。
- `libs/seismic_*`、`tests/cpp/seismic_*`、`docs/development/cpp-seismic-*`：
  近 50 提交与其他 open PR 均未触及（已核实），无冲突。
- `libs/visualization`：不改（tiled 后端只消费其公共头）。

## 1. IO 契约（冻结自 loader.py / seismic_reader 既有语义）

- 采样格式：SEG-Y format code **5（IEEE f32 BE）与 1（IBM f32 BE）**；其余
  拒绝（仓库真实样本 tiny.sgy = format 5；数据层 raw.sgy 为截断桩，不属于
  IO 契约）。PWBVOL1 = LE f32 + JSON header（既有格式，不变）。
- 网格：trace header 字节 188/192 BE int32；不假设排序；去重；uniform step；
  完整网格；负 step 归一为升序 + 正 step（既有冻结语义，与 segyio 的文件序
  语义差异已在 D 线 v3-contracts 声明）。
- 轴：inline/xline 物理 (start, step)；sample 轴 dt 来自 binary header µs→ms
  （dt=0 → 1.0）；unit ∈ {"ms","s"}（time 域）/ PWBVOL1 可为 "m"/"ft"
  （depth 域）；SEG-Y 深度域不支持（与 Python view panel fail-closed 一致）。
- nodata：无隐式重映射（Python 转码原样拷贝 float）；descriptor 携带
  `missing_value`（默认 NaN 语义），渲染端已按非有限值处理（既有冻结）。
- bin-grid 推断：3 角迹 CDP_X/Y（字节 180/184）优先，退回 SourceX/Y
  （字节 72/76）；SourceGroupScalar（字节 70-72，>0 乘 / <0 除 / 0 恒等）；
  方位角从北顺时针；不可得则 `bin_grid` 为空，调用方不得伪造默认网格。
- tile 读：`read_window(origin, extent)` 半开索引界、C-order 输出；SEG-Y 按
  trace gather、PWBVOL1 按行 seek；cancel 每 trace/行检查一次；取消 =
  返回 0 + "cancelled"，输出内容未定义（调用方丢弃）。
- tile cache：LRU，键 = tile 原点（tile 形状构造时定，默认 {4,4,2048}，
  沿 sample 轴长条）；`max_bytes` 构造定 + `set_budget` 运行期收缩立即逐出；
  env `PWB_SEISMIC_TILE_CACHE_BYTES` 由 service 层解释；调用方持
  `shared_ptr<const vector<float>>` 只读视图，缓存永不外泄可写句柄。

## 2. Attribute 契约（冻结自 geoviz_seismic/attributes.py @08851951）

全部：输入 volume_f32、输出 volume_f32、shape 不变、逐体（非逐道轴参数）。
精度链按 oracle 逐面对齐：sweetness 的 Hilbert/unwrap/gradient 内部 f64
（scipy hilbert 实测对 f32 输入返回 complex64，再乘 f64 h 升 complex128；
C++ 全 f64，cast f32 前 ~1e-7 相对差，由冻结容差吸收，非位级一致）；
dip/curvature/relative_impedance 则完整复刻 numpy f32 链（NEP 50 弱标量）
——这正是 parity 要求，不做 f64 内部提升。dip_azimuth 在 f32 dip 输出上
以 f32 atan2 + f32 wrap 评估（与 oracle 的 f32 np.arctan2 对齐，
<=1 ulp f32 差由容差吸收）。

| id（单 dot） | Python 源 | 参数（默认） | 语义要点 |
|---|---|---|---|
| seismic.sweetness | compute_sweetness | sample_interval=1.0 | env/√freq_safe，|freq|<1e-6→1e-6，取 |freq|；env、freq 为 f32 输出 |
| seismic.relative_impedance | compute_relative_impedance | — | 沿 sample 轴顺序 cumsum（f32 累加，NaN 永久污染） |
| seismic.dip_il / seismic.dip_xl | compute_dip | dt=1.0, dx_il=1.0, dx_xl=1.0 | atan(grad/grad_t_safe)，|grad_t|<1e-10→1e-10；np.gradient 边界=单侧差分 |
| seismic.dip_azimuth | compute_azimuth | dt=1.0, dx_il=1.0, dx_xl=1.0（透传给内部 compute_dip；atan2 对两侧 dip 的等比缩放不不变，故参数非透明） | atan2(dip_xl, dip_il)（f32 输入），<0 + 2π → [0,2π)（f32 粒度上极角恰为 2π 的样本仍可能出现，oracle 同） |
| seismic.curvature_mean | compute_curvature(kind="mean") | win_il=3, win_xl=3, win_t=3 | slope=grad(单位间距)/grad_t_safe → 3D uniform_filter(size=2w+1, reflect) → 二阶 gradient → (d2_il+d2_xl)/2 |

- uniform_filter(reflect) 的 C++ 实现 = E 线 RMS 同构滑窗和 ÷ n（对称反射），
  三轴可分离。
- ROI/trace-global 规则（哪些核在全 trace FFT 上禁止裁时间窗）属 Python
  banded/ROI 编排层，本线不迁移；文档保留引用。

## 3. Service / 空间 seam 契约

- `SeismicVolumeService`（Qt-free）：`open_segy(path)`、`open_pwbvol(path)`
  → `OpenedVolume { volume, descriptor（bin_grid 在 descriptor 内）, cache }`；
  cache 字节预算来自构造参数，缺省读 env `PWB_SEISMIC_TILE_CACHE_BYTES`
  （非法/缺失 → 64 MiB）。
- `BinGridGeometry`：xy↔(il_frac,xl_frac) 公式逐符号对齐 models.py
  （azimuth 从北顺时针；spacing 可负）；`nearest_il_xl` = round。
- 工程绑定：CRS 以字符串 id 存于 catalog 版本 result_metadata
  （`spatial.crs` / `spatial.bin_grid`），不引入 libs/project ABI 变更；
  未知 CRS 永不猜测（对齐 mapping_kernel crs_policy 精神）。

## 4. 容差与 oracle

- 固定解释器：本线 venv `.venv-oracle`（py3.14 + numpy 2.5.3 + scipy 1.18.1，
  manifest 记录 SHA/版本）；oracle 源 = geoviz_seismic/attributes.py 等价
  numpy 表达式的直接重放。
- 容差：先测后冻（同 E 线协议）：C++ vs oracle 逐 case 最大误差 × 10 余量，
  并附 negative self-check（扰动 oracle ≥1e-3 相对量必须判 FAIL）。
- IO oracle：tiny.sgy 冻结体 + 合成 format 1/5、NaN 样本、乱序网格、
  tile≠整卷窗口、PWBVOL1 深度域、bin-grid 探针（期望 = oracle
  _infer_bin_grid 对写入字节的推断结果）；取消覆盖为预取消标志拒绝
  （读循环内逐 trace 检查的实现由代码审查核对，无中途取消用例）；
  全部与 numpy 逐样本对照。

## 5. 与既有一致性

- `read_segy` 既有语义与 `seismic_io.segy_read` 冻结测试不动；新 inspect/
  tile 重构后必须逐样本复现旧输出（同一测试守护）。
- viewer/controller/widget 契约（D 线 v3-contracts）不变，本线只新增数据源。
- 既有 4 kernel 的 id/参数/容差不动；`register_seismic_attributes` 扩为
  10 个（顺序：既有 4 + 新 6），重复 id 拒绝语义不变。
