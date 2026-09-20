# 08 — 数据制备、编图编辑与组合文档：任务计划

## 目标

在 origin/main (06211541) 基础上完成本线功能闭环：

1. **composition_panel 真入构建**：消除 UI-17 deferred 的 `libs/ui_seqviz/src/qt/composition_panel.cpp`
   编译债（引用了不存在的 core API），接入 mapping_document 组合核与 document_io 持久化。
2. **PreparationPage 真交付**：`libs/ui_pages_data` 的 `preparation_page.cpp`（当前不存在，
   占位 PagePlaceholder），全生命周期（制备/等值线/井QC/代数守卫）+ 真实 ui_workers 域核。
3. **编图编辑闭环**：ui_pages_mapedit 场景/视图从未被任何 app 实例化 → 通过 closure_mapping
   适配器消费 mapping_document（MapDocumentService），交付真实图层编辑、撤销/重做、修改后
   保存/放弃、多期次（多图件）文档切换、重开恢复样式/CRS/视图一致。
4. **产品装配**：closure_mapping_install 替换 ui_map::MappingPage 的 4 个“未迁移”占位面板 +
   AppShell hub3 preparation 占位；12 的全局 save 路由到本线保存接口。

## 平台支持声明

- 平台无 /goal、/goal-loop 技能或命令（技能清单仅有 browser-use/document-skills/skill-creator/
  zcode-guide）。按任务书要求改用**文件持久化循环**（本目录四文件 + 每轮 progress 记录），
  不伪造命令成功。
- 预算 3.6 亿 tokens 为上限请求：平台无按任务显式预算接口；以子代理用量统计累计
  （已用：盘点两代理 ~2.15M）。完成即停，不为消耗预算重复验证。
- 代理层级：根 ≤3 直接子代理（已用 2 个 Explore 盘点 + 预留 1 个独立审查）；子代理不再派生。

## 分支与 worktree

- 分支 `codex/cpp-close-08-mapping-authoring-20260920`，基于 origin/main 06211541。
- worktree `/home/kevin/project/worktrees/cpp-close-08-mapping-authoring`。
- 协调登记 `.git/codex-coordination/cpp-close-wave/08-line.json`（同 git common-dir）。

## 轮次计划

| 轮 | 内容 | 状态 |
|---|---|---|
| R1 | 盘点（UI-17 findings、迁移清单、PR #1412 依赖、Python 冻结源、C++ 组件现状） | done |
| R2 | composition_panel 修复 + core 值转换助手 + 入构建 + 面板测试 | in_progress |
| R3 | preparation_page.cpp + 逻辑测试 + 入构建 | pending |
| R4 | closure_mapping_document 适配器（MapDocumentService↔场景、切换守卫、保存/放弃）+ 测试 | pending |
| R5 | closure_mapping_install（MappingPage 占位替换 + AppShell preparation 替换）+ 平台测试 | pending |
| R6 | 受影响回归（两遍）+ 独立审查 + 修复复验 | pending |
| R7 | 提交、推送、PR | pending |

## 资源门记录

- 工具链：`/home/kevin/pwb-sdks/root/usr/bin/cmake`（需 `LD_LIBRARY_PATH=/home/kevin/pwb-sdks/root/usr/lib`）
  + 同目录 ninja；交互 shell 的 ninja alias -j40 禁用，一律显式 -j≤2。
- QGIS SDK 只读复用主工作区 vendor 产物（PALEO_QGIS_SDK_DIR/BUILD_DIR 指向
  /home/kevin/project/paleo-workbench/native/qgis_render_bridge/build/qgis-vendor*），
  源用本 worktree third_party/qgis；build/cache 全部写入本 worktree build/。
- configure 走 `scripts/cpp-migration/invoke-resource-gate.sh`（Probe 退避 180s 循环）；
  首轮 Probe 遇 04 线 holder（PID 425675），退避后获取。
