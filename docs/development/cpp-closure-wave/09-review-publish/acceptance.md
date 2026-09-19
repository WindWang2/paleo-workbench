# 09 — 验收记录

## 本线验收条目 ↔ 证据

| 验收条目 | 实现 | 证据 |
|---|---|---|
| 未绑定工程明确状态 | ReviewExportPage 保留"未绑定工程"守卫；installer 在 store 缺失时 set_project_bound(false) + 清空页面态 | unbound_document_states_are_honest（closure_review.core_test）；platform.closure_review_install 打开前状态 |
| 真实有错工程输出可解释 QC | run_map_qc_on_document 六基本规则+十扩展规则+编图委托；status/rule_status/coverage 全记账 | broken_project_qc_is_explained、self_intersecting_facies_is_located、crs_and_renderer_rules… |
| 真实无错工程输出可解释 QC | pass 状态 + 零 issue + 稳定 upsert | clean_project_qc_passes_and_upserts_stably |
| 导出 layer filter / 生效版本 / 权限只读正确 | 导出走 ProjectManager::save 的 read_only/stale-write 守卫；导出文件原子写+parse 验证；ExportArtifact 按真实文档登记 | export_writes_parseable_json_and_registers_artifact；save 文档守卫为 01 线既有测试覆盖 |
| 短写/磁盘满失败不产生成功回执 | 原子写失败→DataError 且不追加 artifact；save 失败→action 失败 | export_failure_leaves_no_success_receipt、save_failure_is_not_a_success_receipt |
| 重开可追溯发布产物 | save_document 落盘 quality_reports/version_sets/export_artifacts；重开 store 可读回 | platform.closure_review_install（保存→重开→断言 status=pass） |
| 定稿守卫/替代/指纹 | demo-draft、lineage-untracked、require_qc_pass；同层位 supersede；指纹同内容稳定/改图变化 | demo_draft_refuses_finalize、require_qc_pass_blocks…、finalize_publishes_traceable_state、finalize_supersedes… |
| cartographic_issues 实际编图侧委托 | CartographicQaDelegate seam + 真实默认委托（未闭合环/重复顶点/退化面，mapping kernel 支撑）+ coverage 记账 | cartographic_delegate_runs_and_skips_honestly |
| nullptr provider 替换 | installer 经 AppShell::review_page() 注入真实后端；app_shell.cpp 本体零改动 | platform.closure_review_install（页面行数来自真实文档） |

## 测试命令（资源门内重放）

```bash
export PATH="/home/kevin/pwb-sdks/root/usr/bin:$PATH"
export LD_LIBRARY_PATH="/home/kevin/pwb-sdks/root/usr/lib:$LD_LIBRARY_PATH"
cd /home/kevin/project/worktrees/cpp-close-09-review-publish
scripts=/home/kevin/project/paleo-workbench/scripts/cpp-migration/invoke-resource-gate.sh
$scripts Configure -s . -b build/presets/linux-ninja -c Release \
  -a -DPWB_BUILD_PLATFORM=ON,-DPWB_BUILD_DATA=ON,-DPWB_BUILD_SCIENCE=ON,\
-DPWB_BUILD_MAPPING_KERNEL=ON,-DPWB_BUILD_CONV_01=ON,-DPWB_BUILD_CONV_16=ON
$scripts Build -b build/presets/linux-ninja -c Release -j 2 \
  -t "closure_review.core_test;ui_review.core_smoke;ui_review.qt_widgets_smoke"
$scripts Test  -b build/presets/linux-ninja -r "closure_review|ui_review"
$scripts Build -b build/presets/linux-ninja -c Release -j 2 \
  -t "platform_closure_review_install;pwb-platform"
$scripts Test  -b build/presets/linux-ninja -r "platform.closure_review_install"
```

## 结果（R4 填写）

- [ ] closure_review.core_test：待门内运行
- [ ] ui_review.core_smoke / qt_widgets_smoke（回归）：待门内运行
- [ ] platform.closure_review_install：待门内运行
- [ ] 受影响集复跑（两次确定性确认）：待做

## 明确未执行 / 限制

- Python 参考流程兼容性：未删除任何 Python 参考代码；C++ 生产路径无解释器/subprocess。
- catalog qc-DataRun / version_finalize DataRun 登记：catalog 侧注册面未合流，
  报告以 `provenance_registered=false` 诚实记录（不虚报来源运行）。
- 编图侧完整规则集（§14 cartographic_qa 全量）：归 08 线；本线交付委托 seam +
  真实几何默认委托， richer 规则集经同一 seam 接入。
- GL/硬件相关验证：不涉及（本线无 GL 面）。
- 全量产品矩阵：由 12 线在集成候选 SHA 上统一执行（本线提交可重放命令）。
