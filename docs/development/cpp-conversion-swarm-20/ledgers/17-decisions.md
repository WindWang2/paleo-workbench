# 17 — Decisions(非显然选择逐条记录)

D1. **路径/环境差异**:prompt 假设仓库在 `/home/kevin/projects/paleo_project/main`、
skill 在 `/home/kevin/.grok/`——本机均不存在。实际:仓库主工作区
`/home/kevin/project/paleo-workbench`,worktree 惯例
`/home/kevin/project/worktrees/cpp-conv-17-crs-units`(conv-11…19 同);
goal-loop skill 文件不存在,按 prompt 自含的 GOAL Loop 协议 + 仓内
karpathy-guidelines(`agent/skills/`)执行。BASE = `35987e13`(origin/main,
与 prompt 指定一致)。

D2. **Python oracle 解释器**:系统 `python3` 无 numpy(与 prompt「已能
import paleo_workbench」不符),无法走 mapping 包 `__init__` 的
geological_pipeline 链。用 swarm 既有 oracle venv
`/home/kevin/project/oracle-venvs/conv12/bin/python3`(numpy 2.5.3 +
PySide6 6.11.2——`paleo_workbench.mapping.__init__` 第 51 行拉
map_render_backend → PySide6,conv11 venv 缺 PySide6 不可用;conv12 皆有)。
生成器按 `__file__` 定位 REPO_ROOT 前置 sys.path,**运行 cwd = worktree
根**(cwd `''` 会遮蔽 worktree 副本,沿用 conv-18 D12 的教训)。

D3. **pyproj 双段冻结**:conv12 有 pyproj,而 C++ 核无 pyproj。kernel
对账段在生成器内以 `sys.modules["pyproj"] = None` **阻断 pyproj 导入**
后跑真实模块——`from pyproj import ...` 走真实 ImportError → except
路径(不是手写 None);这与 C++ 的依赖轮廓完全一致,值可精确对账。
另录 `pyproj_env` 对照段(不阻断,只记录不比对):供后续接线者看
pyproj 在场时 Python 多知道什么(32650 的米轴/面积域/失配判定),
也如实暴露「C++ 内核与 pyproj 版 Python 的能力差」——与既有
crs_policy oracle 的 `pyproj_optional` 段同思想,更严格(kernel 段
值级对账而非只断言 nullopt,因为阻断后环境确定)。

D4. **is_geographic_crs 的三值→二值坍缩**:geometry_units 的
`is_geographic_crs` 把 crs_policy 的 None(不可验证)坍缩为 False——
消费侧语义(面积标签走 `{crs}-unit²` 分支)。C++ 同样返回 `bool`。
「WGS84」这类 id:pyproj_env 段 Python=True(地理),kernel 段/C++
=False——能力差如实记录,不是行为分叉。

D5. **crs_contract.crs_is_geographic 不在 C++ 重复声明**:Python 侧它是
「strip + 空转 None 后委托 workflow.crs_policy」的薄层;对全部字符串
输入与既有 `pwb::mapping::crs_is_geographic`(crs_policy.hpp)等价
(空白串两侧都 nullopt,头段 trim 语义相同)。同 namespace 重声明
同名函数不可行且多余——C++ 复用既有谓词,头注释写明委托关系;oracle
仍以 crs_contract.crs_is_geographic 的真实输出冻结对账(证明等价)。

D6. **normalize_crs 的 `\b` 手写解析**:`re.match(r"^(EPSG:\d+)\b", t, I)`
手写为「锚定起始 + 大小写无关前缀 + ≥1 数字 + 边界(下一字符属 ASCII
[A-Za-z0-9_] 或串尾)」。回溯等价性:数字段任一前缀的终止字符都是
数字(\w),边界必然失败,故只需检查整段数字后的字符。**非 ASCII
后继字符按 word 处理(不命中 → 原样返回)**:Python unicode \w 含
非 ASCII 字母/数字,取保守一致侧;oracle 不含该超边(真实 CRS 串
不存在 "EPSG:4326é" 形态),在源码注释声明。

D7. **Python repr 助手复制而非共享**:crs_policy.cpp 的
`python_str_repr` 在匿名命名空间;geometry_units 的 warning 需要
`crs!r`(None → 字面 `None`,串 → repr)。为不改已绿文件,在
geometry_units.cpp 匿名命名空间放同逻辑小 helper(~20 行);两处各自
由各自 oracle 钉住,漂移可检出。

D8. **Ring/Point 的 len(pt)>=2 由类型保证**:Python `lats =
[float(pt[1]) for pt in ring if len(pt) >= 2]` 容忍畸形点;C++
`Ring = std::vector<Point>`(array<double,2>)畸形点不可表示——类型级
排除,oracle 只含良构环(shoelace 本身对 <2 元素点会 IndexError,
Python 侧同样不在契约内)。空环:Python lats 空 → mean_lat=0 满尺度、
面积 0;C++ 同分支显式保留。

D9. ** shoelace/长度复用已绿核**:`shoelace_area`(polygonization.cpp:173,
0.5·|signed_area|,n<3→0,不补闭合边)与 `polyline_length`
(contouring.cpp:213)与 Python 委托目标逐行同构,直接复用;geometry_units
C++ 只拥有「单位标签 + 地理近似 + warning」层。头注释注明环须闭合的
Python 约定,oracle 冻结 closed vs unclosed 方环案例钉住。

D10. **geod_for_crs / runtime_crs_capable / evaluate_edit_entry /
crs_gate 全家不移植**:geod_for_crs 返回 pyproj.Geod(椭球库对象,
Qt-free 核不引入;无 pyproj 环境恒 None 的事实由 oracle 冻结);
runtime_crs_capable 依赖 qgis_runtime.health(QGIS 桥探测);
evaluate_edit_entry/CrsChainFacts/LayerCrsFacts(crs_chain.py)与
crs_gate 全家在 §6 写入范围之外——findings 已逐符号留档,留给
crs_chain 后续切片。本切片 = geometry_units 全部 + crs_contract 除
geod_for_crs 外的全部声明/单位规则。

D11. **panel_publish_crs 的 logger.warning 不移植**:C++ 内核无日志面;
返回 "" 即契约(降态),degraded_reason 经 resolve_crs 可取。调用方
(宿主)负责呈现——与 Python「caller 不得吞判词」同一纪律的 C++ 形态。

D12. **scale_denominator_from_pixels 的公式行在内核暂不可达**:
crs_axis_unit_metres 无 pyproj 恒 nullopt → 守卫分支恒 0.0,乘式不可达。
保留乘式(契约完整;`39.370078740157481` 字面量逐字)而非删成
`return 0.0`——后续任何轴真源(vendored proj 探测、pinned 米制表)落地
即活,且与 Python 逐行对得上。Karpathy 张力记档:这是移植的忠实性
优先于「删不可达代码」的一处。

D13. **DomainMismatch.describe 的 %g**:Python `f"{x:g}"` 与 C
`%g` 同源(6 位有效、去尾零、指数阈值一致),用 `snprintf("%g")`;
inf/nan 分歧不适用(域/范围坐标由 double 输入,oracle 不含 inf/nan)。

D14. **CRSResolution/DomainMismatch/CRSInference 用 struct + 值语义**:
Python frozen dataclass(slots)→ C++ 简单 aggregate(struct,字段同名
snake_case 保持映射直观);`ok`/`suggests_declaration` property →
const 成员函数。extent/domain 用 `std::array<double,4>`(x0,y0,x1,y1
序,同 Python tuple 序),可选性用 `std::optional`。

D15. **resolve_crs 的 C++ 形参**:value/fallback 用
`std::optional<std::string>`(Python None ↔ nullopt,"" ↔ 空串,二者
判定同途但语义保留);purpose 用 `const std::string&` 无默认
(Python 恒关键字传参);panel_publish_crs 的 purpose 默认
"图层面板发布" 与 Python 一致(UTF-8 字面量,MSVC /utf-8 已在根
CMakeLists 对 MSVC 强制,与既有核中文字符串同做法)。

D16. **CMake 布局(沿 conv-18 D13 先例)**:
- 根 `CMakeLists.txt` 追加 `# BEGIN CONV-17` 块:声明
  `option(PWB_BUILD_CONV_17 ...)`,ON 且 `PWB_BUILD_MAPPING_KERNEL` 未开
  时置位后者(新叶物理在 mapping_kernel 内,避免重复 add_subdirectory);
- `libs/mapping_kernel/CMakeLists.txt` 追加块:
  `target_sources(pwb_mapping_kernel PRIVATE src/geometry_units.cpp
  src/crs_contract.cpp)`(不改 add_library 原列表);
- `libs/mapping_kernel/mapping_kernel_tests/CMakeLists.txt` 追加块:
  `mapping_kernel.crs_units` 测试目标 + fixture 宏 + TIMEOUT 30,
  `PWB_BUILD_CONV_17` 门控。
CONV_17=OFF 时目标与测试与 main 逐字节等价(外科边界)。

D17. **oracle 结构**:`crs_units_oracle.json` 单文件,顶层
`kernel`(pyproj 阻断,C++ 值级对账)与 `pyproj_env`(只记录)两段;
geometry_units / crs_contract 各自函数分节;每案例带稳定 `id` 与
输入回显(环/折线顶点内联)。数值对账容差:面积/长度
`|got-want| ≤ 1e-9·max(1,|want|)`(cos/hypot/libm ulp 噪声;与
contouring 1e-9 惯例一致);域常量/标签/warning/判词逐字节;domain
数组精确相等(纯输入派生)。失败分支文案(resolve_crs 判词、
undeclared warning、describe)是契约,逐字节比对。

D18. **NaN/Inf 不入 oracle**:JSON 无 NaN/Inf 字面量(nlohmann 拒收),
且 C++ Json 封装未声明容忍(conv-18 D7 的容忍解析是那个 codec 的局部
决定,不外溢)。geometry_units 的 NaN 纬度传播路径(cos(NaN)→NaN)
不做冻结,findings 注明为测试缺口。

D19. **subagent 配额用法**:≤3——(1) explore 源码复核(如需要)、
(2) 对抗性 spec 审核、(3) Karpathy/质量审核。实现全部父代理自己写。

D20. **验收口径**:「地理 CRS 的环面积带单位标签与 Python 一致」=
kernel 段 ring_area_with_unit 案例的 (area, unit_label, warning) 三元组
值级一致(含 ≈m² 近似值本身,1e-9 相对);「未声明 CRS 不得被猜成
4326」= resolve_crs/panel_publish_crs/infer_crs_from_extent 的未声明
案例:crs=""、declared=False、判词含「未声明」,且不存在任何把空串
变 4326 的代码路径(源码级 + oracle 案例级双重钉住)。

D21. **Unicode 超边(审核轮 2 的两个 P2,记档不修)**:①Python `\d` 匹配
Unicode Nd 数字(全角 "４３２６" 等),C++ 只认 ASCII——归一化对全角数字
CRS 串分歧;②Python `str.strip()` 剥 NBSP/全角空格,C++ `trim` 只剥
C-locale ASCII 空白。两者均与**已绿 crs_policy 基线的 trim/ASCII-upper
家族性取舍一致**(crs_policy.cpp 同款 ASCII trim)——单独在 crs_contract/
geometry_units 里加 Unicode 支持反而与谓词基线分叉;真实 CRS 串不含这些
形态,oracle/pytest 均无此输入。保持与基线一致的 ASCII 语义,如实记档。

D22. **审核轮 3 修复(根 CMakeLists P1)**:CONV-17 块原放在
add_subdirectory(libs/mapping_kernel) 之后,单独
`-DPWB_BUILD_CONV_17=ON` 配置时 `set(PWB_BUILD_MAPPING_KERNEL ON)`
执行过晚,子目录不会被添加→选项静默空转。已把块整体上移到 kernel
子目录之前(仍为纯插入,不动任何已有行)。单独开启 + platform/science
OFF 实测:configure→build→ctest mapping_kernel.crs_units 全通过;
kernel 对 PWB_BUILD_DATA 的 fail-closed FATAL_ERROR 保留(响亮报错,
符合仓内「ON 必须真的在」准入文化)。subagent 配额用量:2/3
(spec 对抗审核、Karpathy 审核),实现未外包。
