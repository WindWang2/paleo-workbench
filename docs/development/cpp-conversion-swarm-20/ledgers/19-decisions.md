# 19-decisions — 非显然决策记录(CONV-19)

按时间顺序;每条含备选与理由。

## D1 — 环境路径适配:本机实际布局,不创建 prompt 中的不存在路径

Prompt 给出 `/home/kevin/projects/paleo_project/main` 与 `/home/kevin/.grok/skills/goal-loop`;实际环境为 repo=`/home/kevin/project/paleo-workbench`、worktrees=`/home/kevin/project/worktrees`、goal-loop SKILL 在仓内 `agent/skills/goal-loop/SKILL.md`。按「对用户流程更诚实」原则:使用实际路径,不新建虚假目录层级;SKILL 以仓内版本为准(内容与 goal-loop 协议一致)。基线 `35987e13` 与 prompt 所述一致,worktree/分支名严格照 prompt。

## D2 — geoviz 级联阻塞下的 oracle 诚实性:按真实源码 exec 加载,拒绝手写期望值

系统 python3 及全部既有 venv 均无 PySide6;`preview_parsers.registry → well_log_parsers → paleo_workbench.viz.well_log_api → paleo_workbench.viz.__init__ → geoviz → PySide6` 的**包级联 import** 在本机不可满足(prompt 明示不为本任务重装 QGIS/vendor 级依赖)。方案:oracle 生成器对 `well_log_parsers.py` 与 `registry.py` 先向 `sys.modules` 注入最小父包站位(`paleo_workbench.viz` / `paleo_workbench.viz.well_log_api`,后者仅提供 `fast_las_parse_data` 符号,不被被测函数执行路径触达),再以 `importlib` 按真实文件路径加载模块源码并执行。期望值仍**完全来自真实实现的执行结果**;与手写的界限 = 生成器里不存在任何期望值字面量。替代方案(装 PySide6 全家桶)被拒:网络+体积+prompt 禁令;方案(整模块不移植)被拒:xml_well_log_preview 恰是「XML 曲线头」验收流的核心。该站位只在生成器内,不进入产品/测试运行时。

## D3 — joint_well_parsers 不移植(只读)

其结果类型(WellHead/TimeDepthTable/JointWellId)与身份协调(WellIdentityRegistry.reconcile)都构造自 geoviz/身份注册表——站位 stub 等于重写实现,违反 D2 的诚实性边界;模块 import 即失败,无法产出任何真实 oracle。且 §4 目标清单不含它(仅 §5 必读)。语义已逐符号记录于 findings §23,留待 geoviz 依赖可行后的切片。备选(移植纯文本行解析但无 oracle)违反 §2.5「oracle 覆盖每个公开函数」,拒。

## D4 — 移植范围:preview_parsers 的「纯解析」子集 + 分类/路径/设置;重依赖 parser 冻结其依赖缺失回退

- 移植:well_tops、well_location_xml、well_log_xml、classifier(+io_registry 表)、project_path(穿越拒绝)、preview models/format 表/PreviewSettings(fingerprint)、text/dat/csv/table、markdown_to_html、json_preview、spreadsheetml_preview、xml_well_log_preview、office(zip/pptx/dfb+ZIP 校验+PNG/JPEG 验证器+CRC32+mini-inflate)、registry.build_preview dispatch。
- 不移植:geotiff(rasterio)/excel(pandas)/las(geoviz+lasio)/docx(python-docx)/segy(segyio)的真解析——C++ 侧这些引擎不存在,**Python 在无依赖环境下的回退分支就是 C++ 的长期语义**,故冻结该回退(文案与 mode)。理由:C++ 核心永远处于「无这些 Python 引擎」状态,冻结 env 产物反而是对 C++ 可见行为的诚实描述;真引擎接入时改走 libs/seismic_io 等已建 C++ 核,属后续接线切片。joint_well_parsers 见 D3。
- 用户验收流「XML/井顶文本 → 点/曲线头一致」由 well_tops / well_location_xml / well_log_xml / classifier / spreadsheetml / xml_well_log_preview 直接覆盖。

## D5 — `_first`/`next()` 的 set 迭代序歧义:C++ 固定声明序,oracle 只冻序不变案例

`well_location_xml` 的 `_NAME_KEYS/_X_KEYS/...` 是 Python set;`_first` 与 `next(k for k in keys ...)` 的命中顺序是 hash 序(跨进程甚至 PYTHONHASHSEED 可变),同一 values 含同族多键时 Python 自身不确定。C++ 采用**源码声明顺序**的候选表取首个命中。oracle 生成器约束:每个案例的 values 中同族至多一个键命中(真实交付文件形态),此时两语义可证等价;多键案例不冻结(冻了就是把 hash 序钉成契约)。已写入 findings 供审核。

## D6 — GB18030 解码级缺失(诚实声明)

`decode_text_with_fallback` 三级 utf-8-sig→gb18030→replace;C++ 无 ICU/Qt,gb18030 码表不实现。C++ 为 utf-8-sig 严格→replace 两级。影响面:仅「非 UTF-8 且非 ASCII」的 GBK 历史文本文件的预览文本内容;oracle 不构造此类案例(无法双向对账),diff 在 PR 声明。备选(嵌 Qt QStringDecoder)违反 Qt-free 红线;备选(自带 3 万项码表)违反最小代码。

## D7 — json_preview 的 C++ 侧只做「有效性判定」,不构建 payload 树

Python 侧 `json_payload` 供 UI 树;对账目标是 mode/warning/truncated/文案。C++ 实现一个 Python-json 兼容的严格校验器(RFC 8259 + NaN/Infinity 字面量 + 严格 UTF-8 已在前级 decode 保证),不产出 DOM。预览树渲染属 UI 层后续切片。

## D8 — 依赖缺失回退案冻结为「C++ 长期语义」

geotiff→image_fallback("地理元数据读取失败,仅显示图像")、excel→"Excel 预览失败: ImportError"、las→"LAS 预览失败: ModuleNotFoundError"(geoviz 缺)、docx→"docx 预览依赖缺失,请安装 python-docx"、segy→不冻(纯 env 产物且 C++ 有真 seismic_io,冻结会误导接线层)。前四个冻结的理由见 D4;segy 同样冻结依赖缺失文案(SEG-Y 预览依赖不可用)——与 las/excel 同一逻辑:冻结的是当前 registry 路由的可见行为;libs/seismic_io 真读核接入 preview 路由时,属后续接线切片的显式语义变更点。

## D9 — ZIP 读取:C++ 自实现 central-directory 解析 + mini-inflate

zipfile 在 C++ 无对应;thumbnail 条目可能是 deflate。自研:central directory 校验逐分支(文案逐字对齐)+ 本地头跳过 + stored/deflate 两模式 inflate(fixed+dynamic Huffman,截断/校验失败报错)。CRC32 表驱动。备选(引 zlib 依赖)违反「libs 独立可编」现状(mapping_kernel 无外部依赖先例);备选(仅 stored)无法对真实 pptx 对账。

## D10 — spreadsheetml 用流式 XML 而非 DOM 模拟

iterparse+人工 EOF 的「边界截断保留部分行」语义(test_fallback_preview bounded.xml:4 行+truncated)DOM 不可复现(截断前缀整树解析必失败)。XML 基建按事件流实现(expat 式:start/end/text,遇错停但保留已发事件),ET.parse 语义用同一事件流建树。这份事件流核同时服务 well_location_xml/well_log_xml(DOM)与 spreadsheetml(流)。

## D11 — CMake:独立 `libs/ingest`,链接 Pwb::Domain(复用 nlohmann/Json/Sha256),`BEGIN CONV-19` 块追加

mapping_kernel 已示范 Pwb::Domain 作为 Qt-free 基建(nlohmann ordered_json、json_semantic_diff 对账、Sha256 与 hashlib 逐字节一致)。ingest 链接同款,不复制第三方;测试目标名 `ingest.parsers`(§8 要求),fixture 宏注入方式与 mapping_kernel_tests 一致。根 CMakeLists 只追加 CONV-19 块(option `PWB_BUILD_CONV_19`),不动其他块。

## D12 — oracle 生成器与冻结 JSON 放 `libs/ingest/oracle/`(而非 tools/oracle/)

§6 写入边界只允许 `libs/ingest/`+根 CMake CONV-19+ledgers;前序切片惯例 tools/oracle 不在本边界内。生成器(真实 Python)+冻结案例 JSON 同置 `libs/ingest/oracle/`,测试经编译期宏指向 fixtures 目录。生成器是脚本不是产品代码,进 libs/ingest 不违反其 Qt-free 核定位(不参与 CMake 编译)。

## D13 — mtime/oracle 确定性:revision 冻 size,不冻 mtime_ns

safe_stat 的 mtime_ns 随生成时刻变化;revision token 对账只取 size 分量,测试断言 revision 的「存在性+size 分量+checksum 分量」,不做跨机 mtime 相等(非确定性不可冻)。

## D14 — Python float 字面量语义集中实现

well_tops/well_location_xml/dat 列/las 数值都依赖 Python `float()`:接受前后空白、"inf"/"infinity"/"nan"(大小写)、`1_000` 下划线、`1e5`;拒绝十六进制/逗号/全空。C++ 集中一个 `py_parse_float(std::string_view) -> std::optional<double>`,全部调用点共用;NaN/inf 合法输入会产出 NaN/inf 记录(Python 亦然),oracle 有显式案例。
