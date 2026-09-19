# CONV-31 decisions — catalog 域核

Branch `feat/cpp-catalog`（base origin/main 5a6373bd）。Scope：`31-findings.md`；巨文件差距：`31-gap-analysis-big.md`。

## D1 — 移植面（15 个新 TU，全部 Qt-free core，并入 pwb_catalog）
document_index（_CatalogMaps 等价）/ refs（types.py DTO + view.py payload）/ checksum / policies（governance+intermediate_policy+port_roles+model_gates）/ telemetry / lineage_graph / impact / explain / sources / queries / tags（含 #1182 惰性回滚日志）/ legacy_migration（+legacy_projection）/ audit（17 类检测合并现有子集）/ v11_policy（ports⊆flat 不变量、pin/retention/eligibility/lifecycle、operation→role 回填、bundle 名字池）/ trash（storage.py 剩余：trash/restore/purge/working-copy/CAS 判定）。

## D2 — Oracle 与验证边界
`tools/oracle/generate_catalog_domain_fixtures.py` 真实 import 冻结 37 节到 `tests/cpp/data/fixtures/catalog_domain/oracle.json`（{ROOT} 占位；随机 id 段在 replay 两侧掩码）。C++ replay `data.catalog_domain`：13 用例全绿 ×2 + negative self-check（5 处篡改全检出）。**本机无 cmake**：g++ 16.2.1 直连编译（sqlite3.c 以 C 单编）驱动验证；CMakeLists 已按 CONV-15/26 先例挂 target_sources + pwb_data_test，CI 侧可构建。行为面（checksum 分块取消、tags 失败回滚、telemetry 撕裂行跳过）有对应行为断言。

## D3 — DataError 成功哨兵
`DataError()` 默认 code=Unknown：成功路径必须显式 `DataError(ErrorCode::Ok, "")`（repository.cpp 先例）。本切片三处初版踩坑（apply_run_ports 尾返回、port_error 初值、save hook 默认）已修。

## D4 — 有界偏离（如实）
- 大小写折叠 = ASCII fold（entity_view.hpp search_fold 先例；这些词表全是 ASCII+CJK，等价）。
- NFKC 不带（同上，15-decisions D6）。
- governance py_str 对非标量走 json dump（Python str(dict) 形状差异，实践中治理值均为标量）。
- explain/audit 的 payload 解析默认第一梯（service.resolve_path 完整搬迁梯在 31b）。
- audit._parse_iso 取秒（strptime 前缀语义）。

## D5 — 不移植/退役（详表见 findings A3）
runtime/port/adapter（Python DI seam）、lifecycle.py（应用层翻译层）、grid_artifact（NPZ 格式边界）、domain_binding（geoviz 解析器边界）、edit_session（阻塞于 service working-copy 面 + M10 消费方）、entity_views 的 well/survey 视图（待 CONV-44 typed links）。

## D6 — 31b 子切片（拆分理由：文件数大者可拆，任务书 §4）
service.py 深核（open 流程/batch_save/模型注册表/working-copy 生命周期/resolve_path 阶梯）、db.py 通用 apply_changes+DirtySet 通道与 14 个惰性读、store.py manifest load、service_v11 bundle 放置编排剩余。本切片已交付其 C++ 地基（DocumentIndex/refs/tags/v11_policy）。
