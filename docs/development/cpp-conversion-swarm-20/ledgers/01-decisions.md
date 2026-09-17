# 01 decisions — mapping_kernel → MainWindow 地质因子图切片

每个非显然选择与其理由。对照 prompt §8.3。

1. **不新增 tool_policy 动作 id；「地质因子图…」复用既有 `factor_workbench`。**
   kToolGroups 的 `factor` 组已含 `factor_workbench`/`factor_overlay`，
   `rule_factor`（project_gate + constraint_factor 白名单）语义正好是
   「无工程不可用」。追加新 id 会复制同一门禁且偏离「最小改动」。libs/ui
   无需任何改（ToolActionSet 从 evaluate_all 物化）。§7.5 的「新行」=
   新测试中显式断言 `evaluate_tool("factor_workbench", project_open=false)`
   → disabled + "未打开工程"。

2. **「地质因子图…」按 governed QAction 接线**（wire 表设中文文本 +
   connectActions 连 handler），与 reference_import/save_edits 同模式，
   而不是像「新建工程…」那样的裸菜单动作：policy 是启停唯一权威（V8
   契约），且 actionWiring 审计免费覆盖。

3. **runner 放 `libs/application` 且 Qt-free**（输入 Json 井点记录，输出
   Json GeoJSON 特征数组）。QgsVectorLayer/要素读写在 main_window.cpp
   接线层。对应 Python 架构守卫（factor 算法模块 GUI-free）；避免把
   Qgs* 编进可对账的数值编排（红线）。

4. **Oracle 用主仓 venv Python（`/home/kevin/projects/paleo_project/main/.venv/bin/python`）
   而非系统 python3**：系统 3.14 无 PySide6，`paleo_workbench.mapping`
   包导入即失败。venv 是现成的真实模块环境（任务前提「系统 python3 已能
   import」在本机不成立）；生成器 cwd=worktree，import 解析到 worktree
   内冻结源码（与 origin/main 同提交）。未重编任何 QGIS/vendor。

5. **相带多边形不走 shapely repair**。Python `generate_facies_polygon_layer`
   内部调用 `repair_invalid_geometry`（make_valid+orient）；C++ 冻结核对
   identity（M6 决策）。生成器在冻结时**断言** repair 前后坐标一致
   （格元描边环本来就是 CCW 外环/CW 洞、且简单多边形），若将来不一致
   生成器立即失败，而不是冻结一个 C++ 无法复现的 oracle。

6. **等值线/相带要素属性照抄 Python 图层构造器**：contour =
   level/label_text/is_index_contour/length/is_closed/factor/unit；
   polygon = facies_id/facies_name/facies/color/area/area_unit/
   area_percent/mean_value（地理 CRS 追加 area_approx_m2）。%g 标签、
   round(v,4)/round(v,6)（半偶）用 C++ 核的 round_to 复刻。
   QGIS 字段类型：real/string/integer（bool→integer 0/1，memory provider
   无原生 bool 字段类型差异风险）。

7. **图层角色注册**：等值线层 facts.role=`factor_contour`、相带层
   `factor_classification`（workspace 词汇精确串）；`write_granted=false`
   （factor 输出是 RAW 保护角色，Python `ROLE_RAW_PROTECTED` 同语义），
   不进编辑路由。

8. **CMake 全部经 `BEGIN CONV-01` 块追加**（根 option + libs/application
   条件源/链接 + platform 测试目标 + app 编译定义）。option 名
   `PWB_BUILD_CONV_01` 唯一；不触碰其他 CONV-* 块、不整理根 CMakeLists。
   root 块在 libs/application 子目录之前声明（option 必须先于使用）；
   fail-closed：CONV_01=ON 而 kernel/platform 关 → configure 报错。

9. **验证树**：平台测试需要 QGIS/平台闭包，§8 的 PLATFORM=OFF 配方对本
   切片不可行；改用本 worktree 新配 `build/conv-01`，选项
   PLATFORM=ON DATA=ON SCIENCE=OFF SEISMIC_*=OFF MAPPING_KERNEL=ON
   INTEGRATION_TESTS=OFF CONV_01=ON（最小闭包：kernel 需要 Pwb::Domain，
   平台测试需要 Pwb::Application/Ui/Qgis/ToolPolicy）。QGIS SDK 经
   `../../main` 同级解析，只读复用 vendor。`mapping_kernel.*` 既有测试
   在同树运行（§8.5 满足）。`build/cpp-integrated`（主仓）不重用——那是
   main 工作区的构建目录，与本 worktree 源不同。

10. **井点来源**：`runGeologicalFactorMap(layer_id, …)` —— layer_id 指向
    画布点图层（要素→Json 记录：well_id/name/qc_flag + 因子字段），
    保留 id `builtin.sample_wells` = 冻结 8 井 fixture（test_
    geological_mapping_pipeline.py 的 sample_well_dataset）。因子取值
    字段查找：精确因子名 → "value"（其余别名交给 extract 内核——记录
    原样透传，别名机在核里）。

11. **不发布 catalog 版本 / 不建 FactorMapTask**：任务验收是画布出现
    非空两层；B 目录发布、staleness 锚点、MapProduct 是后续切片（main
    plan M6 pipeline 编排面）。诊断（extract metadata + 网格统计 +
    distance_policy 注记）以 Json 返回并在状态栏摘要，诚实可见。

12. **菜单挂新顶层「地质(&G)」**（有 seismic 的「地震(&S)」先例）；
    快捷键 Ctrl+G。无阶段语义（mapping_stage 未设）时 policy 白名单门
    不触发——与平台现状一致（平台会话从未设置阶段）。

13. **oracle 生成器位置** `tools/oracle/generate_map_pipeline_fixtures.py`
    （与既有 8 个生成器同目录同风格：REAL import + sys.path 注入 +
    JSON 落盘）；fixture 落 `tests/cpp/platform/fixtures/map_pipeline_oracle.json`
    （平台测试目录而不是 mapping_kernel_tests——被测编排层在 application）。
