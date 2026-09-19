# CONV-33 实现轮 A3 — recipe（workflow_engine）移植记录

Branch `feat/cpp-workflow-orchestration`（worktree `worktrees/cpp-workflow-orchestration`）。
Python ground truth = `paleo_workbench/workflow/recipe.py`（326 行）；
契约 = 冻结头 `libs/workflow_engine/include/pwb/workflow_engine/recipe.hpp`
（签名/常量未改一字）；裁决 = 33-decisions D1/D5/D8 + 33-findings §A1/§E-3。

## 1. 范围表（交付物）

| 文件 | 状态 | 内容 |
|---|---|---|
| `libs/workflow_engine/src/recipe.cpp` | 轮1 桩 → 全量实装 | freeze_stub 全部替换；~1000 行 |
| `libs/workflow_engine/workflow_engine_tests/recipe_test.cpp` | 骨架 → oracle replay | 136 checks + 4 negative self-checks |
| `tools/oracle/generate_workflow_recipe_fixtures.py` | 新建 | 真 Python 冻结生成器（13 case 族） |
| `libs/workflow_engine/workflow_engine_tests/fixtures/workflow_recipe_oracle.json` | 新建（生成） | 32,794 字节；再生成逐字节确定（cmp 验证） |

实装符号：`RecipeDocument::to_dict/from_dict`、`structural_problems`、
`migrate_recipe`、`validate_recipe`、`save_recipe`、`load_recipe`、
`recipe_from_spec`、`recipe_from_run`、`clone_recipe`、`diff_recipes`、
`inspect_recipe`（+ 私有 `_slug`/CPython JSON 扫描器/repr 工具）。

## 2. 字节级格式结论（E-3）

- **save payload**：`json.dump(payload, fh, ensure_ascii=False, indent=1)`
  等价 = `Json.dump(1, ' ', false)`（nlohmann ordered_json）— 无尾换行。
  键序 = to_dict 插入序（`recipe_schema_version, recipe_id, name,
  description, created_at, source_run_id, tags, workflow`，Python L57-66
  逐字），嵌套 WorkflowSpec/SlotSpec/NodeSpec 键序由 CONV-06 to_dict 保证。
  空容器 `{}`/`[]` 紧凑输出、float（2.5 / 0.0 / 1712345678.5 型）与
  Python repr 一致（与 CONV-32 store 同一已验证路径）。c01 冻结了
  完整文件文本，C++ 逐字节断言通过。
- **原子写**：`.tmp-recipe-<pid>-<计数>` 前缀临时文件（store.cpp 先例，
  对应 mkstemp prefix=".tmp-"；随机后缀名不可见即可）+ `rename`；
  失败 unlink 后重抛。保存后目录无 tmp 残留（测试断言）。
- **`.json` 后缀强改**：`PurePath.suffix` 语义自实现（`.json` 点文件
  → 无后缀，不改写）；`stem + ".paleo-workflow.json"`；名字已以完整
  recipe 后缀结尾则不动。
- **repr 复现**：消息内 `repr()` 单引号、`\\` 加倍（UNC `'\\\\server\\
  share'` 冻结验证）、`\b \f \n \r \t` 字母转义、其余控制字符/0x7f →
  `\xNN`（小写十六进制）、UTF-8 字节直通；含 `'` 不含 `"` 时切换双引号。
- **em-dash**：绝对路径消息与 migrate 拒绝消息的 `—`（U+2014）逐字。

## 3. JSONDecodeError 细节复现（load 拒绝消息）

`f"recipe {path.name!r} is not valid JSON: {exc}"` 的 `{exc}` = CPython
`json.JSONDecodeError` 文本。选择**完整复现**（非仅前缀，超出 store 先例）：
recipe.cpp 内嵌 `_json.c` 扫描器镜像（先于 nlohmann 运行，仅产出错误
定位），消息类与位置规则（CPython 3.14 实测校准）：

- `Expecting value`（值位非法字面量/EOF；部分数字匹配 `01`→`0`、
  `5.`→`5` 留尾给分隔符检查）；
- `Expecting property name enclosed in double quotes`（对象键位非 `"`）；
- `Expecting ':' delimiter` / `Expecting ',' delimiter`；
- `Illegal trailing comma before end of object|array`（**位置 = 逗号下标**，
  3.13+ 措辞，非闭括号下标——实测校准点）；
- `Extra data`（顶层值后非空白尾料）；`Unterminated string starting at`
  （位置 = 起始引号）；`Invalid control character at`；
  `Invalid \escape`（反斜杠下标）/ `Invalid \uXXXX escape`（反斜杠+1）。
- 行列公式：`line = count('\n',0,pos)+1`，`col = pos - rfind('\n',0,pos)`
  （无换行 → pos+1）。

冻结 8 例损坏文件全消息逐字节通过；另做 55 例差分 fuzz（见 §5）。

## 4. 已知偏差（documented deviations）

1. **created_at 类型化**：冻结头 `optional<double>` — Python from_dict
   保留原始 JSON 值（int `1000` 回写仍是 `1000`；字符串原样）。C++ 数值
   读入 double（int 输入回写变 `1000.0`）；非数值读作缺省。oracle 不含
   该输入。`time.time()` 路径（save/clone/from_spec/from_run）始终 float，
   无差异。
2. **source_run_id / tags 元素类型化**：非字符串值 Python 原样携带，
   C++ str() 强转（frozen header string 类型约束）。oracle 不含。
3. **解析器接受集差**（CPython 收、nlohmann 拒，scanner 放行后落入
   nlohmann 措辞回退）：`NaN`/`Infinity` 字面量、**lone `\uD800`-`\uDFFF`
   代理对**、`5.` 型浮点无to_chars差异未观察到（01/5. 均由部分匹配规则
   覆盖）。55 例 fuzz 中唯一分歧 = lone surrogate（§5）。
4. **崩溃类错误 fail-closed**：非 dict 输入 / workflow 非 object /
   tags 非 list → `ws::ModelError`（Python 为 AttributeError/TypeError
   崩溃；类型不冻结，行为同为拒绝）。CONV-06 D5 先例。
5. **migrate 不就地变异**：Python `setdefault` 原地改 caller dict
   （c13 冻结快照即变异后视图）；冻结签名 `migrate_recipe(const Json&)`
   返回副本 — 测试显式重放"post-migrate 视图"对拍。
6. **`_slug` 非 ASCII**：字节级 ASCII lower + UTF-8 多字节整体归一为
   一个 `-`（对冻结语料与 Python 一致，如 `WF.Ünicode 2024` →
   `wf.-nicode-2024`）；Python `İ`（U+0130）lower 后含 ASCII 字母的
   Unicode 特例不复现。
7. **别名可变性**：Python `recipe_from_spec(spec)` 共享 workflow 引用
   （后续 parameters 变异会泄漏进 recipe）；C++ 值语义深拷贝。oracle
   生成器侧以 deepcopy 消除该别名对冻结的影响。

## 5. 验证记录

- **负向自检**（篡改后比较必须 FAIL，4 项）：c01 文件字节篡改
  （recipe_id→recipe_ld）；c04 冻结消息列号 column 2→3；c08 diff 删
  nodes_added 键；c05 setdefault 注入键序对调（仅键序比较器可捕获）。
- **差分 fuzz**（超出冻结语料，标准 g++ 直连驱动，未入库）：
  - `structural_problems` 20 例（Unicode 键/嵌套 falsy forbidden 值/
    repr 密集路径/混合列表）— 与真 Python 逐行 diff = 0。
  - 损坏 JSON 55 例（全部错误类 × 多行位置 × 数字边角 1e/1e+/01/5./.5/
    +1/-）— 唯一分歧 = lone `\uD800`（§4.3 已记录类）。
- **构建/测试**：`g++ -std=c++20 -Wall -Wextra -Werror -fPIC
  -fsyntax-only`（规定 include 集）= recipe.cpp 与 recipe_test.cpp 双 TU
  零警告；`/tmp/conv33-a3-build`（Ninja Debug，PWB_BUILD_CONV_33=ON，
  QGIS 三目录覆盖）`--target workflow_engine_recipe_test
  pwb_workflow_engine` 构建过；`ctest -R "workflow_engine\.recipe"` 两次
  全绿（0.05s/0.04s）。构建中 run_engine.cpp 有一既有 -Wunused-result
  警告（非本路由文件，不越界处理）。
- **fixture 确定性**：连续两次生成 `cmp` 逐字节相同（固定时钟/固定
  workflow/run id）。
- 测试计数：**136 checks + 4 negative self-checks**，13 case 族全过。

## 6. 冻结语料覆盖映射（case → Python 行为）

| case | 覆盖 |
|---|---|
| c01 | save/load 往返 + 文件字节 + 嵌套父目录 mkdir + tmp 无残留 |
| c02 | 禁键（str 值/非 str 值递归/键归一化 " ApiKey "→apikey/列表下标）+ validate_recipe（registry 面） |
| c03 | 绝对路径（posix/UNC/盘符正反斜杠/$ 豁免原始值判定/strip 后匹配原始 repr） |
| c04 | 损坏 JSON 8 例全消息（含多行 line 3 col 13） |
| c05 | migrate v1 恒等 + workflow/schema_version 注入（键序=尾部追加）+ 未知版本 fail-closed（1.1 / float 2.0 / null→"None"） |
| c06 | 后缀强改 5 例（含 dot.name.json、已带后缀、.txt、无后缀） |
| c07 | clone（默认/custom id/空串 id 回退/空 name 回退 workflow.name/source_run_id 清空/深拷贝独立） |
| c08 | diff（节点增删改+排序字段表/槽增删改/max_concurrency 对/逆序/空 diff） |
| c09 | inspect 形状（nodes 无 parameters） |
| c10 | recipe_from_run 槽位默认提升（在 slot_values 中→default；不在→原样；多余 slot 值丢弃）+ lineage |
| c11 | recipe_from_spec（slug/unicode slug/custom/空 id/description 回退/时钟注入） |
| c12 | 拒绝门（save 结构门未写盘/registry 门/无 registry 放行/load 缺失/load 结构门） |
| c13 | from_dict 强转（name→workflow.name、tags→()、created_at→None、schema_version 默认、migrate 注入视图） |
