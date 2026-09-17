# E 线交接 v3（codex/cpp-v2-seismic-attributes）

> 交付分支：`codex/cpp-v2-seismic-attributes` @ `0e6aeed29529005a5fdba609b37a58e227b761d8`
> （基线 `53e22b679ea3181d4e2c2bca8d42ca272c00dfbf`；契约先行 `7c6a75da`、
> fixtures `7a4ca481`）。状态：模块级完成并验证（见 v3-verification.md）；
> 未合入其他分支，不自动 merge/push。

## 1. 给 A 线（平台与最终集成）

1. **接入根构建**：`add_subdirectory(libs/seismic_attributes)`。target
   `Pwb::SeismicAttributes`（STATIC，cxx_std_20，无 Qt/QGIS/Python 依赖）；
   已存在 `Pwb::Science` 时自动复用，不重复引入 `libs/algorithms`。根构建不
   想跑 E 线测试时置 `-DPWB_SEISMIC_ATTRIBUTES_BUILD_TESTS=OFF`（默认 ON，
   fail-closed：缺 fixture/依赖即 configure FATAL_ERROR，不静默跳过）。
2. **注册调用**（产品进程启动时一次）：

   ```cpp
   #include <pwb/seismic_attributes/attributes.hpp>
   pwb::seismic_attributes::RegistrationReport report =
       pwb::seismic_attributes::register_seismic_attributes(registry,
                                                            build_identity_sha);
   // report.registered_ids.size() == 4 且 report.rejection.empty() 表示成功；
   // 重复 id（例如与 C3 或二次调用）会得到 rejection 并跳过后续条目。
   ```

   算法 id：`seismic.envelope` / `seismic.instantaneous_phase` /
   `seismic.instantaneous_frequency` / `seismic.rms_amplitude`（单 dot——
   基线 registry 校验只接受单 dot，契约初稿的双 dot 已修正，见
   v3-contracts §1）。与 `seismic.coherence_c3` 无冲突（测试覆盖共存）。
3. **build_identity**：传主程序构建 SHA；进入 descriptor 与每条 provenance。
4. **参数/单位**：freq 的 `sample_interval` 是**秒**（provider 语义：
   `seismic_view.py:1835` 已把 ms ÷1000），输出 Hz；宿主若持有 ms 需自行换
   算。rms 的 `window` 是**半窗**（总窗 2w+1，默认 21→43）。
5. **取消/progress**：supports_cancel=true；批间检查 stop_token（批大小
   min(64MiB/(16·n_t), 512) 条 trace）；progress 单调、成功终值 1.0；取消
   返回 cancelled 不返回半成品。publisher 语义遵循 C 线契约（每 request
   恰好一次 publish_*）。
6. **B 入库**：四算法每个恰好 1 个 `ProducedVolume`（name/port 名见
   descriptor，unit ''/'rad'/'Hz'/''），provenance 完整，可按 B 的通用单产
   物协议消费。E 线测试中的 publisher 是收集替身——**B 线真实入库未被证明**，
   端到端发布由 A 验证。
7. **C 线 v3 TaskRuntime**：本线在基线版 `libs/workflow`（53e22b67）上冒烟
   通过；C 线已交付先发布后终态修复（`86d8b38c`，契约 `03ff8155`）。A 汇总
   合入 C 的分支后语义更强（publishing 阶段、`TaskSnapshot::published`），
   本线算法无需改动（不感知 runtime 内部状态机）。
8. **FFT 依赖**：vendored `libs/seismic_attributes/src/detail/pocketfft_
   hdronly.h`（mreineck/pocketfft cpp@c90e55b3，BSD-3，SHA256 见
   verification §1；单线程、无计划缓存编译宏在 attributes.cpp 顶部）。无
   网络拉取、无共享依赖清单变更。MSVC 侧无需特殊配置（纯标准 C++ 头），
   但请随 A 的 Windows 构建实测一次。

## 2. 给 D 线（地震二维 viewer）

- 输出 `VolumeView`：shape 与输入相同，packed C-order `(inline, crossline,
  sample)`，元素 strides `{n_xl·n_t, n_t, 1}`，数据 owned float32，
  `lifetime` shared_ptr 随 ProducedVolume 交付——直接按 C 线冻结头消费即可。
- 显示注意：phase∈[-π,π] rad（建议色彩映射按 circular）；freq 单位 Hz、可为
  负（unwrap 链），近零振幅处 phase/freq 无物理意义（契约 §4 幅度不确定子集
  的动机）；NaN 语义与 Python 版一致（hilbert 族整 trace 污染、RMS 滑窗
  尾部污染）。

## 3. 给 B 线（数据持久化）

无直接接口变更。如需把属性体入库： ProducedVolume.name 即端口名，unit 已
带；params_json 与 input_refs 完整进入 ProvenanceRecord（含 RMS 半窗与
freq 采样间隔），`wall_time_ms` 有值。

## 4. 已知边界与后续

- 本轮范围外：sweetness/dip/curvature、SEG-Y/Zarr 读取、通用调度、GUI。
  sweetnes 在 Python 侧 = envelope/sqrt(freq)（低频钳制 1e-6），可直接以
  两产物组合复刻，若需要建议另立任务。
- freq 在 n_t<2 显式拒绝（`input.sample_count.too_small`）；空/零维输入由
  registry `request.input_volumes.*` 拒绝——均为冻结契约。
- 数值契约与容差冻结于 v3-contracts §4；修改算法数值行为必须升 version。
- 本线未改任何 C 线/D 线/B 线文件、未动旧 Python 生产实现与子模块 gitlink
  （geo-viz-engine 在本 worktree 按 gitlink 08851951 初始化，仅只读引用）。
