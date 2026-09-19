# 02 — progress（轮1 实现记录）

## 候选 SHA

base = origin/main 06211541（PR #1410 + #1411 已核）。分支 codex/cpp-close-02-workflow-runtime-20260919。

## 已完成（轮1）

1. **协调登记**：.git/codex-coordination/cpp-close-wave/02-line.json（共享 common-dir，不入库）+ 本四文件台账。
2. **workflow_runtime 增量**（resolve_context.{hpp,cpp} + current_context 两公共方法 + catalog_seam restore_state + runtime_service repository()）：
   - resolve_current_project_version_context 五段真实移植（catalog pointers → horizon → correlation/fault + domain tips 去重 → factor grid + sci identity → prediction model_ref → extra_selected）。
   - CurrentProjectVersionContext::deselect_version / select_version_only（Python 直接集合变更的镜像）。
   - RuntimeStore::restore_state（持久化子类再水化；索引/计数器重建）。
3. **新库 libs/closure_workflow**（python_json / persistent_catalog / map_product / integrated_compilation / workflow_scheduler / cache_run_rail / host_bindings 七 TU）+ 根 CMake PWB_BUILD_CPP_CLOSE_02 门（option 半在 CONV-33 前，subdirectory 半在 CONV-32 后）。
4. **Oracle 三套冻结**（tools/oracle/generate_closure_{resolve,map_product,fusion}_fixtures.py，真实 Python 驱动，两次生成字节一致）：
   - closure_resolve_oracle.json：6 例（真实 ProjectDocument + catalog runtime 注入）。
   - closure_map_product_oracle.json：11 例（指纹/装配/六拒绝/fail-run/lifecycle/rerun）。
   - closure_fusion_oracle.json：9 例（模型×2/降级运行/pin mismatch/注册/四拒绝）。
5. **RunEngine CacheRunRail**（run_engine.{hpp,cpp} 增量构造参数 + execute_node receipt 后钩子；Python L735 _register_cache_run 语义）。
6. **测试四件**（resolve/map_product/fusion 回放 + closure_e2e 验收闭环），全部 -fsyntax-only 通过（-Wall -Wextra，仅存库内预存 warning）。

## 命令/退出码（轮1）

- /tmp/pwb-oracle-venv/bin/python tools/oracle/generate_closure_resolve_fixtures.py → 0（×2 字节一致，sha 6a4f2a4d）
- /tmp/pwb-oracle-venv/bin/python tools/oracle/generate_closure_map_product_fixtures.py → 0（×2，sha 537f7732）
- /tmp/pwb-oracle-venv/bin/python tools/oracle/generate_closure_fusion_fixtures.py → 0（×2，sha 06844bd1）
- g++ -fsyntax-only 全部新 TU → 0 错误

## 资源租约

- 资源门（invoke-resource-gate.sh Probe）— 本主机 busy（其他 C 线持有，pid 轮换中）；轻量语法检查串行完成，完整编译/链接/ctest 排队等门。owner/PID/心跳记 02-line.json。

## 轮1 追加

- e2e 增补 phase L（UI 宿主绑定验收）：bind_workflow_ui_services 四缝 + reopen_project_workflow 恢复面 + SessionPointerBridge 同进程恢复/跨进程拒绝。
- e2e 逻辑修正：服务路径与引擎路径 provenance 双登记去重（register_provenance 标志）、input_version_ids 参数形状归一、FRESH 复验指向重算新 run、cache 轨计数语义（仅 fresh 执行登记，Python 同）。
- 全部新 TU + 测试 TU -fsyntax-only（-Wall -Wextra）零错误。
- 独立审查子代理已启动（只读，覆盖 Python 对拍/e2e 有效性/oracle 自证/持久化/并发/CMake 六面）。
- 资源门持续被其他线占用（holder 轮换），后台轮询 Exec 排队中；多次 probe 记录在案。

## 下一步

1. 门释放 → 全闭包编译 + 链接四测试 → 运行 ×2（后台任务 exec_6792209e）。
2. 修 oracle replay 差异（预计在 descriptor/features 字节细节）。
3. 落实审查 findings → 复验 → 提交 PR。


## 轮2-4：门内构建与测试迭代（exec_942db77f 轮3 记录）

- 轮1（gate 内）：resolve 31/31 绿；map_product FATAL（fixture 捕获了后置状态 + 测试悬垂引用）；fusion width 类型差 + pin 门；e2e recipe 路径。
- 修复：generator lifecycle/rerun 冻结 PRE-state、map_product 生成器冻结 datetime 类（pm.datetime）、unresolvable_factor 冻结真实证据、fusion 测试 register=False 显式、pin 门改 seam 存在性、e2e save_recipe 传文件路径、导入同资产追加版本、H2/K2 双节点、rail 基线比较、canonicalize_ints + semantic diff 细节。
- 轮3：resolve 31/0 绿；fusion 14 checks 3 失败（registration.requested 默认真、证据输入、H2）→ 已修；e2e 49 checks 1 失败（H2 单节点）→ 已修双节点。
- map_product 的 assemble.map_products 仍差（detail 已带 diff path 待轮4 定位）。

## 下一步

轮4 运行中（exec_be7170d0）。全绿后 ×2 复验 → 更新 acceptance → 提交 PR。
