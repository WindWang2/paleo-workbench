# E 线接口与数值契约 v3（codex/cpp-v2-seismic-attributes）

> 基线：`53e22b679ea3181d4e2c2bca8d42ca272c00dfbf`（common five-line base）。
> 本文先于实现提交（接口先行）：冻结四个地震属性的公共头、语义矩阵、参数/单位、
> 支持范围、容差与 oracle 对照协议。权威头文件：
> `libs/seismic_attributes/include/pwb/seismic_attributes/attributes.hpp`。

## 0. Oracle 身份（固定，只读）

| 项 | 值 |
|---|---|
| geo-viz-engine gitlink（基线冻结） | `08851951f3bbc0beb90886adf52e1928f4383c16` |
| oracle 源文件 | `geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/attributes.py` |
| 四函数 | `compute_envelope` / `compute_instantaneous_phase` / `compute_instantaneous_frequency` / `compute_rms_amplitude` |
| provider 路径 | `attribute_pipeline.py`（trace 族，`axis=0`，time 轴）；`seismic_view.py:1827-1835` 把 `models.py` 的 `sample_interval`（毫秒）除以 1000 传给 `sample_interval_s` |
| fixture 解释器（固定） | `/opt/miniconda3/bin/python3.13`（Python 3.13.14，numpy 2.4.6，scipy 1.17.1） |

已实测核验（不是按名称猜测）的 oracle 精确行为：

1. `scipy.signal.hilbert`（scipy.fft 路径，float32 输入 → complex64 解析信号）谱权重
   `h`：偶 N：`h[0]=1, h[N/2]=1, h[1..N/2-1]=2`；奇 N：`h[0]=1, h[1..(N-1)/2]=2`；
   其余 0。DC 与 Nyquist（偶 N）不乘 2——纯 Nyquist 余弦的包络不为常数（0.63~2.72，
   f=0.5/64 采样实测），本 SDK 复刻同一行为。
2. `np.unwrap`（周期 2π）：相邻差 |d|>π 时按 2π 整数倍修正；恰好 +π 的跳变不修正；
   **NaN 进入 cumsum 后把该 trace 后续全部变成 NaN**（实测 `[0.1, nan, 0.2, …] →
   [0.1, nan, nan, nan, …]`）。
3. `np.gradient`（默认 edge_order=1）：内部二阶中心差 `(p[i+1]-p[i-1])/(2·dt)`；
   首末点一阶单侧 `(p[1]-p[0])/dt` / `(p[N-1]-p[N-2])/dt`；N=1 抛 ValueError；
   N=2 两点同为一阶单侧。NaN 只污染邻近点。
4. `uniform_filter1d(size=2w+1, mode="reflect")` == **np.pad symmetric**（边缘重复；
   实测 ≠ np.pad reflect），窗口对 i 取 `[i-w, i+w]`（奇数长对称），任意 folding。
5. NaN 输入经 FFT 传播到该 trace 全部样本（其他 trace 不受影响）；Inf → NaN 同理。
   常数 -2.5：env=2.5、phase=π；全零：env=0、angle(0)=0。
6. 输出 dtype 链（float32 输入）：envelope/phase/freq 全程 float32（angle→float32，
   unwrap→float32，gradient→float32，÷2π→float32）；RMS 平方/均值走 float64 再转
   float32。**本 SDK 内部以 float64 计算后输出 float32**（工程选择，oracle 自身的
   float32 舍入计入容差，见 §4）。

## 1. 算法注册契约

> 修正记录（实现集成时发现）：基线 `AlgorithmRegistry` 的 id 校验只接受
> **单 dot** 的 `<domain>.<name>` 模式（`libs/algorithms/src/registry.cpp`
> `valid_algorithm_id`），v3-contracts 初稿的 `seismic.attribute.<name>`
> 双 dot 命名会被拒绝。冻结 id 修正为下表单 dot 形式（域 `seismic`，与
> C3 的 `seismic.coherence_c3` 无冲突）。

| 算法 id | 输出端口名 | 输出单位 | 参数 |
|---|---|---|---|
| `seismic.envelope` | `envelope` | `""`（振幅） | 无 |
| `seismic.instantaneous_phase` | `instantaneous_phase` | `rad` | 无 |
| `seismic.instantaneous_frequency` | `instantaneous_frequency` | `Hz` | `sample_interval`（number，秒，>0，默认 1.0） |
| `seismic.rms_amplitude` | `rms_amplitude` | `""`（振幅） | `window`（integer，半窗，0..1048576，默认 21） |

- 四算法各恰好 1 个输入端口 `volume`（volume_f32，required）与 1 个输出端口
  （volume_f32）；输出 shape = 输入 shape，packed C-order，数据为 owned float32
  （`shared_ptr` lifetime 随 ProducedVolume 交付，run() 返回后不保留输入裸引用）。
- family=`seismic_attribute`，version=`1.0.0`，deterministic=true，approximate=false，
  supports_cancel=true。id 与 C3（`seismic.coherence_c3`）无冲突。
- 注册只经 `register_seismic_attributes(AlgorithmRegistry&, build_identity)`
  显式进行；重复 id（含与 C3）被 registry 拒绝并在 `RegistrationReport::rejection`
  报告，后续条目跳过。
- 每个结果带完整 ProvenanceRecord（id/version/build_identity/params/input_refs/
  起止 UTC/wall_time_ms），可被 B 的通用单产物协议消费。

## 2. 语义矩阵（冻结）

所有属性沿 **sample 轴（VolumeView shape[2]）逐 trace** 计算；VolumeView 轴序
`(n_inline, n_crossline, n_sample)`（C 线冻结头）。支持 packed 与任意 permuted
strided 输入（按 `effective_strides()` 寻址，不为切片复制整卷）。Hilbert 是整条
时间 trace 的全局运算，**不切时间块**；空间方向按 trace 分批（批大小只影响进度
粒度与临时内存，不影响数值）。

| 语义点 | envelope | instantaneous_phase | instantaneous_frequency | rms_amplitude |
|---|---|---|---|---|
| 核心 | `abs(hilbert(x))` | `atan2(im, re)` ∈ [-π,π] | `gradient(unwrap(phase), dt)/(2π)` | `sqrt(uniform_filter1d(x², 2w+1, symmetric))` |
| 内部精度 | float64 | float64 | float64 | float64（对齐 oracle 的 float64 平方/均值） |
| 输出 | float32 | float32 | float32 | float32 |
| n_t=1 | 支持（analytic=x，env=\|x\|，phase=0 或 π） | 同左 | **显式拒绝**（oracle ValueError；诊断 `input.sample_count.too_small`） | 支持（窗口折叠到单点） |
| n_t=2 | 支持（h=[1,1]，analytic=x 实数） | 同左 | 支持（两点同为一阶单侧差分） | 支持 |
| 奇/偶/非 2 幂长度 | 支持任意 N≥1（pocketfft 混合基+Bluestein） | 同左 | N≥2 | 任意 |
| NaN/Inf | 传播：该 trace 全 NaN（Inf→NaN）；不静默清洗 | 该 trace 全 NaN | unwrap 的 NaN 向后扩散到 trace 尾部（复刻 cumsum 语义） | 复刻 `uniform_filter1d` 滑窗和的非有限拓扑（实测冻结）：NaN 进入滑窗和后该 trace **其后全部** 输出 NaN；Inf 在窗内输出 +Inf，离开窗口那一步起（Inf−Inf）其后全部 NaN。有限值路径同构（先减后加滑窗和，float64） |
| 常数 | env=\|c\|，phase=0（c>0）或 π（c<0），c=0 → 0 | 同左 | unwrap 全常数 → 频率 0 | RMS=\|c\| |
| 边界 | — | — | 首末点一阶单侧，内部二阶中心 | symmetric（边缘重复）padding |
| dt/单位 | — | rad | `sample_interval` 秒；输出 cycles/s = Hz（provider 传 ms 时由宿主先行 ÷1000，与 `seismic_view.py:1835` 一致） | — |
| window 语义 | — | — | — | `window`=半窗，实际长度 `2·window+1`（默认 21 → 43）；与 Python 相同 |

不变量（独立于 oracle，用于防 oracle 误用）：

- 解析正弦 `A·cos(2πft)`（非 Nyquist）：env≡A；phase 斜率 `+2πf`（实测符号为正）；
  频率 ≡ f Hz（dt 与 f 单位一致时）。
- 常数 c：env≡|c|、频率≡0、RMS≡|c|（任意窗口）。
- RMS 在 `window=0` 时 ≡ |x|；`2w+1 ≥ n_t` 时窗口折叠仍为对称 padding 语义。
- 能量：env² = x² + hilbert(x)²（内部解析信号实部=x）。

## 3. 执行语义（cancel/progress/资源）

- trace 分批（默认按临时缓冲 ≤ 64 MiB float64 复数取批，至少 1 条/批）；批间检查
  `stop_token`：取消返回 `TaskCancelled{stage}`，绝不返回半成品 success。
- progress 单调递增：`completed_traces/total_traces`（stage="traces"），成功末尾
  1.0（stage="done"）；失败/取消不发布终值 1.0。
- FFT 单线程（pocketfft 以 `POCKETFFT_NO_MULTITHREADING` 编译，`POCKETFFT_CACHE_SIZE=0`
  无计划缓存）——不建线程池、不占满 CPU；并行度完全由宿主 TaskRuntime 的 worker 数决定。
- 不写 catalog/文件；kernel 内不复制 TaskRuntime。

## 4. 冻结容差（实现前确定；失败修算法，不放宽）

对照对象为固定解释器生成的 fixture（float32 期望值）。比较规则：

- envelope / rms_amplitude：逐元素双判据 `|a-e| ≤ max(max_abs, max_rel·|e|)`。
- instantaneous_phase：**circular difference** `|wrap(a-b)|`，wrap 到 [-π,π]；atan2
  分支与 ±π 零符号差异天然消解。
- instantaneous_frequency：非 NaN 处双判据；dt 缩放放大已计入。
- NaN/Inf 掩码：C++ 与 oracle 的非有限位置（含 Inf 符号）必须逐元素一致；
  finite/NaN 分布单独统计报告。
- **幅度不确定子集（phase/freq 专用，报告不豁免）**：解析信号在数学上为精确
  零的样本（impulse 类数据实测存在），其相位在任何实现中都是纯舍入噪声
  （oracle float32 ~1e-9、double 路径 ~1e-17，角度任意）。判据：oracle 包络
  `env ≤ 1e-6 · max(该 trace env)` 的样本为"不确定"；phase 在不确定样本上只
  报告偏差不断言；freq 额外把不确定样本的 ±1 邻域一并转为报告（unwrap 链的
  2π 偏移差只在链偏移变化处的 gradient 浮现）。不确定子集的数量与最大偏差
  逐 case 打印，不允许整体跳过。

| 算法 | max_abs | max_rel | 依据 |
|---|---|---|---|
| envelope | 1e-5 | 1e-4 | oracle complex64 舍入 ~1.2e-7·A |
| instantaneous_phase | 1e-4 rad | — | complex64 angle 舍入 ~1.2e-7 rad |
| instantaneous_frequency | 5e-3 | 1e-2 | float32 unwrap 链 + ÷dt 放大（dt=0.002s 时 ÷2π·500） |
| rms_amplitude | 1e-6 | 1e-5 | oracle 平方/均值即 float64，滑窗和同构 |

fixture manifest 逐 case 记录容差；实测误差逐算法报告 max_abs/max_rel 与
finite/NaN 掩码统计，不允许"通过"二字带过。

## 5. CMake 消费契约

- 独立入口：`cmake -S libs/seismic_attributes -B build/... -G Ninja`，target
  `Pwb::SeismicAttributes`（STATIC，cxx_std_20，无 Qt/QGIS/Python 依赖）。
- 存在 `Pwb::Science` 时复用；否则 `add_subdirectory` 同 checkout 的
  `libs/algorithms`（不复制源码）。测试额外经 `Pwb::Workflow`（同规则回退引入
  `libs/workflow`）冒烟真实 TaskRuntime。
- `PWB_SEISMIC_ATTRIBUTES_BUILD_TESTS`（默认 ON）：注册 `seismic_attributes.*`
  CTest（缺 fixture/依赖即 configure FATAL_ERROR，不静默跳过）；A 线根构建可置
  OFF 只消费库。
- FFT 依赖固定为 vendored `src/detail/pocketfft_hdronly.h`
  （mreineck/pocketfft cpp 分支，commit `c90e55b3d529f8efa40ed01a20de22405f45fc65`，
  BSD-3，SHA256 `3e9a05318d8e3b1446bda1c4617e6a103cdd23599ae0a776a92a6e8800e92fdc`）；
  不新增共享依赖清单，不从构建时拉取网络。

## 6. 与 Python oracle 的冻结契约差异（显式声明）

1. 内部精度 float64（oracle envelope/phase/freq 链为 float32）；输出同为 float32，
   差异计入 §4 容差。
2. `sample_interval` 语义冻结为"秒 → Hz"（与 provider 实际传参一致）；Python 函数
   本身允许任意单位（ms → kHz），SDK 不提供 ms 入口，宿主负责换算。
3. `window` 上限 1048576（显式支持范围，超出注册层拒绝）；Python 无上限。
4. 频率算法在 n_t<2 时显式拒绝（诊断码 `input.sample_count.too_small`）；Python
   抛 ValueError——同为拒绝，形式不同。
5. 空 shape/零乘积由 `validate_request` 拒绝（`request.input_volume.invalid` 系）。

## 7. 边界

- 不修改：C 的 algorithms/registry/types/science_suite、数据库、D 的 viewer、旧
  Python 生产实现、子模块 gitlink。公共 SDK 缺陷交 C 线（保持基线可独立验证）。
- 本轮不做：dip/curvature/sweetness、SEG-Y/Zarr backend、通用调度、GUI。
- 端到端发布由 A 负责；B 入库未被本线测试证明（publisher 替身在模块测试中收集
  结果并如实标注）。
