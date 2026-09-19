# R10 — 31b 验证手册（Wave3 验证阶段可直接执行）

Recon 代理 R10，2026-09-19。worktree `/home/kevin/project/worktrees/cpp-catalog-service`（分支 `feat/cpp-catalog-service`，git 状态干净，本次 recon 未改动任何 tracked 文件）。
本手册全部命令均在本机实测：g++/gcc 16.2.1、python3 3.14.6、40 核；无 cmake（CONV-31 既定口径：g++ 直连编译，sqlite3.c 以 C 单编）。
本次试跑产物全部在 `/tmp/pwb-31b-recon/`（build 脚本 + obj + 二进制 + 重生 oracle），worktree 未落任何产物。

---

## ① fixture 生成器扩展模式（31b 新生成器怎么写）

研读对象：`tools/oracle/generate_catalog_domain_fixtures.py`（359 行，单 commit e689e44c 冻结）。

### 1.1 现有生成器的解剖（31b 必须复刻的骨架）

- **真实 import 冻结**：`REPO = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(REPO))`，随后 import 全部被测真模块（`paleo_workbench.catalog.{audit,governance,impact,intermediate_policy,lineage_graph,model_gates,port_roles,queries,sources,tags,service,checksum,migration,explain}` + `paleo_workbench.catalog.models` + `paleo_workbench.project.models.ResourceItem`）。期望值全部来自真模块输出，无一硬编码。
- **场景构建 = 真服务 + 手搭文档**：`tempfile.mkdtemp(prefix="catalog-domain-oracle-")` 建临时工程目录 → 写空 `demo.paleo.json` → `py_service_mod.DataCatalogService.open(project, sweep_temp=False)` 真开服务 → 手搭 `CatalogDocument`（3 资产 / 5 版本 / 1 run / 1 tag）覆盖演进、外部缺失、悬空 parent、pin 等边界 → `service.document = doc; service._invalidate_maps()`。
- **确定性锚点**：`created_at` 全部字面量；migration 用 `now=lambda: next(stamp)` 注入时钟；仅有的两个随机段（见 1.3）在 replay 侧掩码。docstring 明言 "Ids and timestamps are frozen as-generated"。
- **冻结输出**：`json.dumps(oracle, ensure_ascii=False, indent=1, sort_keys=True)` → 写 `tests/cpp/data/fixtures/catalog_domain/oracle.json`（17204 字节，CJK 不转义）。
- **{ROOT} 占位**：`text.replace(str(tmp), "{ROOT}")`——一次性把场景临时目录的**所有**绝对路径出现替换为 `{ROOT}`（正斜杠原样，Linux 下无需归一化）。
- **节的组织**：顶层 dict，按子系统前缀分组：`governance_*`(4) / `artifact_policy_*`(3) / `port_roles_*`(1) / `model_gates`(1) / `checksum_*`(3) / `lineage_*`(3) / `impact_*`(5) / `v11_*`(7) / `queries_*`(2) / `sources_missing`(1) / `tags_*`(5) / `migration`(1) / `audit`(1) / `explain_ver_e4`(1)。**实测顶层 38 节**（台账 31-decisions D2 写 "37 节"，与冻结文件差 1——以文件为准；31b 写台账时点清实际节数）。
- **错误路径冻结**：`try/except ValueError` 把异常文本冻成字符串节（如 `governance_patch_reserved`、`lineage_bad_direction`），replay 侧做逐字 parity。
- **窥视 Python repr 形状**：`model_gates` 的 lookup_error 用例冻结的是 `str(KeyError(...))` 即带引号 repr（C++ 侧注释明示 `"'get_model failed: no row'"`）——31b 冻结任何异常文本前先确认它是不是被 repr 过。

### 1.2 31b 扩展模式结论：**新文件，不动 31 的生成器**

命名建议（任务书给定）：`tools/oracle/generate_catalog_service_fixtures.py`，输出 `tests/cpp/data/fixtures/catalog_service/oracle.json`。

理由：
1. **先例对称**：CONV-15 `generate_catalog_gc_fixtures.py` → `fixtures/catalog_gc/`、CONV-26 `generate_ingest_plan_fixtures.py` → `fixtures/ingest_plan/`——一个 replay target 一个生成器一个 fixture 目录。
2. **冻结物不可追加**：31 的 `oracle.json` 已被全绿的 `data.catalog_domain` 消费；往里加节等于强制重冻结已冻结产物（且引入 tags_add.id 等随机段的重掷风险），会把 31 的回归与 31b 的新面耦合。
3. **场景形态不同**：31 是"手搭 document + 纯决策面"；31b（service 深核/db/store）是 IO 驱动——`open` 流程、`batch_save`、DirtySet/`apply_changes`（db.py:1951）、14 个惰性读、manifest load（bak 回退/双损坏隔离，store.py:90 `CatalogStore`）、resolve_path 阶梯、working-copy 生命周期、模型注册表。需要一个**真实落盘的工程目录 + 真 sqlite**做场景，bootstrap 代码与 31 不同。
4. 若确需 31 已有的表（如 governance），在**新文件里重新冻结同值节**（oracle 自包含，C++ 测试一次只加载一个文件），不要交叉引用。

节名建议（沿用前缀分组法）：`service_open_*` / `batch_save_*` / `db_apply_changes_*` / `db_lazy_<读名>`（14 个惰性读逐个） / `manifest_load_*`（含 bak 回退、corrupt 隔离、双损坏） / `resolve_path_ladder` / `working_copy_*` / `model_registry_*` / `bundle_placement_*`。

### 1.3 随机 id 段两侧掩码规则（实测证据）

把 31 的生成器重定向 OUT 重跑一次（exec 源码 + 改 `g["OUT"]` 指向 /tmp，worktree 零改动），与提交版逐字节 diff——**全部差异仅 5 行、2 个随机 id**：

| 随机段 | 形态 | 出现节 | replay 掩码方式（catalog_domain_test.cpp 实测） |
|---|---|---|---|
| `tag_<12hex>` | `tags_add.id` | tags_add | C++ 侧从 expected `erase("id")`（单向丢弃；name/display 才是契约，L620-626） |
| `asset_<12hex>`（`../evil` 消毒 id） | migration 的 versions[].id/.asset、`ver_asset_<12hex>`、warnings[] 文本内嵌 | migration | **两侧**用 `std::regex("asset_[0-9a-f]+")` → `"asset_<generated>"`（regex 命中 `ver_asset_...` 的内嵌子串；warnings/versions/assets 的 expected 与 actual 都过一遍，L717-770） |
| `asset_name`（非 id 但同类） | explain_ver_e4 | explain | 两侧 erase（L824-828） |

31b 规则：**凡新生成 id/时间戳，要么注入时钟/显式传 id 消灭随机性，要么在 replay 两侧用同一 regex 掩码**；重生差异检查（本节 exec 技法）应作为冻结后的自证步骤。

---

## ② oracle.json 形状（抽样）

38 节，`indent=1, sort_keys=True, ensure_ascii=False`。值形态分五类：

1. **纯量表**：`checksum_file` / `checksum_file_streamed` / `checksum_text`（sha256 hex 串数组）；`lineage_bad_direction` / `governance_patch_reserved`（错误文本，中文原样）。
2. **行数组**：`governance_normalize`=[{key,value,ok,err?}×7]（ok=NormResult 或 null+err）；`model_gates`=[{case,ok,reason}×10]；`impact_downstream*`=[{version_id,direct,nearest[],reason,pinned,classification,reproducible,stage}]；`sources_missing`=[{version_id,relinkable,recorded_path,scanned}×5]。
3. **dict 表**：`artifact_policy_table`（kind→5 键行）、`lineage_summaries`（ver_id→{to_raw|null,broken,has_parents}）、`port_roles_display`（含空串键 `""`）、`tags_usage_names`（tag 名→[assets,versions] 计数对，CJK 键）。
4. **嵌套结构**：`lineage_chain_ver_e4`={node_count,truncated,root:{…,children:[]}}（递归树）；`v11_ports_for_run`={input:[7 键 RunPort],output:[]}；`migration`={migrated,skipped,warnings[],versions[],assets[]}；`audit`={checked,issues:[{kind,severity,ref_id,detail}],ok}；`explain_ver_e4`（VersionExplanation `__dict__` 直冻）。
5. **null 语义**：`to_raw: null`、`ok: null`+`err`——与"键缺失"是**类型级区别**（见 ③ 的 comparator）。

`{ROOT}` 共 **9 处**：5×`payload not found: {ROOT}/…`（audit）、`external payload not found: {ROOT}/gone.las`、`resource ../evil: file not found at {ROOT}/y`、`{ROOT}/data/old.sgy`（migration version path）、`{ROOT}/gone.las`（sources_missing recorded_path）、`{ROOT}/y`——**注意 {ROOT} 不仅出现在路径值，也出现在错误文本内部**；31b 冻结任何含路径的 detail 字符串时同样只需生成器末尾一次全局 replace。

---

## ③ replay 测试模板（提炼自 tests/cpp/data/catalog_domain_test.cpp，867 行）

### 3.1 骨架

- 头：`#include "compare_json.hpp"` + `"pwb_test.hpp"` + 被测面全部 `pwb/catalog/*.hpp`。
- 用例注册：`PWB_CASE(name)`（= `PWB_TEST(name)`，pwb_test.hpp 的 Registrar 自注册），共享 `test_main.cpp`（无缓冲 stdout——崩溃不吞 PASS 行；`run_all()` 末行打印 `N cases, M failures`，exit code = 有失败即 1；**N=0 不算过**，CMakeLists 头注释明示 "0 tests / all-skip never counts as pass"）。
- 断言宏：`PWB_TEST_ASSERT(cond,msg)` / `PWB_TEST_ASSERT_EQ(a,b,msg)` / `PWB_TEST_FAIL(msg)`。
- 初始化（每用例首行 `ensure_init()`，static once）：
  1. `getenv("PWB_DATA_FIXTURE_DIR")` → 否则 `fs::path(__FILE__).parent_path()/"fixtures"`（编译期 `PWB_DATA_FIXTURE_DIR` 宏只是 cmake 侧等价物；直连编译不定义也能跑）；
  2. `load_json(fixtures/"catalog_service"/"oracle.json")` 进全局 `g_oracle`；
  3. `mkdtemp("/tmp/catalog-service-replay-XXXXXX")` → `g_root`（每次进程运行独立）。
- 取节：`const domain::Json& o(const char* key) { return g_oracle.at(key); }`。
- {ROOT} 回填：`rooted(text)` 循环 `find("{ROOT}")` → `g_root.string()`；**对 expected 与 actual 都要过**（凡含路径的节）。
- 比对：`expect_json(section, actual, expected)` = `pwb_test::json_compare(expected, actual)` 有 diff 即 FAIL（diff 是 `$` 路径描述，直接进失败消息）。

### 3.2 comparator 语义（compare_json.hpp，31b 不得重造）

- object：键序无关，**键集必须全等**（缺键 ≠ null 键——Python 端 `Optional` None 冻结为 null，C++ 端缺省不得出现在树里）；
- array：**保序**逐元素；
- number：整数域跨符号比较（`int64` 值等即等，sqlite/JSON 往返翻 signed/unsigned 无害）；**int vs float 是类型差异**（1 ≠ 1.0）；
- string：UTF-8 逐字节。

### 3.3 replay 用例的标准形（13 用例的共性）

1. `build_document()`：与 Python 生成器**逐字面量镜像**地搭场景（id/stage/sha256(64 字符)/created_at/parent_version_ids/metadata.pin/run ports/tag 全一致）；b5 的 path 用 `(g_root/"gone.las")` 对应生成器的 `str(tmp/"gone.las")`。
2. 每个冻结节：调真 C++ API → 手工组装 actual `domain::Json`（键名/嵌套形状与冻结侧一一对应，注意 optional→null）→ `expect_json`。
3. 错误路径：`PWB_TEST_ASSERT_EQ(err.message, o("...").get<std::string>())` 逐字 parity（先确认 Python 冻的是 str 还是 repr）。
4. **行为面补充断言**（超出 replay 的不变量，31 有 4 处先例）：checksum 分块取消（cancel 谓词第 3 轮触发 → 必 error 且文案 `hash cancelled: <path>`）；tags 失败 save hook 回滚（doc.tags/asset_tags 计数复原）；relink fail-closed（同名陌生文件拒绝身份证明）；apply_run_ports 拒绝未知 version。31b 的对应面：DirtySet 只落脏行、batch_save 嵌套深度、manifest 双损坏 raise、ThreadSafeCatalogSession 并发不变量。
5. **negative_self_check**（收尾用例，模板）：重建一个 actual，然后 5 处独立篡改 expected，每处都必须让 `json_compare` 报 diff：
   - 值篡改（`to_raw=99`）、布尔翻转（`broken=false`）、**键删除**（`erase("has_parents")`）、**类型差异**（int→float `1.0`）、**多余键**（塞入 `ver_ghost`）。
   - 意义：证明 comparator 本身有检出力，replay 全绿不是恒真。
6. 已知边界（如实沿用）：31 的 `tags_rename` 节冻结了但 replay 只 assert ok（值经 `tags_usage_names` 间接覆盖）——31b 若有类似"只间接覆盖"的节，在测试注释里写明。

---

## ④ 已验证可复现的 g++ 直连命令（本次试跑结果）

### 4.1 源闭包（tests/cpp/data/CMakeLists.txt + libs/*/CMakeLists.txt 推导）

`data_catalog_domain` 链 `Pwb::Data Pwb::Catalog Pwb::Project Pwb::Workspace Pwb::Domain`，Catalog/Data 又带 `Pwb::Ingest`，共 **55 个 C++ TU + sqlite3.c**：

```
libs/domain/src/{ids,sha256,support}.cpp                      (3)
libs/project/src/{document,manager,paths,relocation,schema}.cpp (5)
libs/workspace/src/{mutations,state}.cpp                      (2)
libs/catalog/src/*.cpp                                        (22)
libs/ingest/src/*.cpp + libs/ingest/src/preview/*.cpp         (6+7)
libs/data_suite/src/*.cpp                                     (10)
tests/cpp/data/{catalog_domain_test,test_main}.cpp            (2)
```

include 目录（9 个）：六 lib 的 `include/` + `libs/data_suite/third_party`（nlohmann/json.hpp）+ `libs/data_suite/third_party/sqlite`（sqlite3.h）+ `tests/cpp/data`（pwb_test.hpp/compare_json.hpp）。

### 4.2 实测命令（/tmp/pwb-31b-recon/ 下，可原样重放）

```sh
W=/home/kevin/project/worktrees/cpp-catalog-service          # worktree 根
OUT=/tmp/pwb-31b-recon/obj; mkdir -p $OUT

# 1) sqlite3.c 以 C 单编（对齐 CMakeLists 的 -fvisibility=hidden）
gcc -c -O2 -fvisibility=hidden -I$W/libs/data_suite/third_party/sqlite \
    $W/libs/data_suite/third_party/sqlite/sqlite3.c -o $OUT/sqlite3.o

# 2) 每个 TU 一编（并行）；对象名必须路径镶嵌——闭包里有两个 models.cpp
#    (catalog/src vs ingest/src/preview)，按 basename 落盘会互相覆盖、链接缺符号
compile_one() {  # $1=源码路径
  rel=${1#"$W"/}; obj="$OUT/${rel//\//__}"; obj=${obj%.cpp}.o
  g++ -std=c++20 -O1 -Wall -Wextra \
      -I$W/libs/domain/include -I$W/libs/project/include \
      -I$W/libs/workspace/include -I$W/libs/catalog/include \
      -I$W/libs/ingest/include -I$W/libs/data_suite/include \
      -I$W/libs/data_suite/third_party -I$W/libs/data_suite/third_party/sqlite \
      -I$W/tests/cpp/data -c "$1" -o "$obj"
}
# 对 4.1 的 55 个源逐个调用（xargs -P $(nproc) -n1 亦可，注意嵌套引号——
# 用独立脚本文件承载 compile_one，勿塞进 xargs sh -c 内联串）

# 3) 链接（当前无 threading 面，未需 -pthread）
g++ -o /tmp/pwb-31b-recon/data_catalog_domain $OUT/*.o

# 4) 运行 ×2（fixture 定位走 __FILE__ 回退，无需设 env）
/tmp/pwb-31b-recon/data_catalog_domain && /tmp/pwb-31b-recon/data_catalog_domain
```

完整可执行版：`/tmp/pwb-31b-recon/build_catalog_domain.sh` + `compile_one.sh`（本手册附件，/tmp 可被清理，以本节为准重建）。

### 4.3 试跑结果与耗时（2026-09-19 实测）

| 步骤 | 命令 | 耗时 | 结果 |
|---|---|---|---|
| sqlite3.c | gcc -O2 | **41.8s**（单核） | 0 err，1 warning（strrchr const 丢弃，amalgamation 常态） |
| 55 C++ TU | g++ -std=c++20 -O1 -Wall -Wextra，xargs -P40 | **61s 墙钟 / 397s CPU** | 全部通过 |
| 链接 | g++ | 含于上 | 56 obj 全链通 |
| 运行 ×2 | ./data_catalog_domain | **11ms/次** | `13 cases, 0 failures`，exit 0，两遍全绿 |

警告口径：`-Wall -Wextra` 下共 148 条，分布 = project/schema.cpp 137（-Wmissing-field-initializers，存量）+ workspace/state.cpp 6 + ingest preview 3 + sqlite 1 + **catalog 仅 1**（legacy_migration.cpp 未用函数 py_repr）。**CMake 的 GCC 分支不额外加警告旗标（仅 MSVC /W4）**——CI parity 编译可以不带 -Wall；-Wall -Wextra 只作新 TU 卫生自查，不作为门槛。
另外：/tmp 存有 `catalog_asan`（109MB，2026-09-19 11:38，先前的直连 ASan 构建）——31b 新 TU 若要 ASan 复核属可选加练，非口径要求。

### 4.4 31b 专属注意

- `db.py` 的 `ThreadSafeCatalogSession` 若被 31b 测试触碰 → 编译+链接都要加 **-pthread**（本次闭包没用到所以没加）。
- 新 TU 落 `libs/catalog/src/` 即自动进闭包（`src/*.cpp` 通配），但 CMake 侧仍需显式 target_sources（见 ⑥）。
- 二进制与对象**只落 /tmp**，worktree 不落任何产物（本手册自身除外）。

---

## ⑤ ×2 口径在无 cmake 下的等价执行

- 有 cmake 的先例（台账为证）：`02-pr.md`/`03-pr.md`/`05-pr.md`/`07-pr.md`/`11-pr.md` 均记录 `ctest --test-dir build/conv-NN -R '<域>'  # ×2` + "两遍均绿/连续两遍全绿"——即同一测试选择器**连续跑两遍全绿**，不是两个不同选择器。
- 无 cmake 的等价（CONV-31 做法，31-decisions D2："13 用例全绿 ×2 …… g++ 16.2.1 直连编译驱动验证"）：**把链好的测试二进制连跑两遍**，两遍都满足 (a) 逐用例 PASS 行齐全 (b) 末行 `N cases, 0 failures` 且 N=实际用例数 (c) exit code 0。本次 ④ 已原样演示（两遍 13/13 绿）。
- 31b 记录格式建议：沿用 ledger 惯例，把两次运行的输出尾行各贴一遍并注明 "×2（两遍均绿）"；fixture 侧可加做 1.3 的重生差异检查（重生 oracle 与提交版 diff 仅含已知随机 id 段）作为 Python 侧的自证——这是 R10 本次验证过的增强，CONV-31 未记录，标注为可选。

---

## ⑥ 31b 新增验证面的挂载点（三处）

1. **`libs/catalog/CMakeLists.txt`**：文件尾部按 CONV-31 先例追加 `# BEGIN CONV-31B` … `# END CONV-31B` 块，`target_sources(pwb_catalog PRIVATE src/<新 TU>.cpp …)`——只加新 TU，不动既有 add_library 列表（CONV-15/26/31 三代先例）。sqlite 依赖、include、-fvisibility=hidden 均已在该文件就位，无需改。
2. **`tests/cpp/data/CMakeLists.txt`**：在 CONV-31 的 `pwb_data_test(data_catalog_domain …)`（现 L50）之后追加带 `# BEGIN CONV-31B` 标记的一行：
   `pwb_data_test(data_catalog_service catalog_service_test.cpp data.catalog_service)`
   （函数自动挂 test_main.cpp、五库链接、fixture 目录宏、TIMEOUT 300。）
3. **fixture 目录 + 生成器**：`tools/oracle/generate_catalog_service_fixtures.py`（新文件，见 ①）→ 冻结输出 `tests/cpp/data/fixtures/catalog_service/oracle.json`（新目录）；测试侧 `ensure_init` 用 `fixtures/"catalog_service"/"oracle.json"`。

验收清单（Wave3 直接勾）：生成器真实 import 跑通且重生差异仅已知随机段 → oracle 提交 → replay 测试 N 用例（N>0）全绿 ×2 → negative self-check 5 篡改全检出 → g++ 直连命令按 ④ 重放成功 → 两处 CMakeLists 挂载点就位（CI 侧可构建）。
