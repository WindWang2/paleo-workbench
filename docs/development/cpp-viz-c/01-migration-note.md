# VIZ-C 井震联合 3D（计划 V4）迁移说明

## 范围（well_seismic_3d 剩余 → C++）

| Python 源（@08851951） | 行为 | C++ 落点 | 备注 |
|---|---|---|---|
| `models.py` | JointWellId/WellHead/TimeDepthTable/VerticalDomain/WellTrajectory3D/WellGrTrajectory/WellPierce/JointDisplaySettings/TimeSliceState/OrthogonalSliceState/MAX_TIME_SLICES | `libs/geo3d_viz/include/pwb/geo3d_viz/joint/joint_types.hpp` + `src/joint/joint_types.cpp` | np.interp → 排序二分插值；范围外 NaN（V6 §8 截断语义） |
| `depth_transform.py` | 优先链 fail-closed、ConstantVelocityDepth、#147 v0 校验 | `joint/depth_transform.{hpp,cpp}` | 保留 exact warning 文案 |
| `survey.py` | SurveySpec、survey_from_corners（含 wayfinder #84 间距符号翻转、V6 §9 拒绝零坐标） | `joint/survey.{hpp,cpp}` | BinGridGeometry 复用 `pwb::seismic_io`（数学一致，seismic_io 侧已冻结 oracle） |
| `registration.py` | VolumeRegistration、stride 精确格点映射、#147 dt fail-closed | `joint/registration.{hpp,cpp}` | |
| `well_geometry.py` | pierce/project（Time/Depth、TD 截断、head-only 警告）、offset_curve_along_trajectory、synthetic overlay | `joint/well_geometry.{hpp,cpp}` | |
| `volume_access.py` | VolumeAccess 协议 + InMemory | `joint/volume_access.{hpp,cpp}` | |
| `fence.py` | 等弧长重采样、extract_fence_strip（dense/slice 双路径）、well_to_well_path | `joint/fence.{hpp,cpp}` | 源后端走逐 inline 切片（不整卷物化） |
| `probe.py` | ProbeState.slice_indices、probe_from_fence_s | `joint/probe.{hpp,cpp}` | |
| `color_scales.py` | 冻结色标、colorize_amplitude（P98 鲁棒范围）、colorize_gr | `joint/color_scales.{hpp,cpp}` | np.rint=banker's → std::nearbyint(FE_TONEAREST)；percentile 线性法 |
| `scene.py` | WellSeismicScene 全量（survey/域/切片栈/井/TD/fence/probe/配准/提取缓存/world↔render 映射） | `joint/joint_scene.{hpp,cpp}` | render 映射即 CONV-GEO3D SceneTransform 源；联合状态版本化 JSON |
| `segy_survey.py` | corners→SurveySpec | `joint/segy_survey.{hpp,cpp}` | **映射决策**：Python 侧 text-header 启发式/轴交换是 Python loader 信息缺失的补偿；C++ `inspect_segy`（#1369）已提供权威 bin-grid（SourceGroupScalar 已按迹处理）+ counts + dt，故直接从 `VolumeDescriptor` 构造并 fail-closed（无 bin-grid / 非 TWT ms / dt≤0 一律拒绝）。`_FALLBACK_IL_SPACING_M`/`_measured_spacing_cache`/text-header 解析不迁移。`horizon_corners_from_dat` 归 horizon/井间线（不在此清单）。 |
| `time_map_2d.py` | TimeSliceMap2D 平面图（振幅+穿透点+井序连线+点击加井） | `apps/paleo_workbench_platform/viz_c_time_map.{hpp,cpp}` | Qt 移植；切片数据可由 job 预注入 |

**明确排除**（不在 V4/任务 C 清单）：`joint_widget.py` 直通 API（1134 行，R5 排除）、`profile_2d.py`（VD 剖面渲染，属 D/后续）。

## 复用与接线

- `libs/seismic_service`：`TiledVolumeAccess`（apps 侧桥）把 `ISeismicVolume`（tiled 后端、字节预算 tile cache）适配为 joint `IVolumeAccess`；单读线程纪律由 JobCenter 单 background worker 保证（open + 切片读全部走 job，GUI 只装网格）。
- CONV-GEO3D `SceneTransform` seam（scene_adapter.hpp:75-87，此前零消费者）：`VizCJointHost::install_scene_transform()` 把 scene 的 world↔render 映射装进 dock controller 的 adapter——geomodel 域对象（well:/horizon:）与联合对象共享同一渲染空间；逆向自动作用于 `resolve_pick`。
- `geo3d_dock` 扩展：`joint_host()` 组合根（JobCenter 经 dynamic property 注入）；host 实现 #1394 `pwb::ui_wellseis::qt::JointHostController` 全接口（真实 scene 驱动，非空壳）。
- 联合状态持久化：`WellSeismicScene::joint_state_to_json/restore_joint_state`（版本字段 + 逐条降级），宿主存 QSettings `viz_c/joint_state`；**workspace 七键 schema（objects/measurements/display/clip/camera/views/selected）不动**，旧数据可读。
- 体打开 job：collect(GUI 提交)→compute(worker `open_pwbvol`/`open_segy` O(1) 打开)→apply(GUI survey/access/网格组装)；generation 检查丢弃迟到/被取代结果；取消/关窗走 JobOwner 400ms 协议。

## Oracle

- 生成器 `tools/oracle/generate_viz_c_fixtures.py`：导入真实 `geoviz_well_seismic_3d`（本 worktree 子模块 @08851951；生成器显式注入项目 sys.path 以压过宿主 editable 安装）。冻结 `tests/cpp/viz_c/fixtures/viz_c_joint_oracle.json`（输入+输出+错误文案）+ tampered 变体（负面 self-check：C++ 必须检出）。
- C++ 回放 `viz_c.joint_oracle`：精确 float 相等（同机 glibc libm 下 exact；1e-12 相对回退仅吸收跨平台三角函数 ULP 噪声）+ 计数守卫（>200 次比较，防比较器静默跳过）。

## 环境/资源备注

- 资源门禁全程 `-j2`（CMAKE_BUILD_PARALLEL_LEVEL=2 / CTEST_PARALLEL_LEVEL=2 / OMP=1…）；构建树 `build/viz-c`；QGIS SDK 只读复用同级 main checkout（PwbQgisSdk.cmake 既有约定），另需 `PWB_QGIS_DEPS_PREFIX=…/native/gdal-vendored/install`（本机 gdal 头）。
- GL：本机 X :1 GLX 损坏（glxinfo 同错）；**受支持的软件 GL = Wayland + Mesa llvmpipe（OpenGL 4.6 core）**，`QT_QPA_PLATFORM=wayland` 下 geo3d.widget_test 11/11（真 GL 路径）；offscreen GL-less 诚实降级路径经 X 错误处理器后可跑。
