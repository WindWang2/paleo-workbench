# CONV-31 findings — catalog 域核（35 文件 scope ledger）

Branch `feat/cpp-catalog`（worktree `../worktrees/cpp-catalog`，base origin/main 5a6373bd）。
巨文件差距明细见 `31-gap-analysis-big.md`（db/service/service_v11/adapter/lifecycle/audit/storage/store 逐行号差距）。
cmake 在本机不可用：验证边界 = g++ -std=c++20 直连编译测试驱动 + 真实 Python oracle replay（任务书 §3 预案；先例 curve_ops 304 用例）。CMakeLists 仍按仓库惯例更新供 CI。

## A. 终态三列（Python source → 语义要点 → C++ 目标）

### A1. 本切片移植（新增 C++，oracle 冻结 + replay）

| Python | 语义要点 | C++ 目标（libs/catalog） |
|---|---|---|
| types.py (310) | DataVersionRef/DataRunRef/LineageEdge DTO + to_dict/from_dict + stage 强转 + IntegrityStatus 枚举 | include/pwb/catalog/refs.hpp + src/refs.cpp（JSON codec 逐键 parity） |
| view.py (77) | version_display_payload 20 键显示契约 + integrity 标签 | refs.cpp `version_display_payload`（经 document_index 组装） |
| checksum.py (59) | 1MiB 分块 sha256 + 每 chunk cancel 轮询（不返回部分摘要）+ sha256_file_or_none + 文本 CRLF→LF 规范化 | checksum.hpp/cpp |
| model_gates.py (59) | 生产晋级门：demo_only/受控 provider/model_type 黑名单（casefold 等价类）+ scientific=False 双层 + require_input_schema 容忍读路径 | policies.hpp/cpp `can_promote_to_production`（模型/版本事实以结构体注入，服务依赖倒置） |
| governance.py (227) | 6 治理字段 + 受控词表 + 别名归一（中英文）+ 200 字符自由文本截断 + 保留键拒绝 + 显示行 | policies.hpp/cpp governance 命名空间 |
| intermediate_policy.py (127) | 产物 kind→(must_register, stage, retention) 决策表 + 未知 kind INTERMEDIATE 兜底 + rationale 文案 | policies.hpp/cpp `artifact_policy` |
| port_roles.py (82) | 34 端口角色常量 + 中文 display 注册表 + 未知角色 verbatim | policies.hpp/cpp `port_roles` |
| telemetry.py (91) | events.jsonl 追加（sort_keys、ensure_ascii=False）+ 撕裂行跳过 + filter/tail 读取 + best-effort | telemetry.hpp/cpp |
| lineage_graph.py (252) | ancestors/descendants BFS 链（cycle-safe、max_depth/max_nodes 截断如实标注）+ compute_summaries（迭代 DFS 备忘录、broken/has_parents/to_raw） | document_index.hpp/cpp + lineage_graph.hpp/cpp |
| impact.py (523) | downstream_stale（触发集=非 current 版本+trashed；最近变更祖先 BFS；pinned 分类；节点预算截断标注）+ upstream_impact 闭包 + delete_impact（断边计数/级联建议文案）+ is_stale + 实体域（links 注入） | impact.hpp/cpp（LRU 结果缓存按 Python 语义移植：revision+serial 键） |
| explain.py (192) | VersionExplanation 组装（producing run/typed ports/下游闭包/删除资格/staleness/pin）+ explain_asset 汇总 | explain.hpp/cpp（project 实体上下文经注入 links，缺省降级） |
| sources.py (247) | find_missing_sources（stat-only、probe 仅第一梯）+ relink_external_source（fail-closed：sha256 强证明 → stat 指纹；托管/非 RAW 拒绝文案逐字）+ relink_history | sources.hpp/cpp |
| queries.py (220) | verify_integrity（missing/unknown/verified/modified + cancel）+ search_assets 文档扫描路径（NFKC 折叠按 entity_view.hpp D6 边界：ASCII 折叠）+ find_assets_by_tag | queries.hpp/cpp |
| tags.py (583) | _TagJournal 惰性回滚日志 + add/remove/rename(merge|error)/merge/bulk_*/delete_unused/prune + display_name 规范 | tags.hpp/cpp（事务钩子经接口注入，语义逐分支 parity） |
| migration.py (254) | ResourceItem→catalog 投影（幂等、id 复用、unsafe id 消毒、stat 指纹回填 #1221、managed=False 不变量 #396/C34） | legacy_migration.hpp/cpp（输入 = .paleo.json resources[] JSON 行） |
| legacy_projection.py (93) | bridge id 规则 + 按 id 集 remove（resources+export_artifacts）+ 幂等 upsert | legacy_migration.hpp/cpp `legacy_projection` 命名空间 |
| audit.py (696) | 17 类结构审计（severity 体系、blockers、cancel）| audit.hpp/cpp（与 repository.cpp 现有 audit_catalog 子集合并；保留旧入口兼容） |
| service_v11.py (782) | 语义核：_apply_run_ports（ports⊆flat 不变量+ordinal 排序）+ pin/unpin + retention_class + cleanup_eligibility + lifecycle_status + bundle 成员放置编排 | v11_policy.hpp/cpp（纯决策面；DB 序列化走 repository 既有行） |
| storage.py (644) | 剩余面：trash_payload/restore_payload/purge_trashed_payload + safe_unlink + is_cas_path + create_working_copy 布局 | trash.hpp/cpp（dedup.hpp 已覆盖 blob/place_managed_file；本切片补 trash 生命周期） |
| store.py (229) | load 侧：.bak 回退、corrupt 隔离、双损坏 raise | **未做→31b**（见 A3/D6：本切片收敛于 20 个策略/图/查询面，manifest load 延后） |

### A2. 已移植（此前切片，本切片核对语义并引用为证）

| Python | 证据 |
|---|---|
| models.py | models.hpp（DataAsset/DataVersion/DataRun/Tag/WorkingCopy/aggregate_member_sha256；normalize_tag_name 在 entity_view.hpp） |
| db.py（子集） | repository.hpp（v5 健康/整文档加载/rowid 保序 upsert/事务+revision/5 个领域事务）+ paged_sql.hpp（_search_assets_page/_count_assets）+ sqlite.hpp |
| storage.py（子集） | dedup.hpp（blob 全套/place_managed_file/扫描/指标） |
| gc.py | gc.hpp（plan/sweep/working-copy 清理/lease cutoff） |
| dedup.py | dedup.hpp/cpp |
| entity_views.py（分页子集） | entity_view.hpp（20 键行/游标/过滤）+ paged_sql.hpp |

### A3. 如实不移植/退役（理由 + 边界）

| Python | 终态 | 理由 |
|---|---|---|
| runtime.py (122) | 不移植 | Python 进程级 DI（env var 动态 import、模块级单例）。C++ 侧组合根在 AppContext，库消费者直接持有 repository/service；无等价运行时解析需求。 |
| port.py (229) | 不移植（协议文档化） | Protocol seam 为 Python 业务模块服务；C++ 域内以强类型 API 为 port。其行为契约（幂等资产身份/rerun 新版本）已在 repository 事务语义中体现。 |
| adapter.py (903) | 拆解 | 三大行为语义：三级 dedup 快路径已在 place_managed_file（内容证明）；legacy 桥一次绑定 + domain-task 资产复用属 Python 注册流（ui/project_controller 驱动），随 CONV-44/45 消费方切片评估。其余为 Python 对象模型转换胶水。 |
| view.py/service_view.py | 部分移植 | version_display_payload → refs.cpp；service_view 的 RunProxy 属性投影 = C++ 直接读 DataRun 字段（DataRun.parameters["_domain_task_id"] 语义在 refs/service 面保留），无独立移植价值。 |
| lifecycle.py (1141) | 不移植 | 业务域操作→Port 调用翻译层，绑定 Python 域模型（FactorMapTask 等），消费方是 Python UI/管线（M10 保留 Python）。C++ 等价物由 CONV-32/33 workflow 域切片按域重建，不逐行搬翻译层。 |
| grid_artifact.py (213) | 不移植（Python 边界） | numpy NPZ 私有格式读写；C++ 侧消费因子格网走既有 mapping/science C++ 面（CONV-37/38 域），跨语言经 interchange。 |
| domain_binding.py (796) | 不移植（解析器边界） | import geoviz Python 包（SMI DAT/XML 井头解析、SEG-Y survey 角点）；绑定簿记消费方为 Python 导入管线。C++ 导入链在 CONV-42 resources 切片统一评估。 |
| edit_session.py (258) | 不移植（本轮） | 依赖 service.py working-copy 生命周期面（create/commit_bundle_working_copy）尚无 C++ 对应（见 31b 遗留清单）；且消费方是 Python 工作台 GUI（M10）。 |
| entity_views.py（well/survey 视图） | 遗留至 CONV-44 | 依赖 project.domain typed 实体链接模型（Pwb::Project 现为 JSON 树视图，无 typed links）；分页子集已移植（上表）。 |
| service.py 剩余 / db.py 剩余 | **31b 子切片**（decisions D6） | open 流程/_CatalogMaps 维护索引/batch_save/模型注册表/working-copy 生命周期/resolve_path 阶梯/apply_changes+DirtySet 通用通道/14 惰性读。本切片交付 document_index（maps 的 C++ 等价物）+ 上述 20 文件；深核拆 31b。 |

## B. 共享/冲突文件

- `libs/catalog/CMakeLists.txt`：CONV-31 以 `# BEGIN CONV-31` 块追加 target_sources（先例 CONV-15/26），不动既有列表。
- `tests/cpp/data/CMakeLists.txt`：追加 `data.catalog_domain` 一行。
- `repository.cpp`：新增 `load_manifest`（store.py load parity），不动既有导出。
- 无 ui/、无 QGIS、无 Qt 依赖（全部 Qt-free core）。

## C. 验证口径

- oracle：`tools/oracle/generate_catalog_domain_fixtures.py` 真实 import 冻结 → `tests/cpp/data/fixtures/catalog_domain/oracle.json`；C++ replay 全表 + negative self-check（篡改检出）。
- 行为面（cancel/回滚）：多线程/失败注入用例与 Python 用例一一对应（checksum cancel、tags 回滚、telemetry 撕裂行）。
- 本机 g++ 16.2.1 直连编译运行（无 cmake，如实披露；CI 由 CMakeLists 覆盖）。
