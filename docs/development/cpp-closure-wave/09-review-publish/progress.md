# 09 — progress

<!-- 每轮：候选SHA、目标、范围差量、真实命令/退出码、测试数据、资源租约、发现/处理、下一步 -->

## R1 盘点（2026-09-20，基线 06211541）

- 命令：`git fetch origin`（退出 0）；`git rev-parse origin/main` →
  06211541ae1ccce22b0d5ba9258ce722170ca98b。
- `which goal` → 不存在；技能清单无 /goal、/goal-loop → 文件持久化循环（task_plan 记录）。
- 分支/worktree 建立：`git worktree add /home/kevin/project/worktrees/cpp-close-09-review-publish
  codex/cpp-close-09-review-publish-20260920`（退出 0），`branch --unset-upstream`（防误推 main）。
- 协调登记写入 `.git/codex-coordination/cpp-close-wave/09-line.json`。
- 四能力清单初值：
  - implemented（已有）：ui_review 页面壳/接口/行渲染（UI-11）；project JSON schema 全 section；
    PwbDataStore 打开/提交/恢复；ProjectManager 原子保存。
  - merged（本波基线已含）：CONV-33 workflow 六模块、viz A–E、catalog mutex 修复。
  - wired（本轮目标）：ProjectReviewActions 后端 + review_page provider + 保存 seam。
  - verified：R4 后填写。
- 下一步：R2 实现 libs/closure_review。

## R2 实现（2026-09-20）

- 新增 libs/closure_review：
  - include/pwb/closure_review/review_qc_core.hpp + src/review_qc_core.cpp
  - include/pwb/closure_review/review_versioning.hpp + src/review_versioning.cpp
  - include/pwb/closure_review/report_export.hpp + src/report_export.cpp
  - include/pwb/closure_review/project_review_actions.hpp + src/project_review_actions.cpp
  - closure_review_tests/closure_review_core_test.cpp + CMakeLists
- 新增 apps/paleo_workbench_platform/closure_review_install.{hpp,cpp}
- 命名块装配：根 CMakeLists.txt（BEGIN/END CLOSURE-REVIEW ×2：库块 + app 接线块）、
  main_window.cpp（include + install + openProject notify）
- libs/application data_store.hpp：additive PwbDataStore::save_document()
- libs/ui_review review_export_page.hpp：additive set_actions_provider
- 状态：代码完成；语法级编译检查（g++ -fsyntax-only，逐 TU，无门占用）通过。

### R2 自审发现与修复（均在本线文件内）

1. default_export_dir 语义错误：初版用 <project_dir>/exports；Python 真值为
   artifact_dir_for = <project>.artifacts/exports（paths.py:32 旁挂目录，
   typical.paleo.json ↔ typical.artifacts fixture 佐证）。已修正 + 测试对齐。
2. IssueSpec 指定初始化器顺序与声明序不一致（C++20 编译错误源）。整文件重写，
   统一为 rule→severity→message→feature_id→feature_kind→geometry→ref→extra。
   中途一次正则批量修复损坏了文件内容——整文件干净重写恢复，无遗留。
3. mapping::Point 是 std::array<double,2>（非 .x/.y）；ring_centroid 对退化环
   返回首顶点而 Python 契约是顶点均值——locate 处自行实现退化判定
   （|2*signed_area|≤1e-12）+ 顶点均值兜底。
4. app 侧 CMake 时序：apps/ 子目录在 Pwb::ClosureReview 目标创建前配置，
   TARGET 守卫恒假 → 生产 app 永远装不上后端。改为根 CMakeLists 后置
   target_sources 块（VIZ-A 先例）。
5. 平台测试放错块：test_closure_review_install 需要与 platform_app_shell 相同的
   PWB_WITH_APP_SHELL 完整环境，从 tests/cpp/platform/CMakeLists.txt 移入根
   UI-17 块内（BUILD_TESTING 子块，额外 guard TARGET Pwb::ClosureReview+Data）。
6. 测试 harness 的函数级 static ProjectReviewActions 会跨用例共享——改为
   每用例独立对象。
7. fixture 断言与数据不符：map_clean 的 H2 井表含 outlier 行 → QC status
   是 warning 非 pass；补 linked_contour_draft_id 才能让定稿把草稿置 final。

### 资源租约记录

- configure/构建全部经 invoke-resource-gate.sh（common-dir flock）。
- 首次 Configure 与一次 Build 因 RESOURCE_BUSY（holder=08 线构建，
  持锁 ~37min）被拒，未抢锁；以 90s 退避排队，08 释放后重跑。
- 注意：`gate ... | tail` 会吞退出码（tail 恒 0）——日志以 RESOURCE_* 令牌为准。

## R5 独立审查与修复（2026-09-20）

- 审查代理：1 个 general-purpose（只读，跨 diff 06211541 全量核对 Python 冻结源），
  子代理累计 6.8M tokens。结论：核心语义为忠实移植；发现 1 个 P0 根因、
  3 个测试自相矛盾/路径错误、若干 P2 parity 偏差。全部当轮修复：

| # | 级别 | 发现 | 处置 |
|---|------|------|------|
| P0-1 | P0 | `DataError()` 默认构造 code=Unknown（非 ok）被当成功返回（4 处：save_document、export_quality_report_json、run_map_qc/export 成功路径）——成功被标失败、导出后跳过保存（诚实性反转） | 全部改为 `DataError(ErrorCode::Ok, "")`；测试 harness `next_save_error` 显式 Ok 默认 |
| P0-2 | P0 | finalize 测试断言与 Python parity 相反（再定稿是**新建** VersionSet 而非追加 snapshot），且 `snapshots[2]` 越界经 nlohmann 扩 null 抛异常杀死整个测试二进制 | 重写断言：每轮新 set 单 snapshot + finals/superseded 计数 |
| P0-3 | P0 | out_of_bound coverage 断言与实现（及 Python：coverage 只看 map_extent **参数**）矛盾 | 拆两个断言：view_state 回退仍产 issue 但 coverage=skipped；传参时 evaluated=true |
| P1-1 | P1 | 平台测试 fixture 路径双写 `/typical/typical` | 修正为 `../data/fixtures` + `/"typical"` |
| P2-1 | P2 | horizon 未 strip（Python `.strip()` 语义） | strip_copy 助手用于 target_horizon_present + 井表匹配 |
| P2-2 | P2 | 编图委托问题并入报告但不在 rules/coverage 记账（诚实性缺口） | 增设 `cartographic_side_checks` 键（evaluated/skipped+原因），标注为本线扩展 |
| P2-3 | P2 | MultiPolygon 定位点死分支（少下钻一层外环） | 修正下钻 `coordinates[0][0]` |
| P2-4 | P2 | json_truthy 把数值 0 当真值（Python bool(0)=False）；degraded 要求严格 bool；float 标量化空串 | 全部对齐 Python 语义 |
| P2-5 | P2 | default_export_dir 只建 exports；Python ensure_artifact_layout 建 7 个子目录 | 补齐七目录 |
| P2-6 | P2 | is_demo_draft 只拒绝 boolean true；Python 拒绝任何真值 | 取原始 Json 值做 json_truthy |
| P2-7 | P2 | openProject 中途失败路径会把页面留在已绑定态（notify 位置过早） | notify 移至 openProject 成功尾部 |
| P2-8 | P2 | review_export_page.cpp 未绑定导出仍显示"导出完成"（UI-11 既有、当前接线不可达） | 不改（非本线文件，不churn）；记入 findings 待 UI-11 侧修复 |
| P2-9 | — | ledger 四文件在声明变更集之外 | 任务规定行为（本线独占维护），维持 |

- 审查确认无发现区：内存/生命周期（ordered_json 指针稳定性论证成立）、命名块纪律、
  CMake 时序、规则/状态/coverage 核心 parity、失败诚实性机制。

### 环境记录（供恢复）

- 工具链：`/home/kevin/pwb-sdks/root/usr/bin/{cmake,ninja,ctest}`，
  需 `LD_LIBRARY_PATH=/home/kevin/pwb-sdks/root/usr/lib`（cmake 依赖 librhash）。
- 系统无全局 cmake；`/tmp/pwb-oracle-venv` 里另有一份（13 线的）。
- 门竞争：08→其他线连续持锁；链脚本 `/tmp/p09_gate_chain.sh` 每阶段
  Probe 等待 + 90s 退避，被拒不抢锁。
- `gate ... | tail` 吞退出码（tail 恒 0）——一律以 RESOURCE_* 诊断令牌为准。
