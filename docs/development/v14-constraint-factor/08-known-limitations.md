# V14-CONSTRAINT-FACTOR — 08 已知限制

1. **地理 CRS 的 barrier buffer 换算未移植**：`constrained_idw_adapter` 的 `barrier_buffer_distance_for_crs`（300 m → 度）未移植；地理 CRS（EPSG:4326 类）+ break 线的约束 IDW 任务会以原始地图单位运行 barrier buffer，与 Python 产品存在偏差。本地 `factor_service` 的科学路径同样未移植该换算（science_service 侧已登记同一差量）。后续：`geod_for_crs` 椭球面换算落地后补。
2. **样条 / 方向趋势无原生核**：geoviz SciPy griddata 与 directional 引擎未移植；这两个 UI 方法在 prepare 中 per-task 诚实失败（"未原生接入"），不伪成功。后续：按 CONV 序列移植 cubic/directional 引擎。
3. **Kriging 为 numpy-OLS 估计器**：mapping_kernel `interpolate_factor` 的普通克里金（经验变差 + 球状/指数/高斯 + ridge 回退）与 geoviz WLS 估计器是不同估计器；网格轴 padding 为 10%/0.01（geoviz 为 5%）。以 mapping_kernel oracle 为单一权威（既有 CONV-28 决策）。
4. **constrained 的 contour 后处理未移植**：masked marching squares / 环闭合 / 穿越修复 / barrier 修剪属 haiyou 引擎的 extract_contours 腿；grid 本身 bit-identical（oracle 对）。等值线经 `viz_charts` marching squares 常规提取。
5. **NPZ 容器未移植**：Python 的 `.factor_grid.npz` artifact 容器未移植；C++ 侧网格持久化走 catalog INTERMEDIATE 版本 payload（`to_legacy_dict` JSON）+ live cache。旧工程 parameters 内联 grid 可读（legacy 腿），保存时按现状保留内联。
6. **`set_run_ports` / `versions_for_domain_tasks` C++ API 缺**：Python catalog lifecycle 的两个 seam 未移植；factor_map run 以 input_version_ids=[] + parameters.pins/hash 表达输入（Python register_factor_map_run 同型）。
7. **PersistentRuntimeCatalog 与 closure_workflow::FileCatalogRepository 同契约双实现**：平台配置不含 `PWB_BUILD_CPP_CLOSE_02`，故 rails 实现于 app 层。二者写同一 `<root>.json` 契约（store_version:1），02 线进入平台配置后可单一化（替换为 closure_workflow 实现，无数据迁移）。
8. **factor_map_tasks 重复 id**：调度器与 commit 按 id 键（Python 移植行为）；重复 id 时 commit 写最后出现槽、结果表折叠。未在数据面强校验（与 Python 一致）。后续可在 slice builder 加去重告警。
9. **contour payload 记忆化未做**：重开工程后每次「等值线初稿」在 GUI 线程重解析 catalog payload（100 任务 ≈0.4-1 s）；live cache 命中时 <10 ms。后续按 version_id 记忆化（版本不可变，可安全缓存）。
10. **单位语义**：`quality_metrics.unit` 未写（extract 的 FACTOR_DEFAULTS 单位表在 `extract_factors` 路径，prepare 直接消费 sample_points）；value_key 已防混维度，但单位标签缺失。
11. **attach 每任务两次 descriptor 构建**（grid_entry_from_attached 复制 task JSON 重跑 attach）：≈1 ms/任务，功能等价，性能记账见 06。
12. **macOS/Windows 未验证**：本机 linux；平台矩阵由 12 线统一执行。
13. **在线 CI 未等待**：本地验证为准（见 09）。
