# B 线 goal-loop 账本（井间对比、剖面与井震标定）

- 目标：完成 V3 批次净剩余（见 scope.md），交付 PR `codex/viz-b-crosswell-welltie` → `main`。
- 完成条件：scope.md §3 五条硬门全部满足。
- 迭代上限：200 轮。
- 环境：Linux x86_64，cmake 4.4.3，ninja 1.13.2，g++ 16.2.1，Qt6（/usr/lib/cmake/Qt6），内存 ≥46 GiB 可用。
- 资源锁：`/home/kevin/projects/paleo_project/.bare`（git common dir），门禁 `scripts/cpp-migration/invoke-resource-gate.sh`，jobs=2，MinFreeGiB=8。
- 构建树：`build/viz-b`（本 worktree 独占）。

## 轮次记录

| 轮 | 改动 | 验证 | 结果 | 下一步 |
|---|---|---|---|---|
| 1 | 定位仓库/建 worktree（origin/main@7290f727）、init submodule（geo-viz-engine@08851951，本地 --shared 克隆）、读计划与 PR #1321/#1352/#1375/#1394 实码、三路源码调查、写 scope.md | — | 通过 | 实现 Qt-free 核 |
| 2 | 实现 cross_well Qt-free 核 6 模块 + well_tie Qt-free 核 6 模块 + Qt 半（section canvas/formation preview/两种报告导出/tie canvas）+ 根与子目录 CMake（VIZ-B 块）+ app dock（JobCenter/会话代际/sidecar 持久化/链接编辑器与导出对话框绑定）+ MainWindow 接线 + oracle 生成器×2（真 Python 参考 08851951 + 真 LAS A4/A13/A16 via lasio）+ 测试代码（oracle/Qt smoke/集成/example） | fixture 冻结 25+72 cases；桌面核查修 3 bug（palette 悬空引用、cstdint、find_pick 限定） | 通过 | 门禁内构建 |
| 3 | 第 1 轮独立审核（Python/科学语义 agent）12 项逐条对账 | P0×1（kDisconnect undo/redo 空操作）、P1×5、P2×15 | 全修：kDisconnect undo/redo、zoom 锚点 [0,1] 钳制、NN 平局改首见插入序、吸附 NaN 语义（深度 mask + argmax NaN 传播）、save_csv RFC4180 引用+\r\n、synthetic.hpp 文档 | 门禁构建 |
| 4 | 门禁内最小配置（PLATFORM=OFF + VIZ_B=ON）+ 构建 Qt-free 核 | 修 auto_tie lambda 变量名、unique_ptr<Command> 不完整类型（out-of-line ctor/dtor）、测试类型限定 | 核 + 2 oracle 测试链接成功 | 跑测试 |
| 5 | 跑 oracle 测试，修 6 个失败 | cross_well：**生成器快照共享可变引用**（to_dict 非 deepcopy → accept 的 clear() 追溯污染全部快照）→ 生成器改 deepcopy；**Python 命令 aliasing 语义**（add 的 pick 在 undo 后保留其后 mutation）→ picks_model 重构为 `shared_ptr<HorizonPick>` 存储；zoom/clamped 浮点路径逐句对齐（new_span 预钳制 + span=min(full,·) 先于 >= 判定）；saved_text 以 newline="" 读回保留 \r\n；negative self-check 计数隔离（捕获后回滚） | **cross_well oracle 236 checks 全过** | 修 well_tie fixture |
| 6 | well_tie fixture 裸 NaN（json.dumps 默认写 NaN 字面量，nlohmann 拒绝）→ tagging；测试 null canonical、residual 头部切片、r 相对容差 1e-12（numpy pairwise vs naive 求和序）；rc 长度案例改真不兼容（[2]vs[3]；numpy 广播下 [2]vs[1] 静默成功）；sonic 警告 None 文本 | `ctest -R viz_b`：**2/2 Passed**（well_tie 3.61s 真实井管线、cross_well 0.12s） | 通过 | OFF 配置 + 集成 |
| 7 | OFF 配置（PWB_BUILD_VIZ_B=OFF）验证；集成验证脚本（configure+build+ctest×2+MALLOC，全程门禁 jobs=2） | OFF configure 成功且 viz 目标全部不出现 ✓；集成首轮失败：QGIS deps prefix 缺（本机无 /home/kevin/pwb-sdks）→ 取 viz-c 同款 `PWB_QGIS_DEPS_PREFIX=main/native/gdal-vendored/install`（只读复用）；二次失败：首轮已把默认写进 CMakeCache（cache 优先于 env）→ 清 build 树重跑 | 进行中 | 等集成结果 |
| 8 | 第 2 轮独立审核（C++/Qt 生命周期与并发） | **P0×5**：DTW spec 回调在 worker 线程触碰 GUI（QMessageBox/模型写/定时器）+ owner 释放后 prev_done UAF + 单 owner 复用抛异常 + Qt 半 4 处编译错误（hovered_well_ 残留、QPageSize::Landscape 不存在、dock 缺 include/大小写/synthetic 签名/const 违规）+ WellTieCalibration 实参交换（paintEvent 内抛异常路径）；P1×3：canvas 从未 set_models（拾取不可见）、n_samples 恒 0（band 降级 20）；P2×9 | 集成构建同样卡在 Qt 半编译错误（与审核一致） | 全部修复 |
| 9 | 修复审核 2 全部发现：DTW 提交重构为 submitSegyJob 模板（spec 回调留空、GUI 工作全在排队的 on_finished、每次提交新 owner、progress MinimumDuration(0)）；tie_canvas 实参序+入口长度校验；export 各路径 painter.isActive()+QFileInfo::exists 诚实返回；hover_key_ 去重；Svg/PrintSupport 改 REQUIRED（源码无条件包含） | 待集成重验 | 进行中 | 审核轮 3 |
| 10 | 第 3 轮独立审核（产品接线/重复/范围与构建） | **P0×3**：app CMake guard 与链接不匹配（缺 UiWorkers/UiWellseisQt 链接）、dock synthetic_from_logs 三参误用、验证脚本落在 scripts/（协议外落点）；P1×2：include 嵌在 GEO3D 条件内、换工程不 flush 旧 sidecar（数据串扰窗口）；P2×5（scope 决策不同步、correlation_layer 落点文档错、closeEvent 时序、depth_domain/method 写回、sidecar 无井来源） | 合规确认：并行写入协议全过（4 个公共文件均标记块）、无第二 DTW/LAS、导出与链接编辑真用 #1394 组件、CMake 无环 | 全部修复：链接补齐、签名改正、脚本移入 docs/development/cpp-viz-b/、include 移出条件块、openProject 先 handle_project_closed、closeEvent 钩子移到取消门之后、scope 同步、sidecar 记录井来源并自动重载 |
| 11 | 集成验证第 4 次运行：pwb-platform TU 失败于 `version_id` —— **主线既有 bug**（7290f727 与 39c0833d 相同结构；我的 38 行 diff 未触碰该函数；主工作区旧构建未覆盖此路径） | 提交 issue #1399（不改公共实现）；验证脚本改为构建本线闭包（Qt 半×2 + oracle×2 + smoke + 集成 + example + 新增 dock_smoke：真实 dock+JobCenter 编译运行证据） | 记录在案 | 继续修 |
| 12 | 修剩余编译/测试问题：qt_smoke QPixmap→toImage 与 SectionScene 别名；dock_smoke 链 Pwb::JobQt（JobOwner/install_quit_drain 所在）；**SectionCanvas 构造函数漏 impl_ 初始化**（4 个 Qt 测试段错误的根因，gdb 定位）；engines_example 先建输出目录；集成测试 twt 断言改掩蔽轴对齐 + SVG 身份断言改真实绘制内容（井名+曲线标签）；dock 加载器接受 real_wells 键 | 最终集成验证：**configure+build（jobs=2 门禁内）+ ctest 两遍 + MALLOC 审计 = 3×100% tests passed out of 6**（well_tie.oracle / cross_well.oracle / cross_well.qt_smoke / integration / engines_example / dock_smoke）；最小配置第二遍 2/2 通过；OFF configure 通过 | **通过** | 提交 PR |

## 已知声明（容差/分歧，scope.md §2 同步）

- 相关系数 r 与 numpy 的差异 ≤1e-12 相对容差（pairwise vs naive 求和序）；legacy evaluator residual 仅对比冻结头部 8 元素。
- PCA 符号固定（最大|分量|取正）+ 投影稳定平局 = 文档化 hardening；fixture 同时冻结 numpy raw 序佐证翻转真实存在（reversed_input_order 案例）。NN 平局按首见插入序（Python dict 序）。
- new_pick_id 为随机（uuid4 同形状 12 位小写 hex）；oracle 以结构对比 + 跨快照 id 稳定性验证。
- 退化输入分歧（P2，均有代码注释）：空 wavelet Python 抛错/C++ 返回全零；calibration 空 twt 表 Python IndexError/C++ 返回空；stod 与 Python float() 对下划线/十六进制字面量接受度不同。
- well_tie fixture 的 `cal_from_sonic_descending` sonic 数组含 tagged "nan"（真实 LAS 缺测经参考管线保留）。

## 最终验证记录（门禁内，jobs=2）

- 最小配置（PLATFORM=OFF, VIZ_B=ON, Debug）：`viz_b.well_tie.oracle` + `viz_b.cross_well.oracle` 两遍 100%（0.54s/0.02s）。
- OFF 配置（PWB_BUILD_VIZ_B=OFF）：configure 成功，viz 目标不出现。
- 集成配置（全开关 ON + VIZ_B=ON, Release，QGIS SDK 只读复用主工作区 + PWB_QGIS_DEPS_PREFIX=gdal-vendored）：本线闭包构建 + `ctest -R viz_b` 两遍 + `MALLOC_CHECK_=3` 审计 = **3×100%（6 测试）**。
- pwb-platform 完整二进制被主线既有 bug 阻断（issue #1399，非本线）；dock 的编译/链接/运行证据由 `viz_b.dock_smoke`（真实 dock + 真实 JobCenter）承担。
- 脚本：`docs/development/cpp-viz-b/verify-integrated.sh`（资源门禁全程包装）。

## 外部依赖记录

- geo-viz-engine submodule：gitlink 08851951（与主工作区检出一致，`git clone --shared` 本地初始化）。
- QGIS SDK（主程序验证用，只读）：`/home/kevin/projects/paleo_project/main/native/qgis_render_bridge/build/qgis-vendor/output`。
- Python oracle 环境：`/home/kevin/projects/paleo_project/main/.venv/bin/python`（numpy 2.5.2 + PySide6）。
