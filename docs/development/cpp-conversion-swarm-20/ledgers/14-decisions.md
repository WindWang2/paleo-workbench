# 14-decisions — interchange 纯核（path_safety / manifest / preflight）

每个非显然选择记录：选项、决定、理由。编号 D14-n（前缀 14 防与其他 swarm 冲突）。

## D14-1 环境路径适配

任务书中的 `/home/kevin/.grok/skills/goal-loop/SKILL.md`、
`/home/kevin/projects/paleo_project/main` 在本机不存在。实际仓库
`/home/kevin/project/paleo-workbench`（origin/main `35987e13` 与任务书基线一致）。
goal-loop 协议按任务书 §0/§2/§8 内嵌条款执行；karpathy 准则读仓库自带的
`agent/skills/karpathy-guidelines/SKILL.md`（CLAUDE.md 指定路径）。worktree 建于
`/home/kevin/project/worktrees/cpp-conv-14-interchange`（与既有 conv-11/15 同级，
仓库外，不在 main 工作区内）。

## D14-2 移植范围（诚实清单）

任务唯一目标：path_safety + package 清单 + preflight 纯校验；用户流程验收 =
「拒绝路径穿越 + 写出与 Python 同构的 manifest JSON」。
**移植**：`safe_relative_path`、`check_collision`、`ensure_within_root`、
`sanitize_filename`、`is_reserved_or_unsafe`、常量与保留名/坏字符表；
`PackageEntry/PackageManifest`（to_dict/from_dict/dumps/entry_paths/
validate_paths）+ `write_manifest/read_manifest` 的纯校验链；
preflight 决策树（`ImportPreflightService.inspect` 的全部分支逻辑 +
`PreflightIssue/PreflightReport` + `plan` 的失败文案）。
**不移植（本切片）**：`safe_members/extract_archive`（需 zip 容器读取器，
Qt-free 核不引入 zip 库）；`os_replace_atomic`（Windows 过滤驱动重试策略是
OS 语义层，POSIX 无此问题；manifest 写盘用一次性 temp+rename 等价）；
`sniff_format` 及内容嗅探（文件内容 I/O）；全部 adapters 的重解析引擎
（geoviz/rasterio/segyio/GDAL/openpyxl/lasio）；builder/verifier/executor/
batch/delivery/dependency_audit（catalog 依赖与编排，属 M9 后续切片）。
不伪造、不半实现——这正是 v5 decisions D2 的「declared, never faked」。

## D14-3 `safe_relative_path` 返回类型

Python 返回 `PurePosixPath`，但全部下游只消费 `str(pure)` / `as_posix()` /
`parts`。C++ 返回 `std::string`（join 后的规范化相对路径），避免引入无人使用
的路径类（Karpathy：不为单处使用造抽象）。组件判定语义按 PurePosixPath 实现：
丢弃空段与 `"."`、折叠重复 `/`、丢尾部 `/`、保留 `".."` 交组件循环拒绝。

## D14-4 Unicode：生成表而非手写

NFC 判定/归一与 casefold 需要真实 Unicode 表。手写必错、抽样必漏。
决定：oracle 生成器从系统 python3 的 `unicodedata`（Unicode **16.0.0**，
与冻结 oracle 同源同版）导出：canonical 分解映射（Hangul 走公式不进表）、
canonical 组合对（含组合排除）、CCC 表、全量 casefold 逐码点映射
（Python str.casefold 用 full folding，非 1:1 也入表）→ 生成
`libs/interchange/src/unicode_tables.inc`。NFC 实现为标准三步
（规范分解 → CCC 稳定排序 → canonical 组合 + Hangul 公式），
`nfc_equals(s)` 即 `nfc_normalize(s) == s`。表由真实 Python 生成，
满足「不得手写 oracle 期望值」的同一纪律。版本漂移风险记入 findings。

## D14-5 Python `repr()` 仿真（错误文案逐字对账）

path_safety/manifest 的全部错误消息内嵌 `{x!r}`。为使 C++ 消息与 Python
逐字一致，实现 `python_repr(string)`：引号选择（含 `'` 无 `"` → 双引号，
否则单引号）；`\\`、`\n\r\t`；控制字符、DEL、C1 区间与 `\xa0`（<0x100
不可打印）→ `\xHH` 小写；Zs/Zl/Zp 分隔符（\u2000-\u200a、\u2028/9、
\u202f、\u205f、\u3000、\u1680）→ `\uXXXX`（非 BMP 用 `\UXXXXXXXX`）；
其余字符原样保留。**有界声明**：Cf/Co/Cn 类目按原样直通（Python 亦转义），
oracle 池不含这些类目（冻结范围=测试范围，findings 已记）。

## D14-6 manifest `dumps()` 字节对账

`json.dumps(to_dict(), ensure_ascii=False, indent=1)` ↔
`nlohmann::ordered_json::dump(1, ' ', false, …)`。两者键序（ordered_json）、
分隔（`: `）、非 ASCII 原样 UTF-8、控制字符转义规则一致；oracle 冻结含中文
entries 的完整 manifest 全文做字节比较。`read_manifest` 的 JSON 语法错误消息
**不逐字对账**（Python JSONDecodeError 与 nlohmann parse_error 文案不同源），
只冻结「抛错」事实；from_dict/validate_paths 层的消息逐字对账。

## D14-7 preflight：投影而非仿真

C++ 核不复制 rasterio/segyio 等解析器。`ImportPreflightService.inspect` 的
本质是**纯决策树**：输入 = 存在性/目录性 + SniffResult + 扩展名 + 适配器表
（format_id/extensions/import_data/notes）+ InspectionInput(ok/size/errors/
warnings)。C++ `Registry` 承载 `AdapterSpec` 投影；真实默认注册表
（13 适配器、扩展名、能力、注册序）由生成器从真实
`build_default_registry().capability_matrix()` 冻结进 oracle，C++ 测试装载
同一张表 → `adapter_for_extension` 优先级、format-unknown 判定与 Python 同源。
决策分支的 oracle 用 **stub 适配器驱动真实 Python `ImportPreflightService`**
（与仓库自有 pytest 的 fixture 风格一致：假适配器 + 真服务），冻结全部
report dict（path 用 `<PATH>` 哨兵，机器无关）。

## D14-8 oracle 生成与重放边界

`tools/oracle/generate_interchange_fixtures.py` 全部 import 真实模块
（`paleo_workbench.interchange.path_safety/package.manifest/preflight/
registry/adapters`），无手写期望值。`ensure_within_root` 场景冻结为
布局描述（目录/文件/symlink 拓扑 + candidate + 期望决策 inside/symlink/
escape + 相对余量），Python 侧在临时目录实跑后冻结，C++ 侧按同一布局
重建后重放（绝对路径机器相关，不冻结）。

## D14-9 测试目标命名

§8 要求 ctest 目标 `interchange.preflight`。单一测试可执行
`interchange.preflight`（`libs/interchange/interchange_tests/preflight_test.cpp`），
装载一份 `fixtures/interchange_oracle.json` 跑全部区段
（safe_path / collision / sanitize / within_root / manifest / preflight），
失败区段与案例 id 全量打印。不拆多目标（一个内核一份契约）。

## D14-10 CMake 接线

根 CMakeLists 追加 `# BEGIN CONV-14 … # END CONV-14` 块：
`option(PWB_BUILD_CONV_14 … OFF)` → `add_subdirectory(libs/interchange)`。
`libs/interchange` 链接 `Pwb::Domain`（ordered_json 约定 + 现成 alias），
因此 configure 需 `-DPWB_BUILD_DATA=ON`（与 mapping_kernel 同门槛，
任务书验证命令已含）。不改其他 CONV 块、不整理根文件。

## D14-11 `UnsafePathError` 的 C++ 类型

Python 是 `ValueError` 子类。C++ 定义
`struct UnsafePathError : std::runtime_error`（不映射 std::invalid_argument，
消息文本才是对账面；类型只需可 catch 且可区分于解析错误）。
manifest 的 `schema_version 必须是整数…` 是 ValueError 但**非** UnsafePathError
—— C++ 抛 `std::invalid_argument`，测试按消息对账并断言类型区别于
UnsafePathError（对应 verifier 的 except 分叉顺序）。

## D14-12 `check_collision` 的集合语义

Python 传可变集合原地登记。C++ 签名
`check_collision(const std::string&, std::set<std::string>& seen_casefold,
std::set<std::string>& seen_nfc)`，保持同一调用形状（manifest.validate_paths
与未来 verifier 复用同一对集合语义），不引入 CollisionTracker 类。
casefold 集合存折叠串、nfc 集合存原串——与 Python 逐语义同构。
