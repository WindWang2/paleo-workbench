# E 线台账 v3（codex/cpp-v2-seismic-attributes）

> 目标（Prompt E）：四个地震属性（envelope / instantaneous_phase /
> instantaneous_frequency / rms_amplitude）真实 C++ kernel，与固定 Python
> oracle 对照，交付可注册、可发布结果的 `Pwb::SeismicAttributes` 模块。
> 上限 15 轮；实际 6 轮完成。

| 轮 | 改动 | 验证结果 | 判定 | 下一步 |
|---|---|---|---|---|
| E1 | 环境/事实核查：Linux 验证机上定位 bare+worktrees 布局（A/B/C/D 已就位）；基线 `53e22b67` 确认；建 E worktree + 分支；geo-viz-engine 按 gitlink `08851951` 初始化（干净）；读 CLAUDE/设计文档/账本 R14-R16/C 线 v3-contracts（7 冻结头 blob SHA）；实测 oracle 语义（hilbert 谱权重/float32 链、unwrap NaN cumsum 扩散、gradient 边界、uniform_filter1d=symmetric、NaN/Inf 传播、常数/零值）；FFT 选型 pocketfft cpp@c90e55b3（BSD-3，仓内无 FFT、系统 FFTW 为 GPL 弃用） | 语义全部实测非猜测；内存 52 GiB 可用 | 通过 | 冻结契约 |
| E2 | 契约先行提交 `7c6a75da`：公共头 `attributes.hpp` + `v3-contracts.md`（语义矩阵/容差/单位/支持范围）+ vendored pocketfft（SHA256 记录） | 提交 SHA 公布 | 通过 | 生成 fixtures |
| E3 | fixture 生成器（固定解释器 py3.13/numpy2.4.6/scipy1.17.1）：12 case × 4 属性；解析不变量 self-check（整周期余弦/常数/零/_provider 轴等价）——自检抓到常数负值 float32 相位链 ~2e-5 Hz 尾噪声，放宽不变量至 1e-3 并注明；fixtures 提交 `7a4ca481`（含 manifest：gitlink/版本/shape/params/hash/统计） | 生成器 exit 0；统计抽查符合解析预期（sine env≡0.8、NaN 恰在 5 条污染 trace） | 通过 | 实现 |
| E4 | 实现 `libs/seismic_attributes`：四 kernel（pocketfft 双精度 Hilbert 整 trace、scipy 同构 unwrap/gradient、RMS symmetric 折叠 padded 滑窗和）、显式注册、批处理/取消/progress、CMake standalone+可 add_subdirectory；4 个测试（kernels/registration/runtime/perf）+ gate.sh（flock 等价资源门禁） | 门禁内 configure/build exit 0；ctest 首轮 2 失败：①registry 拒绝双 dot id（其校验只收单 dot）②kernels 3 项失败 | 部分通过 | 修 |
| E5 | 修正：id 改单 dot `seismic.<name>`（契约加修正记录）；诊断 impulse 失败根因——解析信号精确零样本相位为纯舍入噪声（exact 计算证明）、unwrap 链 2π 偏移在 gradient 浮现 250Hz——按契约 §4 幅度不确定子集协议（oracle 包络 ≤1e-6·trace max 为不确定，报告不豁免；freq 加 ±1 邻域）；诊断 RMS 差异根因——scipy 滑窗和 `(s-old)+new` 的 NaN 永久尾部/Inf 离窗 NaN 尾部（5000 长实测无重置）——RMS 重写为同构滑窗和 | ctest 4/4 exit 0；52/52 parity 零失败零跳过；实测误差见 v3-verification §4；nan_inf 掩码 63/63 全对齐 | 通过 | 提交+文档 |
| E6 | 实现提交 `0e6aeed2`；最终确定性链路复验 4/4；Qt/Python/QGIS 链接检查（ldd/nm 0 命中）；perf/内存实测记录（envelope 1.18M 样本 21.6ms、96×96 无无界缓存）；写 v3-verification/handoff/ledger | 全绿；无门禁拒绝（全程 52 GiB 可用） | **完成（模块级）** | 交 A 注册/汇总 |

## 遗留

- A 线 Windows/MSVC 构建实测（pocketfft 无平台分支，仍需实证）。
- C 线 TaskRuntime v3 修复（`86d8b38c`）合入后的端到端发布验证（A）。
- B 入库、D 展示由各自线条交付后由 A 汇总。
- sweetness 等其余属性本轮明确不做（可组合复刻，见 handoff §4）。
