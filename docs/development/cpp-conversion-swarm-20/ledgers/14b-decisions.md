# 14b-decisions — interchange archive/OS/container/adapters（CONV-14 续作）

伴随 14b-findings.md。D14b-1..n 记录移植中的语义决策与偏差；每条含理由与
影响面。三轮 review（A parity / B 质量 / C 闭环）结论回写于文末。

## D14b-1 ZIP 容器自研，deflate 用系统 zlib（不引入 minizip/Qt/Python）
`libs/interchange/src/zip_archive.cpp` 手写 EOCD/central directory/local
header 读写；压缩体走 zlib raw deflate（windowBits=-15，与 CPython
`zipfile` 的 compressobj(-15) 一致）。读端理解 ZIP64（EOCD locator +
extra 0x0001），写端不发 ZIP64：条目数 >65535 或单条目/容器 ≥4GiB 报
`ZipError`（中等规模上限，任务书排除 100G 体量）。理由：任务书「Native
ZIP/archive」+「C++ 主链不得依赖 Python」；仓库无现成 zip 内核可复用。

## D14b-2 created_at 以 provider seam 冻结（等价 Python monkeypatch）
Python builder 读 `datetime.now(timezone.utc).isoformat()`，oracle 用
`builder_mod.datetime = _FixedDateTime` 定格；C++ PackageBuilder 提供
`set_created_at_provider`（默认 `pwb::domain::now_iso8601`，六位微秒
+00:00，与 Python isoformat 字节一致）。manifest 其余字段、dumps() 字节
布局沿用 CONV-14 已冻结实现。

## D14b-3 应用版本显式注入
Python 读包内 `paleo_workbench.__version__`；C++ PackageBuilder 构造参数
`application_version` 注入（kernel 保持 Python-free），测试取 oracle
`meta.package_version` 回放。

## D14b-4 catalog 以 CatalogSource 抽象 seam 承载，sqlite 服务不进本切片
builder 消费 `list_assets / list_versions / resolve_path / export_manifest /
list_runs` 五个调用（真实 Python catalog 服务的窄面）；resolve_path 异常时
回落 `project_dir/version.path`（与 Python 一致）；provenance 段任何 catalog
异常静默返回空（与 Python `except Exception: return` 一致）。oracle 用
StubCatalog 驱动真实 PackageBuilder（conv-14 R4 的「stub 驱动真实服务」
模式）。C++ libs/catalog 尚无该表面，接口就位后由 sqlite 实现接入。

## D14b-5 解释器相关错误尾巴只冻前缀
`json.JSONDecodeError` 文本、`OSError` strerror 尾巴（含 `[Errno 2]`）不可
跨实现复现：oracle 冻结 severity/code + 稳定中文前缀（corrupt-manifest /
corrupt-project / corrupt-catalog）或整条 summary + prefix 标记
（inspect_missing_file），C++ 断言前缀（`message_prefix_match`，按第一个
": " 截断）。其余全部逐字节对比。

## D14b-6 路径相对化必须纯词法（lexically_relative）
 pathlib `Path.relative_to` 是纯词法；`std::filesystem::relative` 会
weakly_canonical 解析 symlink——对包内 symlink 条目会解析到包外目标，把
「未知符号链接: sneaky.bin」错报成 `../../../etc/hostname`（review 轮 0 的
实测失败）。全部 rel 计算统一 `lexically_relative`；排序用
`PathPartsLess`（Python sorted(Path) 的 parts 元组序，"a/b" < "a.txt"）。

## D14b-7 Python float()/int() 语法覆盖面
model adapter 的数字解析实现 Python 语义：正负号、下划线仅允许夹在数字间
（`1_0` 合法、`1__0`/`_1`/`1_` 非法）、`inf/infinity/nan` 大小写不敏感、
十六进制浮点拒绝、`strtod` 全消费校验。已知偏差（记录不修）：CPython
`int()`/`float()` 接受全角 Nd 数字（如 "１２３"），frozen corpus 不含该类
输入，C++ 拒绝；巨整数溢出路径 C++ 报 invalid_argument 而 Python 分
OverflowError——两者均为响亮失败，不产生静默分歧。

## D14b-8 写器字节复用 CONV-22（严禁复制）
export_data 通过 `pwb::geomodel::legacy_export_to_flac3d/abaqus` 取得与
Python 逐字节一致的产物（CONV-22 已冻结 %%.4f 格式与 C3D8/B8 面循环节点
序），经 AtomicOutputFile 落盘。oracle `export_data_flac3d` 再冻一次产物
sha256 作回归锚。geomodel 缺席时（纯 CONV-14 旧消费者如 CONV-21 预测切片）
`model_adapters.cpp/service.cpp` 不参与编译（CMake `target_sources` 仅在
`TARGET Pwb::GeoModel` 时加入，archive 测试目标同门），path-safety/manifest/
preflight 内核照常可用；该配置已双树实证（CONV_21=ON 无 geomodel 25/25、
CONV_22+CONV_14 全量 26/26）。

## D14b-9 写端确定性策略
ZipWriter 固定 date_time=(1980,1,1,0,0,0)、目录序 parts 元组序、非 ASCII
名置 UTF-8 flag 0x800（CPython 规则）、external_attr=regular 0644。
deflate 字节不跨 zlib 版本复现 → oracle 锚 CRC32 + 大小 + 内容 sha256
（CRC 是规范常量），不锚压缩字节。

## D14b-10 读端有界与炸弹护栏
逐条目流式（1MiB 块），inflate 输出超 central directory 声明 size 即
`ZipError("...exceeds declared...")`（强于 Python ZipExtFile 的读上限等价
面）；CRC 与 CD 不符报 `Bad CRC-32 for file <repr>`（CPython 同文案）。
extract_archive 先全量 safe_members 再写任何字节；cancel checkpoint 逐条目
（Python 无 cancel——本切片新增 seam，不改语义）。

## D14b-11 atomic 语义
`os_replace_atomic`：POSIX 单次 rename（瞬时失败即真错误）+ 父目录 fsync
（best-effort，Python 吞 OSError 同）；Windows 10 次 MoveFileExW 指数退避
（0.05·2^min(i,6)s，Python 策略同参数），最终失败抛
"atomic replace of <target> kept failing after retries: ..."。
`AtomicOutputFile`（resources/exporters.atomic_output 的 RAII 化）：mkstemp
语义（O_EXCL、0600、8 位 [a-z0-9_] 随机、保留目标后缀），commit 走
os_replace_atomic，未 commit 析构即清理——失败导出零残留。

## D14b-12 delivery/executor/batch/dependency_audit 显式归类不移植
交付配置层（DeliveryProfile/DeliveryService/DeliveryReportBuilder +
dependency_audit）依赖 C++ catalog service 与 UI 编排，本切片只承载其
已冻结的底层件（KNOWN_PACKAGE_EXTRA_FILES、报告写盘的
os_replace_atomic 模式）。归类 Python-only（removal-candidate：catalog
C++ service 落地后随编排层一起移植）。executor/batch 同理。

## D14b-13 根 CMakeLists 零改动
PWB_BUILD_CONV_14 块已存在；新文件、ZLIB 依赖、GeoModel 条件依赖全部收在
libs/interchange/CMakeLists.txt 内，规避并行 worktree 对根文件的写冲突。
find_package(ZLIB REQUIRED) 为系统库硬依赖（Linux 发行版普遍预装；
Windows 走 vcpkg/预置 zlib 的平台构建已有第三方依赖管线）。

## D14b-14 网格维度算术全程防溢出（review B P1-2）
Python 靠 bignum；C++ 以除法边界复刻同一拒绝集（`grid_dims_valid`：任一 <1，
或除法链证明积 >8_000_000——任一维超上限且其余 ≥1 时积必超限，与 Python
逐案等价）。plan_export/export_data/verify_output 共用；export_data 对
hand-built plan 重新校验（Python 侧会在 writer/numpy 内响亮失败，C++ 提前
响亮拒绝，杜绝 int 截断静默错档）；verify_output 对越界维度给失败 check
（detail "预期 (超出导出规模上限)，实际 N"——Python 会打印天文数字 bignum，
frozen corpus 不可达，属 C++ 防御路径）。`option_int` 的 float 分支
|v|>9.2e18 抛 invalid_argument（Python 出 bignum，同样不可达 frozen 面）。

## D14b-15 manifest from_dict 改 fail-closed（review A P1）
Python `list(5)`/`dict(5)`/`int(None)` 抛 TypeError/ValueError → verifier
折为 corrupt-manifest；C++ 原实现静默跳过错型字段可使 verify.ok 翻转成
true。现 entries/external/missing/generated/provenance/options 错型即抛
invalid_argument，total_size_bytes null 沿旧例跳过（Python int(None) 亦
TypeError——注意：frozen corpus 无 null total；此处保持首切片行为并注释）。

## D14b-16 read_manifest 抛裸解析错误（review A P2 双前缀）
Python read_manifest 透传 JSONDecodeError，verifier 只包一层前缀；C++ 首切
片在 read_manifest 内预包导致 "manifest 解析失败: manifest 解析失败: ..."。
现 read_manifest 透传 parse_error，由 verify_directory 统一包一层（与
Python 单前缀一致）；conv-14 oracle 只冻 happy-path，无回归。

## D14b-17 响亮失败三处（review A P2 #3/#9 + review B P2-2/P2-3）
① catalog-less 项目 JSON 非 UTF-8 → 抛错中止构建（Python UnicodeDecodeError
在 except (OSError, JSONDecodeError) 之外）；② plan() 对缺失工程文件 stat
失败即抛（Python 同）；③ copy_payload/copy_artifacts_tree 哈希失败抛错
（builder.py 用会抛的 sha256_file，绝不发布空 sha256 条目）；④
recursive_directory_iterator 的 increment(ec) 在 build/copy/zip/symlink 扫描
路径上 ec 即抛（静默截断会发布不完整包或漏检 symlink）；verify_directory
的目录扫描保持静默跳过（与 pathlib.rglob 吞 OSError 语义一致）。

## D14b-18 zip 读端收紧（review A #13 + review B P2-5/P2-6）
EOCD 语义对齐 CPython `_EndRecData`：取最后一个签名且 comment 长度一次校验，
不回退更早候选；central directory 分配前校验 cd_offset+cd_size ≤ 文件大小、
entry_count ≤ cd_size/46（敌意容器不再触发巨分配）；flag-0x800 名字走严格
UTF-8（拒绝超长编码/代理对/>U+10FFFF，与 CPython decode 一致）；空条目写
规范 2 字节 deflate 流（\x03\x00）。

## D14b-19 verify_zip 的 BadZipFile 逃逸语义（review B）
Python 的 corrupt-* except 元组不含 BadZipFile：payload 损坏时异常直接冒出
verify_zip_container。C++ 同步——entry 读取的 ZipError 原样重抛，只有
JSON/类型/路径错误折为 issue；CRC 损坏档因此是「响亮异常」而非报告项。

## D14b-20 其余 review 修复清单
registry register(replace=true) 原地替换（对齐 preflight 内核与 Python dict
语义）；plan_import asset_name 空串回落 path.name（`asset_name or path.name`）；
option_float 对显式 null 抛 float(None) 类错误；inspect 对目录走
「无法读取文件」（IsADirectoryError 语义）；py_llong "+12" 符号bug 修复
（review A #7，conv-14 遗留，oracle 无冻结案例）；AtomicOutput fsync 空父
目录按 "." 处理；ZipWriter::add_file 用堆缓冲并提前拒绝 ≥4GiB；ZipEntryInfo
补 flags/dos_time/dos_date 供元数据冻结断言；oracle 补齐：zip 侧
missing-project（原案例改错键，A #4）、下划线数字解析 ×4（A #5）、manifest
全文冻结（A #6，弃 80 字节尾部启发）、extract ZIP64/目录条目、verify_dir
unsupported-schema、open_package fail-closed 报告路径、zip_package_dir
symlink 拒绝（`包内出现符号链接`）、zip_writer 元数据（UTF-8 flag + DOS
定格）断言、residue 含目录项。

## Review 轮次记录
- 轮 0（主 agent 自测对账）：oracle 首轮 replay 揪出 lib 真 bug——
  `std::filesystem::relative` 解析 symlink（→D14b-6），及测试侧 {ROOT}
  空间/双编码/目录清理问题；修后 417 checks 全绿。
- 轮 1（subagent #1，A parity）：P1×1（from_dict fail-open，→D14b-15）+
  P2×5 + P3×11，全部处置（见 D14b-16..20）；P3 中 write_manifest 临时文件
  语义（mkstemp vs 固定 .tmp）为首切片冻结行为，留待上游切片统一，不入本
  分支；EOCD comment、zip_package_dir 大条目 cancel 粒度记为已知限制。
- 轮 2（subagent #2，B 质量）：P1×2（无 geomodel 配置断裂——已由主 agent
  在审核运行期间修复并双树实证；维度溢出 →D14b-14）+ P2×8 + P3×11，
  全部处置（D14b-14/17/18/19/20）；「每 payload 单次流式」表述改为诚实
  的中等规模策略（D14b-1/头注）。
- 轮 3（subagent #3，C 闭环）：P1×1 与轮 2 同根（CMake 条件编译），已在
  该 subagent 读档后修复；P2 service 面文档夸大已改写（package runtime 由
  package_runtime.hpp 自由函数暴露）；P3 确认：无重复实现（sha256/写器/
  压缩均复用既有内核）、无 Python 残留、根 CMakeLists 零改动、与并行
  worktree 无冲突面；apps/UI 接线声明补入 findings。
- 收口门禁：interchange.archive 446 checks 全绿；全量 ctest 双配置
  （CONV_22+CONV_14：26/26；CONV_21 无 geomodel：25/25）×2 全绿，-j3，
  未等线上 CI。
