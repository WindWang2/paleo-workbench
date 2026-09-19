# 12 — acceptance（验收证据；每条记录命令、退出码、SHA、资源租约）

<!-- 规则：缺环境/硬件/凭据的验证显式标注"未执行"，不以 PR 绿灯相加冒充
     全量通过。 -->

## 能力清单状态（四列）

见 `../closure-matrix.md`（由 tools/migration/pwb_closure_matrix.py 生成，
源 = 本目录 capability-matrix.json）。

## R3 平台闭包构建与测试（候选 SHA：见提交；测试树与提交内容一致）

- 资源租约：`scripts/cpp-migration/invoke-resource-gate.sh`（common-dir
  flock，j2，MinFreeGiB=8）。排队记录：R2–R4 期间多线轮转持锁（exit 75
  退避轮询，最长单次等待 ~35min）。
- vendored QGIS SDK：`bash /home/kevin/pwb-sdks/build-qgis-vendor.sh`
  （共享锁内）→ exit 0（"ninja: no work to do"，369 步尾部已在早前持锁
  轮次完成；output/lib 含 libqgis_core/gui/analysis/native.so 4.2.0）。
- Configure：`cmake -S <worktree> -B build/cpp-close-12 -G Ninja
  -DCMAKE_BUILD_TYPE=Release -DPWB_BUILD_PLATFORM=ON -DPWB_BUILD_DATA=ON
  -DPWB_BUILD_SCIENCE=ON -DPWB_BUILD_MAPPING_KERNEL=ON
  -DPWB_BUILD_CONV_01=ON -DPWB_BUILD_CONV_16=ON
  -DPALEO_QGIS_SDK_DIR=<shared-vendor>/output
  -DPALEO_QGIS_BUILD_DIR=<shared-vendor> -DPALEO_QGIS_SOURCE_DIR=<main>
  ` → exit 0。
- Build：`cmake --build build/cpp-close-12 --parallel 2 --target
  pwb-platform platform_app_shell platform_shell_project_actions` →
  exit 0（603 targets，首次运行暴露 1 处 API 误用已修复）。
- 测试（ctest，offscreen，全部经资源门）：
  - Round A：`-R '^platform\.(shell_project_actions|app_shell)$'` →
    **2/2 passed**（新电池 + 含 palette provider 断言的 app_shell）。
  - Round B：`-R '^platform\.'` → **21/21 passed, 100%**。
  - Round C（关键确定性回归二遍）：`-R
    '^platform\.(shell_project_actions|app_shell|ui_wiring|edit_cycle|
    lifecycle_cycles|app_context)'` → **6/6 passed**。
- 修复轮记录：审查修复后 link 失败一次（预存测试目标自编译
  main_window.cpp 未链新源）→ PWB_APP_SERVICE_SOURCES 统一追加（见
  findings R7），重跑全绿。

## R4 无 Python 生产路径（全部落地）

- `scripts/cpp-migration/audit-python-runtime-deps.sh`（源审计）→
  **exit 0，AUDIT PASS**（归类修订见 findings R6：self_check 注释散文误
  报豁免；cartography_bind 列入 compat seam 名单）。
- 部署：`deploy-native-product.sh build/cpp-close-12 /tmp/pwb12-dist`
  （资源门 Exec，exit 0）→ 发行树就绪；**--self-check 12/12 PASS**，
  含：ui_shell（MainWindow+AppContext 生命周期）、data_gpkg_roundtrip、
  render_frame（800x600 非空帧）、layout_export、project_lifecycle
  （new→open→edit→commit + manifest checkpoint）、**python_free_process
  verified**、service_registry（7 硬服务）。
- `--exe /tmp/pwb12-dist/libexec/pwb-platform`（ldd 链路审计）→
  **clean: closure python-free，AUDIT PASS**。
- `audit-licenses.sh /tmp/pwb12-dist` → **PASS（exit 0）**：dist notice
  （licenses/ 目录）、qt6、QGIS-COPYING（部署收集）、onnxruntime、proj
  数据齐备；wle SKIP（worktree 子模块未检出，如实呈现）。
- 真显示器的 GUI/GL 与 Windows 全功能验证：**未执行**（本主机 Linux
  offscreen；Windows 属 cpp-platform-windows 自托管 runner 域）。

## R5 独立审查

见 acceptance R5（前置记录：2×P0 + 4×P1 + 10×P2 全部处置完毕）。

## 完成判定对照

- [x] 四 deferred 入口生产处理器 + 真实测试（platform.shell_project_actions）
- [x] CommandPalette 双 provider（platform.app_shell 断言）
- [x] 矩阵生成器 + 单测（6/6）
- [x] 许可审计工具 + 部署契约补齐
- [x] 平台闭包构建 + 21/21 测试 + 关键回归 ×2（本地 Linux）
- [x] 独立审查 + P0/P1 修复 + 复验
- [ ] 提交/推送/PR（进行中）
