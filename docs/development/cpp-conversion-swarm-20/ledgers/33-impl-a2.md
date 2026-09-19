# CONV-33 impl A2 — workflow/versioning.py 移植（轮2，route A2）

Branch `feat/cpp-workflow-orchestration`（worktree `cpp-workflow-orchestration`）。
契约 = 33-decisions D1-D8 + 冻结头 `libs/workflow_runtime/include/pwb/workflow_runtime/versioning.hpp`
（六道门消息 constexpr 逐字消费，未改写）+ `libs/project/include/pwb/project/version_models.hpp`
（前置 DTO 实装，只消费未改）。

## 范围表

| 文件 | 角色 |
|---|---|
| `libs/workflow_runtime/src/versioning.cpp` | freeze_stub 替换为全量实装：build_snapshot / finalize_map_version / active_final_snapshot / version_set_summary + 指纹字节编码器 + 测试缝 `versioning_fingerprint_raw_bytes` |
| `libs/workflow_runtime/workflow_runtime_tests/versioning_test.cpp` | 轮1 骨架替换为冻结 oracle replay（argv[1] fixture；27 例 + 2 sink 检查 + 5 负向自检） |
| `tools/oracle/generate_workflow_versioning_fixtures.py` | 新生成器，import 真实 `paleo_workbench.workflow.versioning` + `project.models` |
| `libs/workflow_runtime/workflow_runtime_tests/fixtures/workflow_versioning_oracle.json` | 生成冻结（211,137 字节，27 例，6 raise，重跑字节一致 ×2 验证） |

## 指纹字节格式结论（本切片核心发现）

Python `json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)`
**无 indent 时 DEFAULT 分隔符是 `(", ", ": ")`** —— 与 constraint_versions /
workflow_spec canonical_hash 的 `separators=(",", ":")` 紧凑格式**不同**。
冻结样例（fixture `fingerprint_bytes_rich`）：

```
{"facies": [{"alpha": 2.5, "nested": {"k1": {"a": null, "b": true}, "k2": [0.5]}, "zeta": 1}, ...], "horizon": "H1", "id": "map_fix1", "labels": [...], "lines": [...], "wells": [...]}
```

- 键排序在**每一层**生效（sort_keys 递归）；UTF-8 字节序 = Python 码点序。
- float = Python repr（复用 `factor_host::python_repr_double`：最短往返、
  `1e+16` / `1.5e-05` / `-0.0` / `5e-324` 全部在 fixture 里冻结对拍）；
  int 与 float 类型不折叠（`0` vs `0.0`）。
- ensure_ascii=False：中文原样 UTF-8；`"`/`\`/C0 控制字符转义
  （`\b\f\n\r\t` 短形式优先，其余 `\u00xx` 小写）。
- `default=str` 在 Json seam 下**永不触发**（文档视图值已全 JSON 原生）。
- 实现为本地递归编码器（nlohmann dump 无 "仅分隔符加空格" 模式，不可用）；
  顶层 payload = {facies, horizon, id, labels, lines, wells}（wells/labels/lines
  原样透传，嵌套键由编码器排序）。
- 字节级断言缝：`pwb::workflow_runtime::versioning_fingerprint_raw_bytes(map_doc)`
  定义在 versioning.cpp、仅在测试中声明（不进冻结头）；测试对冻结 `raw`
  逐字节比较 + C++ `domain::Sha256` 重哈希对拍 `fingerprint`。

## 时钟缝（D5）与调用顺序

pydantic default_factory 按**字段声明序**触发（探针实证）。fresh-set finalize
的完整序列（fixture 冻结为计数器值，C++ `OracleClock` 按 per-case
`clock = {id_consumed, now_consumed}` 种子复现）：

```
make_id("vset") → now(created_at) → now(updated_at)          # VersionSet 构造
→ make_id("vsnap") → now(created_at)                          # build_snapshot
→ now(finalized_at) → now(updated_at)                         # 定稿盖章
→ now(draft.updated_at) → now(run.updated_at)                 # 联动（各一次）
```

existing-open-set 复用路径无 vset 构造三连；supersede 每命中一集一次 now
（先于 find/create）。

## oracle 确定性手法（供后续切片复用）

- `_id` 是 lambda 工厂 → 打 `project.models._id` 模块属性即达模型构造。
- `_now_iso` 是**直接函数绑定**进 FieldInfo → 模块属性 patch 不达；须
  `model_fields[*].default_factory = fake + model_rebuild(force=True)`
  （本生成器对模块内全部 BaseModel 通用循环，重建 8 个模型）。
- `versioning.py` 顶层 `from ... import _now_iso` 是独立绑定 → 还需单独
  patch `paleo_workbench.workflow.versioning._now_iso`。
- 输入侧全显式 id/时间戳 → per-case 种子恒 {0,0}（仍如实记录 `clock`）。
- 生成器内建自检：指纹 replica 与真实 content_fingerprint 逐一断言相等；
  `get_catalog() is None` 断言（sink 路径 = nullptr skip 的冻结前提）。

## 偏差（均无行为影响）

1. `str.lower()` → ASCII tolower：状态词表全 ASCII（error/failed/critical）。
2. Json seam 容错：缺 section ≙ 空表；null/缺标量 ≙ 模型默认。模型 dump
   永远全键在场，fixture 走主路径；越界输入 Python 本就不可表达。
3. `finalize` 中 map_doc 取 `Json` 拷贝视图（Python 持模型对象的读稳定性
   等价物）；vset 以元素指针就地改写。
4. Python 广义 `except Exception` → C++ `catch (...)`，同样不重抛
   （L189-203 语义）；无日志面（_log.debug 对应物缺省，行为等价）。
5. 手册 g++ 直连检查需追加 `-Ilibs/factor_host/include`（canonical_json.hpp
   依赖；与 constraint_versions.cpp 同一先例，任务给定清单未列，真实 CMake
   构建由库目标导出覆盖）。

## 负向自检清单（comparator 必须能失败）

| 案例 | 篡改点 |
|---|---|
| finalize_happy_fresh_set | `version_set/status`: final → open |
| finalize_gate_qc_failed_status | `raise/message`: status=Error → status=passed |
| finalize_supersede_chain | `steps/1/version_set/snapshots/0/map_document_id` → map_tampered |
| fingerprint_bytes_rich | `raw` → 紧凑格式串（同时钉死 spaced≠compact） |
| dto_roundtrip_models | `dumps/0/finalized_at` → 1999-01-01 |

## 测试与验证

- fixture 27 例：build_snapshot ×3（rich / 无 qc 无 draft / 空 horizon 全任务）、
  finalize ×10（happy / supersede 双步链 / 六门拒绝 / production:0 整数不触发
  strict-False 门 / require_qc_pass 通过(无 run 无 draft) / 既有 open 集复用 +
  多集 supersede + 异层位 final 不动）、active_final_snapshot ×7（末 final /
  层位命中 active-id≠末位 / 未命中 / 空 active 末位回退 / 悬挂 active-id 末位
  回退 / final 空快照 / 空工程）、version_set_summary ×2、DTO roundtrip ×1
  （五模型 None→null/键集）、fingerprint 字节 ×3。
- 运行输出：`ALL 29 CHECKS PASSED (+5 negative self-checks)`
  （27 fixture 例 + 2 C++ 本地 sink 检查：throwing sink 定稿不失败且状态与
  冻结期望全等；recording sink 恰一次调用且参数组合 = snapshot|operator|note|vset_id）。
- 门消息复核：6 条冻结 raise 中 4 条逐字命中头常量；2 条组合消息
  （unknown-map 前缀+id、qc status 前缀+原样 status+后缀）按头注释分解验证。
- 构建/测试：`/tmp/conv33-a2-build`（PWB_BUILD_CONV_33=ON）
  `cmake --build --target workflow_runtime_versioning_test pwb_workflow_runtime` 过
  （一次 A3 并发 service.cpp 中间态失败，等待后重建过 — 非本路由文件）；
  `ctest -R "workflow_runtime\.versioning"` 两遍 100% 通过。
- g++ -std=c++20 -Wall -Wextra -Werror -fPIC -fsyntax-only：versioning.cpp 与
  versioning_test.cpp 均零警告（含 factor_host include）。
- 生成器重跑字节一致（diff ×2）；未触碰所有权外文件
  （git status 其余改动属 A1/A3/A4）。
