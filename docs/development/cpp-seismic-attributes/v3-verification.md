# E 线验证记录 v3（codex/cpp-v2-seismic-attributes）

> 验证日期：2026-09-17。本机：Linux x86_64（内核 6.18.50-2-lts），GCC 16.2.1，
> CMake 4.4.3，Ninja 1.13.2。所有重型 configure/build/ctest 经共享资源门禁
> （本机无 pwsh，使用 `tests/cpp/seismic_attributes/gate.sh` —— 与
> `scripts/cpp-migration/Invoke-ResourceGate.ps1` 同协议的 Linux 等价实现：
> 独占 `.bare/cpp-migration-heavy.lock` flock、≥8 GiB 可用内存否则 exit 75、
> CMAKE/CTEST_PARALLEL_LEVEL=2、OMP/BLAS 线程=1、构建产物限本 worktree
> `build/` 下）。

## 1. 身份链

| 项 | 值 |
|---|---|
| 基线 | `53e22b679ea3181d4e2c2bca8d42ca272c00dfbf` |
| 契约先行提交 | `7c6a75da9e1b2fddd312a64cfde19b9e6232927f`（公共头 + v3-contracts + pinned pocketfft） |
| 冻结 fixtures 提交 | `7a4ca481f8f3d57596ea557f8daf7132d7504209` |
| 实现提交 | `0e6aeed29529005a5fdba609b37a58e227b761d8` |
| geo-viz-engine gitlink | `08851951f3bbc0beb90886adf52e1928f4383c16`（worktree 内已按 gitlink 初始化，干净） |
| oracle 解释器（只读） | `/opt/miniconda3/bin/python3.13`：Python 3.13.14，numpy 2.4.6，scipy 1.17.1 |
| FFT 依赖 | mreineck/pocketfft cpp 分支 commit `c90e55b3d529f8efa40ed01a20de22405f45fc65`，vendored `src/detail/pocketfft_hdronly.h`，SHA256 `3e9a05318d8e3b1446bda1c4617e6a103cdd23599ae0a776a92a6e8800e92fdc`，BSD-3；`POCKETFFT_NO_MULTITHREADING` + `POCKETFFT_CACHE_SIZE=0` |
| 消费的 C 线冻结头 | v3-contracts §0 的 7 个 blob SHA（基线版，未改动；本线对 C 的增量仅消费） |
| TaskRuntime 版本 | 基线 `53e22b67` 内的 `libs/workflow`（C 线 v3 发布顺序修复 `86d8b38c` 未入本基线；见 handoff §4） |

## 2. 真实命令与退出码

```
# 门禁探测（每次重型步骤均经 gate.sh；全程内存 52 GiB 可用，无 75 拒绝）
tests/cpp/seismic_attributes/gate.sh -- cmake -S libs/seismic_attributes \
    -B build/cpp-seismic-attributes -G Ninja -DCMAKE_BUILD_TYPE=Release   # exit 0
tests/cpp/seismic_attributes/gate.sh -- cmake --build \
    build/cpp-seismic-attributes --parallel 2                             # exit 0
tests/cpp/seismic_attributes/gate.sh -- ctest --test-dir \
    build/cpp-seismic-attributes -C Release --parallel 2 \
    --output-on-failure --no-tests=error --timeout 600                    # exit 0
```

- 编译告警：本线源码 0 error；`src/attributes.cpp` 0 warning（pocketfft 以
  pragma 压制；`libs/algorithms/coherence_c3.cpp` 有 1 条基线固有的
  `-Wformat-truncation` 告警，属 C 线文件，未改动）。
- CTest：**4/4 通过，0 失败，0 跳过**（`seismic_attributes.kernels` /
  `.registration` / `.runtime` / `.perf`），最终复验同样 4/4。
- Qt/QGIS/Python 链接检查：`ldd` 测试产物仅 libstdc++/libm/libgcc/libc；
  `nm` 库目标无 python/Qt/qgis 符号（0 匹配）。

## 3. Oracle 语义实测冻结（生成 fixture 前用固定解释器核实）

以下不是按名称猜测，均已在固定解释器上实测（脚本内嵌于会话记录，结论冻结进
fixture 与实现）：

1. `scipy.signal.hilbert`（scipy.fft 路径）谱权重：偶 N `h[0]=1,h[N/2]=1,
   h[1..N/2-1]=2`；奇 N `h[0]=1,h[1..(N-1)/2]=2`；DC/Nyquist 不乘 2。纯
   Nyquist 余弦包络非常数（0.63–2.72 实测）——SDK 复刻同一行为。手工复刻
   float64 对 scipy float64 误差 2.5e-16。
2. `np.unwrap`：+π 精确跳变不修正；NaN 进入 cumsum 后**其后全部 NaN**
   （实测 `[0.1,nan,0.2,…] → [0.1,nan,nan,nan,…]`）。
3. `np.gradient`（edge_order=1）：内部二阶中心差，首末一阶单侧；N=1 抛
   ValueError（SDK 显式拒绝码 `input.sample_count.too_small`）；N=2 两点同值。
4. `uniform_filter1d(mode="reflect")` == **np.pad symmetric**（边缘重复）；
   ≠ np.pad reflect（实测两者不等）。
5. `uniform_filter1d` 非有限拓扑（实测）：滑窗和 `s=(s-old)+new`（先减后加）；
   NaN 进入后**整条尾部 NaN**（5000 长实测无重置恢复）；Inf 在窗内 +Inf、
   离开那步起 Inf−Inf=NaN 尾部。SDK 逐操作复刻（nan_inf case NaN 63/63、
   mask_mismatch=0 全对齐；有限值路径同构滑窗和）。
6. dtype 链：oracle envelope/phase/freq 全程 float32（abs/angle/unwrap/
   gradient/÷2π 均保 float32）；RMS 平方/均值 float64。SDK 内部 float64、
   输出 float32，差异计入容差。
7. 解析不变量（生成器 self_check 强制）：整周期余弦 env≡0.8 精确、freq≡30
   Hz；常数 env=|c|、rms=|c|；provider 路径 axis=0 与 axis=-1 逐 trace 等价。
   常数负值的 float32 相位链在尾部留 ~2e-5 Hz 噪声（实测发现，宽容差 1e-3
   校验，C++ double 路径输出精确 0，fixture 如实冻结 oracle 值）。
8. impulse 类数据：解析信号存在**数学精确零**样本（exact 计算验证
   5.5e-17≈0），其相位在任何实现都是纯舍入噪声（oracle float32 ~1e-9 复数、
   double ~1e-17），角度差可达 ~π；unwrap 链 2π 偏移差在 gradient 浮现为
   1/(2dt)=250 Hz（实测）。按契约 §4 幅度不确定子集协议报告。

## 4. 数值对照结果（52 项检查，0 失败）

每行来自 `seismic_attributes.kernels` 实际输出（`PWB_SEISMIC_ATTRIBUTES_
FIXTURE_ROOT` 指向 `tests/cpp/seismic_attributes/fixtures`）。

覆盖矩阵：synth_mixed(24,20,64 偶 2^6)、synth_odd(13,17,45 奇非 2 幂)、
synth_prime31(6,5,31 素数长)、synth_nt2(4,3,2)、synth_nt1(4,3,1)、zeros、
constant_pos/neg、impulse(8,8,32)、sine_30hz(4,4,256)、nan_inf(8,8,16)、
tiny_sgy_real(8,8,32, 真实 tiny.sgy, dt=2ms)。参数覆盖：freq dt∈{1.0,
0.002, 0.00390625}；rms 半窗 w∈{0,1,2,3,10,21,100}（w=100 > n_t 验证
symmetric 折叠）。置换 strides：synth_mixed 以 xl-major 存储 + 显式 strides
过 envelope（与 packed 结果按 expected 对照，双判据通过）；显式 packed
strides 与 {0,0,0} 约定 memcmp 逐位一致。

| 算法 | 断言子集最差实测（跨 12 case） | 冻结容差 | 判定 |
|---|---|---|---|
| envelope | max_abs **5.96e-07**（synth_mixed/tiny）；max_rel 1.60e-05 | 1e-5 / 1e-4 | 全过 |
| instantaneous_phase（circular） | max_abs **1.36e-05**（synth_odd） | 1e-4 rad | 全过 |
| instantaneous_frequency | max_abs **4.73e-04**（synth_mixed, dt=0.002）；rel 峰值出现在 |e|→0 元素（由 abs 判据覆盖，如 constant_neg 3.80e-05 abs/rel 1.0） | 5e-3 / 1e-2 | 全过 |
| rms_amplitude | max_abs **3.27e-11**（synth_mixed w21）；w0 与 |x| 逐位相等；w100/tiny 为 0 | 1e-6 / 1e-5 | 全过 |

非有限掩码（逐元素必须一致）：nan_inf envelope NaN 80/80、freq 80/80、
rms NaN 63/63，三组 mask_mismatch 全 0（rms 的 63 = NaN 块 4 trace×15 尾部
+ Inf trace 离窗后 3，与 oracle 滑窗拓扑逐点一致）。

幅度不确定子集（契约 §4，报告不豁免）：impulse phase unc=1997/2048
（max dev 2.98 rad，精确零解析样本 + 全零 trace，断言子集 1.31e-06）；
impulse freq unc=2045/2048（max dev 250 Hz=1/(2dt)，断言子集 3.82e-05）；
zeros phase/freq unc=200 但 max dev 0.00（两侧同为 0；另有独立不变量测试
断言零输入四算法全零）。其余 10 个 case 的 phase/freq 断言子集 = 全样本。

独立不变量（不经 oracle 期望值）：sine_30hz env 偏差 6.96e-06、freq 偏差
1.91e-04 Hz；常数 env=|c|（<1e-6）、phase=0/π（circular）、freq 逐元素
**精确 0**（double 路径）、rms=|c|；zeros 四算法全零；rms w0 ≡ |x| 逐位
相等（synth_mixed 与 tiny_sgy）。

## 5. 执行语义与集成冒烟（seismic_attributes.runtime，6 项全过）

- 预置取消：run 前 request_stop → `TaskCancelled`，stage 非空。
- 计算中取消（同步屏障，无计时竞态）：(200,200,64)=40000 trace、批 512，
  首个 progress 回调内 request_stop → 第二批边界取消，stage
  `traces 512/40000`，实测 1 次回调后取消。
- progress：(120,120,32) 30 次报告，first=0.0356，单调递增至 1.0，末条
  stage="done"。
- 输入不变性：FNV-1a 哈希运行前后一致；确定性：两次运行 30720 元素
  **逐字节相同**（memcmp）。
- 输出生命周期：仅保留 ProducedVolume 的 VolumeView（含 lifetime），销毁
  AlgorithmResultV1 后 2048 元素仍可读。
- 真实 TaskRuntime（基线 `53e22b67` 版 `libs/workflow`）冒烟：四算法各
  submit 一次（publisher 收集），全部 `succeeded`，各恰好发布 1 次
  success、1 个输出体（5760 元素），provenance 完整，单位 ''
  /'rad'/'Hz'/''。**publisher 为模块测试替身：未证明 B 线入库**；端到端
  由 A 线负责。

## 6. 注册契约（seismic_attributes.registration，5 项全过）

显式注册 4 id（`seismic.envelope` / `seismic.instantaneous_phase` /
`seismic.instantaneous_frequency` / `seismic.rms_amplitude`，单 dot —— 基线
registry 校验拒绝双 dot，见 v3-contracts §1 修正记录）；重复注册明确拒绝
（rejection 含 "duplicate"，registry 状态不变仍 4 条）；与 C3 共存：先注册
`seismic.coherence_c3` 再注册四属性无冲突，C3 小规模运行正常（输出
 coherence∈[0,1]、provenance id/build 正确）；descriptor 契约（端口/单位/
 参数/默认值/范围）逐项断言；请求级拒绝码逐项断言：
`request.input_volumes.count`、`request.algorithm_version.mismatch`、
`param.sample_interval.not_positive`（=0）、`param.sample_interval.out_of_range`
（<0，注册层）、`param.window.out_of_range`（<0 与 >1048576）、
`param.window.invalid_json`、`input.sample_count.too_small`（freq n_t=1）、
`request.input_volumes.invalid`（零维）。注册测试仅链接公共头（生产消费
程序证据）。

## 7. 性能与内存（seismic_attributes.perf；声明：不与 Python 比速）

固定规模（Release、单线程 FFT、无计划缓存；VmHWM 取 /proc/self/status）：

| 算法 | 规模 | 墙钟 | provenance | 峰值 RSS 增长（允许上限） |
|---|---|---|---|---|
| envelope | 48×48×512 (1.18M) | 21.6 ms | 21 ms | 8.6 MiB（105） |
| instantaneous_phase | 48×48×512 | 29.6 ms | 29 ms | 0.6 MiB |
| instantaneous_frequency | 48×48×512 | 38.9 ms | 38 ms | 0.0 MiB |
| rms_amplitude (w=21) | 48×48×512 | 5.9 ms | 5 ms | 0.0 MiB |
| envelope | 96×96×512 (4.72M) | 77.5 ms | 77 ms | 18.0 MiB（132） |

批处理：批 = min(64MiB/(16·n_t), 512) 条 trace；上表 RSS 增长 ≈ 输入+输出
载荷 + 单批 FFT 缓冲，96×96 规模（trace 数 ×4）不出现随 trace 数增长的无界
缓存（断言上限 = 2×载荷 + 64MiB + 32MiB，全部远低于上限）。

## 8. 未覆盖 / 限制

- sweetnes/dip/curvature、SEG-Y/Zarr backend、GUI、跨域转换：本轮范围外。
- 本机为 Linux 验证环境；A 线 Windows/MSVC 构建与 Qt ABI manifest 由 A 汇总。
  pocketfft 为纯标准 C++ 头，无平台分支风险，但 MSVC 编译仍需 A 实测。
- freq 的幅度不确定子集协议依赖 oracle 包络做幅度参考（fixture 自带，
  运行时不需要）；生产使用中相位/频率在近零振幅处本身无意义，不构成
  功能限制，但消费方（D 线显示）应知晓。
- TaskRuntime 为基线版语义；C 线 v3（先发布后终态）修复 `86d8b38c` 合入后
  发布语义更强，本线测试在两种语义下均成立（只断言 succeeded + 恰好一次
  publish_success）。
- B 线入库未证明；D 线展示未做（A 汇总时接入）。
