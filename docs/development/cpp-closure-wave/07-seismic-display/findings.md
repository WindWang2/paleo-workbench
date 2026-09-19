# 07 — findings

## 平台与预算（2026-09-20）

- ZCode 技能清单无 /goal、/goal-loop（仅 browser-use、document-skills、skill-creator、zcode-guide 系列）。
  采用四文件持久化循环，不安装未知插件、不伪造命令成功。
- 平台无 token 配额查询接口；预算 3.6 亿为上限请求。开工时已消耗：盘点 Explore 子代理 ~3.97M
  （root 直接 subagent 1/3）。
- 无 cmake/ninja 于系统 PATH；SDK 只读复用 `/home/kevin/pwb-sdks/root/usr/bin/{cmake,ninja,ctest}`
  （cmake 4.4.3 / ninja 1.13.2），需 `LD_LIBRARY_PATH=/home/kevin/pwb-sdks/root/usr/lib`（cmake 依赖
  自带 librhash.so.1）。与 06 线 CMakeCache 记录一致（CMAKE_COMMAND 同路径）。
- Python oracle 环境：系统 python3.14 无 numpy/scipy，无 pip/uv/conda，文档钉死的
  /opt/miniconda3/bin/python3.13 本机不存在 → 无法本机重跑冻结 Python 生成新 oracle。
  采用证据链替代（详见下"oracle 策略"）。

## 代码事实（origin/main=06211541）

- SeismicSliceWidget API 面：set_volume(identity,revision)/display_mode/polarity/clip/gain/picks/
  save_picks/load_picks/set_view_transform/slice_image()/plane_point_at（seismic_slice_widget.hpp）。
  ViewerState 含 degenerate/failed；SliceController 幂等 shutdown、epoch 代际。
- display_core.percentile_clip_range：numpy 'linear' nanpercentile parity，float32 输入 dtype 插值，
  fixture 已提交且 contracts 套件验证（display_core.cpp:10-31）——fuse_rgb 的归一化原语可直接复用。
- viz_d_seismic_binding：工厂捕获 shared_ptr<ISeismicVolume>，null→"no seismic volume available"。
- SeismicPredictionPage（libs/ui_wellseis）：view_panel_ = new SeismicViewPanel(splitter_)（:61），
  从不调 view_panel_->set_hooks → SeismicViewHooks 全空（show_resource 为 no-op）→ 面板永远空占位。
  页面暴露 view_panel() 访问器（"Panel access for the host's engine wiring + tests"）——
  绑定可在 app 层完成，无需改 ui_wellseis 源。
- ResourceSlice{id,name,path,type,format}（ui_workers/worker_common.hpp:177）。
- SeismicVolumeService::open_segy/open_pwbvol → OpenedVolume{volume,descriptor,cache}（volume_service.hpp:69-90）。
- ExternalPresenter{kind,supports,create,note} + register_external_presenter（viz_e_install.hpp:66-77，
  first-registration-wins）；04 线协调文件声明其 closure_preview_install 注册 kind="seismic"
  （D→E make_seismic_preview_presenter）。07 不注册，避免抢写。
- main_window.cpp 地震菜单已有 BEGIN/END VIZ-D 具名块调用 add_seismic_horizon_menu_actions（:729-741）
  ——导出/视图态菜单可在同块内追加调用，属最小具名块租约。
- 属性面板词汇（ui_wellseis/seismic_attributes.hpp）：seismic_attribute_panel_groups() 含"未实现"组；
  kernel_for_label(label)→kernel id（""=不可计算叶）。可计算集由 host computable_probe 注入。
- science IAlgorithm::run(AlgorithmRequestV1{params_json, input_volumes}, progress, stop_token)
  → Result<AlgorithmResultV1{outputs[ProducedVolume{volume,unit}]}>（algorithm.hpp:15-32, types.hpp:95-150）。

## Python 冻结源语义（geo-viz-engine@08851951，主仓检出同 pin，只读参照）

- fuse_rgb(attr_r,g,b,clip_pct=99.0)（attributes.py:223-260）：每通道独立
  lo=nanpercentile(a,100-pct), hi=nanpercentile(a,pct)；hi<=lo→回退 nanmin/nanmax；仍 hi<=lo→全零；
  否则 clip((a-lo)/(hi-lo),0,1)；uint8 = 归一化*255 截断；堆叠 (H,W,3)。
- blend_rgba：min-max 逐通道 + 常数 alpha 0.85——面向 pyqtgraph.opengl 3D 顶点色，**不在 2D 显示范围**。
- _export_slice（seismic_view.py:1880-1907）：png=对应剖面 widget.grab()（真实显示渲染）；
  npy=np.save(原始数组)；csv=np.savetxt(delimiter=",", fmt="%.6f") 无表头。
- get_project_state（seismic_view.py:372-386）：file_path、slice_positions{inline,crossline,time}、
  colormap、render_mode；apply_project_view_state 读回。拾取导出 CSV 表头 inline,crossline,time_ms %.1f
  （:2336-2338，与 horizon::to_csv parity 已存在）。

## oracle 策略（诚实记录）

无法本机运行冻结 Python（无 numpy 解释器）。证据链：
1. fuse_rgb 语义逐行对照冻结源 attributes.py:223-260（上方摘录）；
2. 归一化原语复用已验 oracle parity 的 display_core.percentile_clip_range（numpy linear nanpercentile，
   seismic_attributes fixtures 已提交并由 contracts 套件验证）；
3. 新测试含解析手算用例（常量面、全 NaN、已知分布的精确 uint8 值）+ 篡改/负面 self-check
   （篡改期望值必须使测试失败）；
4. numpy .npy 格式按 v1.0 规范（\x93NUMPY\x01\x00 + 64B 对齐头部）与 np.save 逐字节契约实现，
   测试用独立 C++ npy 头解析器回读校验（非"自己写自己读"的同函数循环）。

## LOD/GPU/Zarr 不迁裁决复查（r6a-audit.md:10-17,37-43 原文核对）

- LOD（lod.py 189 行，裁决不迁）：视口抽稀已由 display_core.viewport_decimation 承担（每像素至多
  一个绘制样本）；LOD 金字塔是大体性能优化而非用户能力。生产读路径=SliceController 平面缓存+
  ±1/±2 预取+tiled_volume 有界 CPU tile。**用户能力无损，维持不迁。**
- GPU 路径（明确不迁）：C++ 无 GL 引擎（raster Qt）；gpu_ops 仅 CPU parity
  （sample_polyline_slice 已在 display_core）。**渲染能力由 VD/wiggle raster 承担，无损，维持。**
- Zarr 后端（PWBVOL1 架构性替代）：seismic_service open_pwbvol 为替代路径。**无损，维持。**

## 接口/所有权协调

- 04 线（task-04-data-preview.json）：owned viz_e_install + closure_preview_*；
  "presenter_registry: closure install registers kind=seismic (D→E make_seismic_preview_presenter)"
  → 07 不调用 register_external_presenter，仅保证 presenter 真实、可注册、smoke 绿。
- 12 线：app_shell.cpp seismic_page_ 构造块（app_shell.cpp:178-186）具名块租约
  BEGIN/END CLOSURE-SEISMIC；不触碰其他块。
- 06 线：libs/ui_wellseis geological_modeling_3d_page.cpp 归 06，不碰。
- viz_e registry / preview_dispatch 词表：不修改（04/E 所有）。

## R1-R3 实现期发现并修复的缺陷（自查）

1. npy 头部填充差一（slice_export.cpp）：prefix=10+header 需 ≡0 mod 64，
   初版 append(padded-total-1) 少一空格 → 独立 npy 解码测试可捕获（证明测试有效）。
   已修：append(padded-total)。
2. 测试 SEG-Y 写器迹头偏移：读核 segy_layout.cpp 用 0-based kInlineOffset=188/
   kCrosslineOffset=192（头注释的 189/193 是 SEG-Y 规范 1-based 口径）——
   测试写器初版按 1-based 写导致网格发现错位。已修为 188/192。
3. 根 CMake UI-14 imply 链（CMakeLists.txt:489）置 CONV_06/07/08=ON 但未同时置
   CONV_07 验证所需的 PWB_BUILD_MAPPING_KERNEL/CONV_06 → 任何 PLATFORM+DATA 配置
   在 :564 FATAL（现主线缺陷，12 线所有）。07 未改根 CMake，用 -D 显式补参绕开，
   已在 progress.md 记录，建议 12/13 复验修复。
4. gate 脚本 invoke-resource-gate.sh 的 -a 参数契约是"逐个完整 cmake 参数"，
   每项需自带 -D 前缀（-a '-DX=ON;-DY=2'），裸 KEY=VALUE 会被 cmake 当未知 token
   静默吞掉。已写入本 findings 供其他线参考。
5. tests/cpp/viz_d 在 root CMake :829 早于 libs/ui_wellseis（:867）→
   `if(TARGET Pwb::UiWellseisQt)` 在该时点恒假。viz_d.closure 门改用
   PWB_BUILD_PLATFORM + 已定义 lib 的 TARGET 检查，UiWellseisQt 走前向引用
   （generate 期解析）。

## 已知限制（诚实记录）

- 属性核计算在 GUI 线程同步执行（单剖面 <100ms 量级）；SliceController 式
  worker 化留待后续（v5-product-delta 的异步属性管线属面板级扩展）。
- RGB 融合通道序固定为"最近三个已计算属性平面 R/G/B"，无通道选择 UI
  （Python 引擎有 combo；面板词汇表未含，需后续与 04/12 协调 UI 词汇）。
- depth 域（m/ft）数据体拒绝瞬时频率（时间轴语义），其余 E 线核可算。
- 结构核（sweetness/dip/曲率/相干）需 3D 邻域，2D 剖面诚实拒绝，不伪造结果。

## 独立审查结论（general-purpose 子代理，2026-09-20）

- P0：无。核心数值（fuse_rgb parity、npy v1.0、JSON fail-closed）、钉扎生命周期、
  测试独立性（独立 npy 解码器、pattern 公式核对）判定良好。
- P1 修复：通道配准校验（volume_id+axis+index+revision 全等，换体清空历史）、
  属性钉扎下 npy/csv 拒绝导出（PNG 仍导真实显示）、viz_d.closure 门条件改
  PLATFORM+DATA（UI imply 触发条件）。
- P2 已修：size_t 乘积、csv nan 无符号（numpy parity）、内嵌 picks 体绑定校验
  （跨体 picks 拒绝整个状态）、换资源回放 display_mode、注释对齐。
- P2 遗留（不阻断，如实记录）：
  1. wiggle 模式下钉扎属性图不可见但 attribute_active 仍真（切回 VD 恢复；
     overlay 标签仍在）——行为记录于本条，未加额外 UI。
  2. load_view_state 两处 setter 契约性 no-op（map 视图存 wiggle、min>=max 显式
     范围）——保存路径不可能产生这两种组合（widget 自身约束），仅手造文件可触。
  3. 属性失败诊断经 last_diagnostic() 供宿主读取，canvas overlay 不显示；
     当前两个宿主均消费该通道。
  4. 融合 oracle 为手算解析值+截断点断言（无 committed numpy fixture——本机无
     numpy 解释器，见"oracle 策略"）。
  5. 导出/视图态菜单仅接 viz-d dock（hub-2 页面 viewer 走 widget API）——
     菜单可达性不对称，记录为限制。
- 审查亦确认：viz_d_seismic_install.hpp 顶部 "No preview/data-page assembly"
  注释与 04 线合同一致（注册归 04）。
