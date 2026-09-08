# 08 — Known Limitations（已知限制）

## 交互/功能

1. **跨图层拓扑传播的 undo 非原子**（Review 1 P1-4 部分残留）：同图层内
   主编辑 + 传播已合成单命令；**跨图层**传播写入各自图层的独立会话，
   一次 Ctrl+Z 只回退活动图层（QGIS 会话隔离的结构性限制）。用户需切到
   相关图层分别撤销。缓解：传播失败有 warning 日志。
2. **fallback 画布测距无数值显示**（Review 1 P2-11）：UnifiedMapCanvas 无
   `measure_updated` 信号，fallback 只有 overlay 折线；原生画布有状态栏
   「测距: X · N 段（椭球）」。fallback 是测试/headless 路径，按 Goal §5
   不为其新增专业功能。
3. **原生 identify 单命中 vs fallback 多层列举**（D6）：原生
   QgsMapToolIdentifyFeature 只回报单击命中的单要素；Python 路径的
   identify_all 列举所有可见图层命中。语义差异已记录，未伪装收敛。
4. **grid 捕捉模式无 QGIS 对应物**：参考网格捕捉（Python 专有构造）只在
   fallback 采点轨生效，不下推 QGIS。
5. **endpoint/intersection 捕捉在旧桥（无 manifest 声明）上不下推**：
   原生采点轨这两个模式不生效（有 warning 日志提示），fallback 轨继续
   支持；重建桥扩展即恢复。
6. **reshape 无回退实现**：依赖原生 addLine 数字化器 + 桥 reshape 算子，
   fallback 画布/旧桥上禁用（按钮带原因）。

## 平台/环境

7. **Windows 全量测试套件存在两处基线问题**（非本分支引入，main 同样复现）：
   - `test_theme_and_sidebar.py::test_app_shell_styles_through_the_theme_manager`
     在全量顺序运行中挂死（`setStyleSheet` → 表格模型重查询死循环；隔离
     运行通过）。验证跑批需 deselect 该用例；根因在 theme/table 组件，
     属本 Goal 所有权边界外的模块。
   - 全量顺序运行中存在少量与 venv 包版本相关的 geoviz 失败（main 与本
     分支差异集见 05-verification）。
8. **vendored QGIS Windows 构建是本 Goal 新增能力**：依赖树（vcpkg
   installed/ + 手工 QScintilla + Qt 6.8.0）位于本机 `C:/deps`，setup.py
   已内置 Windows 分支，但 CI（Linux）未覆盖该路径。
9. **Qt 版本双轨**（D1）：编译期 Qt 6.8.0 / 运行时 PySide6 6.11.2——Qt
   官方前向二进制兼容支持该组合；若未来 PySide6 升级到移除 6.8 符号
   的版本（7.x），需重评。

## 契约层

10. **LayerCapabilitySnapshot 尚无生产消费者**（Review 1 P2-7）：13 项图层
    能力已实现 + 测试钉死，UI 分支消费属后续目标（稳定接口已冻结）。
11. **EditDelta journal 上限 1024**：超过后丢最旧（审计流是滑动窗口而非
    全量账本）；全量账本由 undo 栈/工程版本承载。

12. **QGIS 腿既有问题（非 V7 引入，Windows 本机复现）**：
    - `test_map_render_backend.py` 3 个栅格测试需 `osgeo.gdal` Python 绑定，
      Windows venv 无（Linux CI 有）；与 V7 矢量 authoring 范围无关。
    - `test_qgis_layer_panel_menu.py::test_menu_reference_snap_check_state_follows_authority`
      的 teardown error（QMenu 悬垂回调）隔离复现，为既有测试问题。
