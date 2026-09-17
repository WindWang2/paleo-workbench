# C++ 转换整体计划（main，评审后续）

基线：`e732678d` 合并 + P1 修复 + 工程会话（ledger 13/14 轮），integrated 45/45 ×2。
目标口径：**以用户流程验收**衡量"整体完成"——C++ 工作台能覆盖 Python 产品的
核心编图/数据/计算/显示回路，并可作为默认入口；不以文件数/行数/测试占比折算。

## 阶段与验收门（每阶段独立提交，全量 ctest 绿 ×2 后才算过门）

### M1 — D/E 主程序装配（评审第 3 步收口）
- 启动时 host 侧显式注册 E 四算法（无静态自注册）。
- `AlgorithmRunner`（application 层）：真 TaskRuntime + 真 CatalogResultPublisher；
  输入 = catalog 中 PWBVOL1 版本（读回 payload + 几何），发布 = 真 B run/publish。
- MainWindow：菜单"地震属性…"调起；结果版本可一键送入地震视图。
- 地震视图 dock：`SeismicSliceWidget` 嵌入；`打开体版本(version_id)` 从 catalog
  读 PWBVOL1 → `make_owning_volume` → 切片显示。
- 验收：新平台级 E2E——打开工程 → 选 PWBVOL1 输入 → 跑 rms/envelope →
  run complete + 新版本落库 → viewer 显示该版本切片（非空、状态 ok）。
  既有 45 项回归不降级。

### M2 — 工程生命周期补全
- 新建工程：minimal 模板 JSON + 空 catalog（ensure_schema）+ 初始地震/矢量资产，
  随后 openProject 直接可编辑提交。
- GPKG 绑定图层物化（与 GeoJSON 同路径，staged 导出仍为 GeoJSON）。
- 验收：`platform.project_session` 扩展——newProject → 打开 → 编辑 → 保存 →
  重开全链；GPKG 载荷路径同断言。

### M3 — 真实地震数据进口（SEG-Y）
- `libs/seismic_io`（Qt-free）：最小 SEG-Y 读取器（IEEE/IBM float、TEXT/BIN/trace
  头、iline/xline 排序 → C-order volume + 几何）。
- 菜单"导入 SEG-Y…"：读入 → 作为属性输入源（可发布为 Raw 版本入库）。
- 验收：以 `tests/fixtures/realdata/tiny.sgy` 为 oracle——C++ 读取结果与
  `seismic_attributes` 冻结的 `tiny_sgy_real/input.f32` 逐样本一致；导入后
  可直接跑属性并在 viewer 显示。

### M4 — B 线高级目录功能（按需排队，非切换阻塞项）
- 数据 GC/dedup、staging leases、models/model_versions、entity view/分页、
  Unicode 检索归一化、通用多产物事务、catalog.json checkpoint。
- 验收：随 B 线契约逐项补 oracle 对账测试；不与 M1-M3 混提。

### M5 — 产品切换准备
- 入口切换评审：pyproject 入口 vs C++ launcher；切换前必须完成——
  Windows 全链回归（**本机无环境，需外部执行，如实标注**）、
  五线统一 CI 门禁脚本化、安装包/部署树自检。
- 默认产品是否切换 = 产品决策，本计划只交付"可切换状态"。

## 明确不在本计划内（如实）
- 井间/三维渲染、多视图联动、更多属性与完整工作流编排（后续版本）。
- Python 侧功能冻结——转换期内 Python 产品继续可用。

## 全面转换阶梯（M6-M12，目标：替换全部 Python 产品）

> 剩余 Python ~25.4 万行（产品码）+ 21.3 万行测试。方法论沿用 M1-M3：
> 纯算法核先行 + 冻结 Python oracle 对账 + 逐片接线。

- **M6 编图计算管线**（mapping/geological_pipeline 3.0k 行起步）：
  contouring（✅ 首片已落地：`libs/mapping_kernel`，
  168 冻结案例全过）→ interpolator（IDW 等，1.0k）→ polygonization
  （616 行，需 polygon 环模型）→ pipeline.py 编排（594 行）→
  factor_layer_products/well_prediction_surface。
- **M7 工作流引擎核**（workflow/ 2.8 万行中引擎部分：定义/执行器/
  crs_policy/factor_grid_result）。
- **M8 viz 其余**（井相关：DTW 对比、地层相关、地质体；2 万行分期）。
- **M9 prediction/interchange/resources/providers**（~1.5 万行，
  纯服务层居多）。
- **M10 UI 层**（9.5 万行，最大块）：先做"原生 QGIS 组件可承接面板"
  分层清单，再按面板簇分期移植；MainWindow 逐轮长出面板。
- **M11 测试体系去 Python 化**：oracle 逐模块转 C++ 基准后退役钉死
  的 Python oracle（geoviz、readback 等）。
- **M12 默认入口切换 + Python 产品退役**：M5 评审三阻塞清零 +
  M6-M10 完成 → 切换 → Python 侧转维护模式。

## 进度记录
- 2026-09-17：计划建立；M1 开工。
- 2026-09-17（同日）：**M1 完成**——`AlgorithmRunner` + E 四内核注册 + D 切片
  dock + 计算属性对话框；`platform.attribute_ui`（真 MainWindow：种子体→
  rms→入库 complete→viewer ok）。
- 2026-09-17（同日）：**M2 完成**——`newProject`（B 文档工厂+空 catalog+
  bootstrap 资产）+ GPKG 物化 + 单资产自动定向；流程暴露并修复 B 三个缺陷
  （create_new 空值不回读 / 新库 sync_state 不种 / 首绑 rebind 空转）。
- 2026-09-17（同日）：**M3 完成**——`libs/seismic_io` SEG-Y 读取器（IEEE/IBM、
  头驱动排序、严格规则网格）；`importSegy` 入库 Raw 体版本；端到端对冻结
  oracle 对账（读取器 vs geoviz 逐样本；导入体上跑 rms vs expected_rms_w21）。
  套件 47/47 ×2（integrated 树，含 D/E/seismic_io）。
- 2026-09-17（同日）：**M5a/M5b + M4 首片**——`run-integrated-gate.sh`
  一键门禁（configure+build+ctest×2+MALLOC 审计）；地震菜单“打开体版本…”
  （D 的浏览入口补全）；`name_search` 写入路径 ASCII 折叠对齐 Python
  NFKC+casefold 契约（有界实现，非 ASCII 边界在源码注释与测试中声明）。
  门禁脚本全绿（47/47 ×2 + 14/14）。
- 2026-09-17（同日）：**M4 第二片**——lineage/staging_leases 读模型入
  `CatalogDocument`（oracle_compare 从“只报告”升为真比较，typical fixture
  3+1 行对账通过）；`CatalogRepository::export_manifest` 落 Python ADR 0056
  的 catalog.json checkpoint 契约（全表 schema 1、原子写、.bak 轮换、
  models/model_versions 原样透传不丢行），接线到 PwbDataStore::commit 与
  bootstrap/import 之后；新测试 `data.manifest_export`。门禁 48/48 ×2。
- 2026-09-17（同日）：**M5 收口**——`--self-check` 扩展覆盖 M1-M3 全链
  （新工程→编辑保存→manifest checkpoint→SEG-Y 导入→rms→切片显示；部署树
  无 fixture 时如实跳过）；入口切换评审文档
  `cpp-entry-switch-review.md`（结论：建议并行启动器增量曝光，Windows
  回归+打包+soak 清零后再评默认切换）。门禁 48/48 ×2。
- 2026-09-17：**目标升级为全面转换**，阶梯 M6-M12 入计划（见上）。
  **M6 首片完成**：`libs/mapping_kernel` 忠实移植 contouring.py 数值核
  （marching squares 16 例+鞍点、段缝合精确复刻 Python dict 插入序遍历、
  RDP/Chaikin、nice/quantile 层级阶梯含 np.nanpercentile linear 语义与
  银行家舍入）；oracle 生成器
  `tools/oracle/generate_contour_fixtures.py` 冻结 5 网格 ×168 案例
  （含 NaN 空洞/鞍点场/噪声场），C++ 对账全过（坐标 <1e-9）。
- 待办：M6 其余（interpolator→polygonization→pipeline 编排）、M7-M12
  按阶梯推进。
