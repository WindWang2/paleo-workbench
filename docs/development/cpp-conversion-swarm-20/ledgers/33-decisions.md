# CONV-33 decisions — 契约冻结轮（轮1）裁决记录

Branch `feat/cpp-workflow-orchestration`（worktree `../worktrees/cpp-workflow-orchestration`）。
轮1 = 契约冻结：头文件签名桩 + CMake 预接线 + project 版本模型前置实装
（31b 轮1 同构：签名桩聚合 TU 零警告 + models DTO 实装 + CMake 块）。
轮2+ 的并行实现代理以本文档 + 六个冻结头为唯一契约，不得改签名；要改先回本表追加裁决。

## D1 — 落点裁决（修正 33-findings 初判，依据 = lib 依赖方向）

| 模块 | 落点 | 理由 |
|---|---|---|
| service.py / orchestrator.py / versioning.py | **libs/workflow_runtime**（非 findings 初判的 workflow_engine） | service 组合 runtime 本库的 freshness/recompute_plan；workflow_runtime PUBLIC 链接 workflow_engine（runtime → engine 单向），落 engine 会成环。orchestrator 依赖 service 的 infer_workflow_step_status + STEP_ORDER，随 service；versioning 编排 project 版本模型 + QualityReport + catalog best-effort 缝（catalog_seam.hpp 先例） |
| recipe.py | libs/workflow_engine（初判不变） | 唯二仓内依赖 = workflow_spec model + validation，已字节级对齐 |
| qc.py / map_qa_rules.py | libs/workflow_runtime（初判不变） | 收编 ui_review 手工 spatial_issues 对应面 |

新 TU 共 6：engine `recipe`；runtime `orchestrator/service/qc/map_qa_rules/versioning`。

## D2 — project 版本模型前置（实装，非桩）

`libs/project/version_models.{hpp,cpp}`（root CMake `target_sources` CONV-33 块，CONV-26 relocation 先例）：
WorkflowStep / CompilationRun / ContourSegment / ContourDraft / VersionSnapshot /
VersionSet / QualityReport 七 DTO + to_dict/from_dict。字段与键序逐字对
project/models.py（L78/105/330/340/390/408/429）；None 字段输出 null
（pydantic model_dump parity；domain/json.hpp 键序保真要求）。
workflow_runtime 因此新增 PUBLIC `Pwb::Project` 链接 + FATAL 守卫。

## D3 — 状态字符串不 enum 化

pending/running/complete/warning/failed/stale 等（含 CompilationRun/
VersionSet/ContourDraft 词表）冻结为 `inline constexpr std::string_view`
常量数组，类型用 std::string —— 状态串是跨模块隐式契约（service/
dashboard/QC UI/持久化 Json 直读），enum 会破坏 Json 对拍。词表常量
同时是轮2 实现与 oracle 断言的单一权威。

## D4 — 形参语义裁决

- orchestrator.next_step 的 step_payload（Python 接受但忽略，L81）→ C++ 省略。
- project 参数一律 Json seam（recompute_plan.hpp 先例：`.paleo.json` root /
  段视图，缺键 ≙ 空）；orchestrator 空 object ≙ Python
  ProjectDocument(meta=ProjectMeta(name="Default Project"))（状态推断只读
  证据段，语义等价）。
- 就地回写面（create_compilation_run / home_workflow_steps / run_basic_qc /
  run_map_qc / finalize_map_version）= `domain::Json&`；读侧面 = `const&`。

## D5 — id / 时间戳缝（oracle 确定性）

`project::ModelClock{NowIso, IdFactory}`（version_models.hpp）：
- default_now_iso = UTC 秒级 ISO-8601（无微秒）—— 对
  `datetime.now(timezone.utc).isoformat()` 的有界偏差；时间戳不参与科学
  指纹，oracle 冻结一律注入确定性实现。
- default_make_id = `<prefix>_<12 lowercase hex>`（uuid4().hex[:12] parity，
  随机源 thread_local mt19937_64）。
- from_dict 宽松回填（缺键/类型不符 → 字段默认）；pydantic 硬校验仍属
  document/schema.cpp 层，不在此重复。
- recipe 的 time.time() → `Clock = std::function<double()>`（store.hpp 先例）。

## D6 — CMake 门与测试预接线

- root `PWB_BUILD_CONV_33` 聚合门（implies CONV-26B + CONV-06；26B 自带
  DATA/MAPPING_KERNEL/07/08/25 级联）——**块序必须在 CONV-26B option 块
  之前**，否则 implies 失效（实测：晚于 26B 块时 MAPPING_KERNEL 不落、07
  块 FATAL）。无新 add_subdirectory：增量 TU 随宿主库门 = CONV-32 先例。
- 4 测试目标预接线（argv[1] fixture 模式，workflow_interpretation 先例）：
  `workflow_engine.recipe` / `workflow_runtime.qc` / `workflow_runtime.service`
  / `workflow_runtime.versioning`；骨架 main 如实打印 "round-2 wires the
  oracle replay"，fixture 由轮2 生成器落盘（generate_workflow_*
  _fixtures.py 命名已在骨架头注释绑定）。
- 验证边界升级（对 31/31b/32 披露的修正）：本机 cmake 实际可用
  （`source ~/pwb-sdks/env.sh`；QGIS 需 `-D PALEO_QGIS_{SOURCE,SDK,BUILD}_DIR`
  覆盖到 `/home/kevin/project/paleo-workbench`，UI-12 先例）。轮1 即真实
  configure + build + ctest，不再只有 g++ 直连。

## D7 — cartographic 双权威避免

map_qa_rules.cartographic_issues 是对 mapping.cartographic_qa（§14/V7）的
薄委托：C++ 冻结为 `CartographicQaDelegate` 注入缝，本头**不复述**
CARTOGRAPHIC_QA_RULES 常量——权威单点在 mapping 侧对应切片落地时提供。

## D8 — 桩策略（fail-loud，不伪造行为）

- 六个新 TU 的 .cpp = `throw std::logic_error("CONV-33 round-2 implements
  <symbol> (contract freeze stub)")`；定义参数匿名（形参名以头声明为准）。
- 数据契约常量（STEP_ORDER / REQUIRED_RESOURCE_TYPES / STEP_NAMES 中文 /
  BASIC+EXTENDED_QC_RULES / 六道门中文消息 / 跳过原因中文）在头文件
  constexpr 冻结，轮2 直接消费、不得改写。
- 唯一例外：orchestrator 构造（STEP_ORDER 常量拷贝）与只读访问器真实化
  ——纯数据搬运无行为语义。
- version_models.cpp 是实装（本切片"前置"交付物），不是桩。

## 验证记录（轮1）

- 聚合 TU（/tmp，含 7 新头 + 常量 static_assert 逐字断言 + 签名取址检查）：
  g++ -std=c++20 -Wall -Wextra -Werror 零警告。
- 7 个新 .cpp 同 flags 全部零警告（version_models 实装 + 6 桩）。
- 真实 CMake：`-DPWB_BUILD_CONV_33=ON` configure 过（implied 级联生效）；
  pwb_project / pwb_workflow_engine / pwb_workflow_runtime + 4 新测试目标
  构建过；ctest 9/9 = 新 4 + 宿主库既有 5（workflow_engine.run/store/
  receipt_plan_view/lifecycle + workflow_runtime.contracts）零回归。
- version_models 无既有消费者（唯一 include 方 = 本切片新头），回归面以
  engine/runtime 套件为界，如实声明。

## 已知风险移交（轮2 盯防，承接 33-findings §E）

1. home_workflow_steps 就地 mutation + broad except 降级 → 显式所有权 +
   catch 边界（#847-3 不得静默）。
2. 中文消息逐字：六道门/推进拒绝/OPERATION_LABELS_ZH 渗入面（常量已冻结
   在头，实现不得内联第二份）。
3. JSON 字节：recipe indent=1 ensure_ascii=False；versioning 指纹
   sort_keys+default=str 的 Python float repr；紧凑分隔符对拍。
4. 质心三级兜底链（facade → 顶点均值 → 无定位点）fail-open 语义。
5. qc domain_task_id 锚（#373/C15）与 register_qc_run 缝的临时文件 OUTPUT
   语义归属。
