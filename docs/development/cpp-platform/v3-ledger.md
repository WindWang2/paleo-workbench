# CPP-A v3 轮账本（codex/cpp-v2-platform）

> 基线 `53e22b67`；上限 15 轮；本文件只记 A 线。资源门禁全程经
> `invoke-resource-gate.sh`（PowerShell 门禁的 POSIX 等价端口，本机无 pwsh）。

| 轮 | 改动 | 验证 | 判定 | 下一轮 |
|---|---|---|---|---|
| 1 | 侦察：总设计/平台历史文档/平台源码全量/主仓状态；发现本机为 Linux（非 prompt 假设的 Windows）：Qt 6.11.2 系统包 + vendored QGIS 4.2.0 Linux .so 树实测在位；B/C v3 worktree 已就绪停基线 | 文档/源码核阅完成；ldd/头文件实测 | 通过 | 建 worktree+门禁 |
| 2 | 建 `codex/cpp-v2-platform` sparse worktree（cone 排除 third_party 16.7k 文件）；`invoke-resource-gate.sh`（同锁/8GiB/exit75 语义）；`PwbQgisSdk.cmake` 跨平台化（.so 导入、Qt 前缀 fail-closed 校验、路径经 cache/env 注入不写死） | Probe `free=53.26 GiB`；configure 一次通过（GCC 16.2.1） | 通过 | 首编 |
| 3 | 首编修复：qgis_{gui,core,analysis}.h 生成头目录、namespace-QWidget 陷阱、QGIS4 API 差异（getFeature/capability flags/三参 QgsApplication 构造/mapToolSet/closestVertex）、PrintSupport、AUTOMOC、main.cpp 缺头 | 全量构建通过（该代码**首次在任何平台真实编译**） | 通过 | 测试 |
| 4 | 测试修复：QgsApplication 应用对象（instance() 是 qobject_cast，普通 QApplication → 全部 acquire 抛异常）、PROJ/GDAL Linux 路径探测、getFeature 测试、并行 job 渲染头名、oracle 复核后修正 toolpolicy 预期（Python oracle 原位对账）、checkable 提升 | platform.* 8/8 绿（golden 28×77 对账含） | 通过 | UI 接线 |
| 5 | MainWindow 全面接线：菜单/工具栏/快捷键同源 QAction、真实操作（打开/地图工具/顶点工具/undo/redo/提交/放弃/导出）、dirty-close 三态可注入 responder；`platform.ui_wiring` 新测试；提交 `8dc3d7d4` + v3-runtime-manifest/v3-contracts | 构建+8/9（ui_wiring 编译过、跑测试被 B 持锁 75 拦） | 基本通过 | 等锁跑 ui_wiring |
| 6 | 合入 B `82430eca` + C `410bd6b0`；根 CMake integrated all-or-nothing + D/E fail-closed 开关；适配层（PwbDataStore/PWBVOL1/CatalogResultPublisher）；integration 两测试源码 | B 头文件先行、WritableSession 未实现 → 改用 B 已提交组合面 | 源码完成 | integrated 构建 |
| 7 | B 移植缺陷最小修复（gmtime_r/windows.h 路径桥/_wgetenv/fsync，标注归还）；适配层 include/类型修正；B 交付实现 `a228bafb` 后二次合入（冲突取 B 侧，双方修复一致） | integrated 全量构建通过；算法链绿；工程链败于目标选择（fixture 绑定是合成 id） | 部分通过 | 工程链接线 |
| 8 | 工程链：CommitRequestV1 显式 asset_id + 资产头版本乐观锁（首绑图层 rebind 语义）；GDAL_DATA 标志文件探测 | 工程链直跑绿但 CTest 环境堆损坏 → gdb 栈定位**双 sqlite3 符号抢占**（静态 vendored 抢占 GDAL 的动态 libsqlite3 内部调用） | 缺陷定位 | 修 sqlite3 |
| 9 | vendored sqlite3.c `-fvisibility=hidden` | `MALLOC_CHECK_=3` 下工程链绿：编辑→B commit（+1 版本、旧 hash 不变、幂等、stale 拒绝、重开绑定推进） | 通过 | 全量 |
| 10 | 全量 integrated：**MainWindow 析构顺序 UAF**（integrated 堆布局暴露）修复 + ToolActionSet 所有权 + layerById 空守卫 + ui_wiring 断言逐项修正（QMessageBox 位标志枚举！、fixture 文件名、模块级保存语义、discard 终结态后不可复用窗口） | platform+integration+science 15/15；全量 32/34（唯二 = B fixture 绝对路径，移交） | 通过 | WLE |
| 11 | WLE dock 嵌入（VisualizationWellLog 守卫；无 Q_OBJECT → dock->widget() cast）；self-check 真 LAS 加载；部署树 + env -i 自检 exit 0；提交 `18ba6409`；纯平台树回归 9/9；四文档+集成验证 | 见 v3-verification / v3-integration-verification | 通过 | 收口 |
| 12 | B 后续交付（`50075fb0`+`2286b23b`）合入复验：仍 32/34（fixture 绝对路径问题在其修复范围外）；终验一次全量+链接审计（0 Python/PySide，Qt 单源 /usr/lib） | 资源 75 ×3（B 持锁）按协议等待，未绕过 | 收口 | — |
| 13（main） | 外部评审 P1 修复：发布失败改抛 `CatalogPublishError`+run 终态收敛；EditController stage/finalize 拆分（B 接受后才写源 provider）；operation ID `pwb-edit-<layer>-r<rev>-<sha8>` 唯一化+重试复用+base_version 冻结；`data.oracle_compare` 语义比较去机器绑定；D/E 开关纳入 integrated 树；新增 `integration.attribute_chain` 五线真实链（E 内核→C runtime→A publisher→B catalog→重开读回对账 E 冻结 oracle）。详见 v3-verification §4a | main 工作区 integrated 44/44 ×2（data 19/19、science 4/4、D 5/5、E 4/4、platform 9/9 含新增连续编辑/重试/源未写断言、integration 3/3 含发布失败注入两段+五线链）；MALLOC_CHECK_=3 platform+integration 12/12 | 通过 | 评审后续第 2/3 步剩余（.paleo 工程会话、D/E 主程序装配） |
| 14（main） | 评审第 2 步：`MainWindow::openProject`（真 store 拒只读→recover() 启动恢复→GeoJSON 绑定图层物化为 `.pwb-working/` 显式工作副本→facts/active 接线；文件菜单“打开工程…”）；新增 `platform.project_session`：prep 绑定→打开→编辑→保存→payload 哈希前后不变+工作副本已改+绑定推进→重开刷新 | integrated 45/45 ×2；MALLOC_CHECK_=3 platform+integration 13/13 | 通过 | D/E 主程序装配（第 3 步剩余）、新建工程 |
| 15（main） | 转换整体计划（docs/development/cpp-conversion-main-plan.md）M1-M3 三连：<br>**M1** `AlgorithmRunner`（application，内核无关）+ 主窗口注册 E 四内核 + D 切片 dock + 计算属性对话框；`platform.attribute_ui`（真 MainWindow：种子 PWBVOL1→rms→run complete+新版本→viewer ok）<br>**M2** `newProject`（`ProjectDocument::create_new`+空 catalog+bootstrap 资产经 B run 生命周期）+ GPKG 物化 + `PwbDataStore::commit` 单活资产自动定向；暴露并修复 B 三缺陷：schema 缺 joint_analysis/geo3d_workspace 默认（create_new 产 null 不回读）、`open_read_write` 新库不种 sync_state（重开被拒）、`apply_rebind_to` 首绑空转（membership 不存在即丢弃）；`platform.project_session` 增 bootstrap 场景（新工程→开图层→编辑→保存自动定向+rebind→重开物化）<br>**M3** `libs/seismic_io` SEG-Y 读取器（IEEE(5)/IBM(1) 大端、道头驱动排序不假设有序、严格规则网格：不完整/重复/非均匀一律拒）；`importSegy` 入库 Raw 体版本（地震菜单）；`seismic_io.segy_read`（真 tiny.sgy vs geoviz oracle 逐样本一致+4 拒绝路径+乱序重排）；`platform.attribute_ui` 增 M3 场景：导入 tiny.sgy→rms(21)→与冻结 expected_rms_w21 对账(<1e-5)→导入体与结果体均 viewer ok | integrated 47/47 ×2（data 19、science 4、seismic_viewer 5、seismic_attributes 4、seismic_io 1、platform 11、integration 3）；MALLOC_CHECK_=3 platform+integration 14/14 | 通过 | M4 按需、M5（Windows 回归需外部环境；入口切换为产品决策） |

## 结论

- **模块级（A 线自身）**：platform.* 9/9，两次树（独立+integrated）均绿 —— 完成。
- **集成级（B/C 真实模块）**：32/34，唯二失败属 B 线 fixture 可移植性（已定位移交，非集成缺陷；B 自树 19/19 证据其侧通过）——B/C 侧完成。
- **五线整体**：D/E 未交付 → prompt 的五线完整验收**未达成**（fail-closed 记录，不伪称完成）；A 侧接线位、消费指南、PWBVOL1 数据面已备好（v3-handoff）。
