# CPP-B 测试计划（B0）

CTest 命名前缀 `data.`；0 tests / 全 skip / stub 输出不算通过。自定义轻量 harness
（`tests/cpp/data/pwb_test.hpp`：注册宏 + 断言 + 退出码），避免外部测试框架的网络依赖；
每个可执行文件一个 CTest 条目，长测试设 TIMEOUT。

## 1. Fixture corpus（固定、可再生成、带校验值）

`tests/cpp/data/fixtures/` 下由 Python oracle 生成（生成器 `tools/oracle/generate_fixtures.py`，
主仓 `.venv` 只读运行；产物入库，记录 `fixtures/manifest.json`：名称/来源/生成时间/关键计数/sha256）：

| fixture | 内容 | 覆盖 |
|---|---|---|
| `minimal` | 新建工程（meta+空节）+ 空 catalog | 默认值语义 |
| `typical` | 2 井/1 survey/域实体/entity_asset_links/2 resources（1 内 1 外部）/user_vector_layers(3 模板)/mapping_workspace(3 stage 全键+绑定 3 态)/map_qgis_project_xml 信封/joint_analysis/geo3d_workspace(含未知键) | 常规全字段 |
| `unicode_paths` | 中文工程名/中文资源路径/中文图层名 | Unicode + Windows 路径 |
| `legacy_abs_paths` | 资源/导出用绝对路径（external） | 迁移机器语义 |
| `future_schema` | schema_version=99 + 未知顶层节 | future 只读 + 未知节保留 |
| `catalog_full` | catalog.sqlite：多资产多版本/run+ports/members bundle/trash/working_copies/staging_leases/tags | SQLite 读侧 |
| `corrupt_json` / `corrupt_db` | 截断 JSON / 伪造坏 DB | 诊断不崩溃 |
| `missing_resource` | 引用不存在文件 | 丢失资源诊断 |

## 2. 用例矩阵 → Oracle 映射

| CTest 名 | 内容 | Oracle |
|---|---|---|
| `data.domain_ids` | 强类型 ID、安全段校验、时间 ISO | — |
| `data.project_roundtrip` | corpus 全部 .paleo 读→写→再读：语义 dump 与 Python oracle dump 一致；未知键（顶层/geo3d/metadata 嵌套）保留；字节级不要求（键序+缩进等价格化除外，见 §3） | O2 |
| `data.project_recovery` | .bak 恢复（中断保存/损坏 main/备份也坏 → 诚实失败）；恢复记录进 meta.last_recovery | O6 |
| `data.project_paths` | relativize/resolve/逃逸/UNC/盘符/Unicode；只读模式零写入（mtime+hash 前后比对） | O3/O6 |
| `data.workspace_codec` | membership/stage/binding 回落与往返；artifact_maturity 词表外丢弃；opacity null 剔除 | O2 |
| `data.catalog_read` | catalog_full 逐表读取 vs Python dump；一致性检查（孤儿/重复绑定/失效/缺资源/旧版本使用/run 状态） | O2/O3 |
| `data.catalog_write` | 临时库上：注册版本（path/hash/落盘布局）、upsert 保序、事务回滚 | O4 |
| `data.commit_coordinator` | 正常提交/重复 operation id 幂等/base 冲突拒绝/原版本不覆盖 | O4 |
| `data.commit_recovery` | journal 每阶段故障注入（fake storage）→ 恢复结论明确；真实 SQLite+文件系统崩溃窗口测试；原始资产 hash 不变 | O5 |
| `data.diagnostics` | corrupt_json/corrupt_db/future_schema/missing_resource：诊断 + 不崩溃 + 不静默修复 | O6 |
| `data.cli_inspect` / `data.cli_migrate` | 退出码契约（contracts §8）；migrate 拒绝覆盖输入副本以外的真实工程 | O7 |
| `data.oracle_compare` | 对 corpus 的 C++ dump 与 Python dump 语义比较（比较器见 §3） | O2 |
| `data.build_hygiene` | 链接依赖核验：不出现 Qt/QGIS/Python 符号 | O1 |

## 3. JSON 语义比较器规则（`tests/cpp/data/compare_json.hpp`）

- 对象：键序无关；**缺失键 ≠ null 键 ≠ 默认值键**（三方显式区分）。
- 数组：顺序保留，逐元素递归。
- 数值：int/int 与 float/float 按值；int vs float **类型不同即差异**（防过度 normalization）。
- 字符串：精确比较（UTF-8）。
- Python dump 端（`dump_fixture.py`）：`model_dump(mode="json")` 全量 + catalog 逐表行集；
  已知时间戳/uuid 类字段按 fixture manifest 校验值固定（生成时打桩 `_now_iso`/`uuid4`），
  使两侧可确定性比较。

## 4. 故障注入点（commit_recovery）

journal 阶段：`write_journal`→`stage_payload`→`catalog_commit`→`project_commit`→`rebind`→`complete`→`cleanup`。
fake storage 在指定阶段抛 `io_error`；恢复器重启后逐阶段验证：
可继续 → 幂等重放；不可继续 → 回滚并**列出**残留产物（staged 文件/新版本行/rebind 状态）。
另需真实 SQLite kill-window：在 `catalog_commit` 后、`project_commit` 前重开 → journal 驱动续走。

## 5. 明确不测（第一轮边界）

- QGIS XML 的渲染语义（信封原样字节即可）；算法数值；GC/dedup/impact 高级服务；
  多进程并发写目录（Python 侧 #411 语义由 stale-write 检测承载，本线实现同语义检测的单进程测试）。
