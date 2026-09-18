# 04 Decisions — 非显然选择留痕

每条按「决策 → 备选 → 理由」。歧义按「对用户流程更诚实、更少抽象」自决（prompt §0）。

## D1 · 「有界子集」的精确契约

**决策**：ring_ops 核只对**无退化简单输入**承诺与 shapely 一致，输入越界一律返回
`status=unsupported`（结构化 reason），绝不给出「看似合理」的错误答案：
- clip：subject 与 clip ring 均须 simple（无自交、无相邻重复边）；两边界无顶点触边、
  无共线重叠段；subject 为 Polygon（或两两不相交的 MultiPolygon）。
- repair：闭环段对任意输入忠实移植（dict 语义无越界）；定向/拆分仅对
  `is_valid==True` 等价的输入（自洽简单性检查集：每环 simple、洞在 exterior 内、
  环两两不交）与「单一 proper crossing bowtie」开放，其余 unsupported。
**备选**：实现完整 make_valid/GEOS overlay。**否决**：等价于重写 GEOS，违背 Karpathy
最小实现；prompt 明示「有界」。
**理由**：Python 产品对无效输入的行为由 GEOS 决定且属实现细节；诚实拒绝 + 显式 skip
是本仓既有哲学（shapely fallback 披露引擎、geotopo 拒绝式守恒）。

## D2 · clip 多边形交集算法 = 边界弧拆分 + even-odd 分类 + 节点缝合（overlay）

**决策**：A∩B 边界 = A 边界在 B 内的弧 ∪ B 边界在 A 内的弧。步骤：
1. 全部跨界求交（参数化，严格 t,u∈(0,1) 内点；端点触边/共线重叠 → unsupported）；
2. 两边界在交点处拆成弧，弧中点 even-odd 判在对侧多边形内（带洞语义 =
   exterior 内 ∧ 非洞内，与 geometry_planar.point_in_polygon_scalar 同谓词）；
3. 保留弧在交点节点缝合：proper crossing 节点度恒为 2（一条 A 弧 + 一条 B 弧），
   回路唯一、无歧义；
4. 回路按「最小包含外环」分类 exterior/hole（复用 polygonization 洞归属模式），
   输出外环 CCW / 洞 CW。
**备选**：Sutherland–Hodgman（仅凸 clip 环，且非凸 subject 会产出退化连接边——与
shapely 结构不符）；Weiler–Atherton 全量（含退化处理 = 无界工程）；Greiner–Hormann
（顶点触边退化处理复杂且许可/来源引入顾虑）。**理由**：本算法在 D1 契约内精确且每
一步可独立断言；与仓内 even-odd/洞投票先例同构，代码量最小。

## D3 · bowtie 自交拆分 = 单一 proper crossing 切两瓣（不做通用 make_valid）

**决策**：检出恰有一对非邻接边在参数内点相交、且无其他退化时，把闭合环在交点处
切成两条顶点链（各自闭合），每瓣按 signed area 定向 CCW，输出 MultiPolygon；
其余自交形态 unsupported。
**实证**：shapely 2.1.2 `make_valid` 对经典对角 bowtie
[[0,0],[10,10],[10,0],[0,10]] 输出 MultiPolygon，两三角形 (0,10),(5,5),(0,0) 与
(10,0),(5,5),(10,10)（各 25）——与本算法产物集合一致（仅旋转/方向不同，由规范化
比较吸收）。test_repairs_bowtie 面积 50、test_geological_topology_core 的
figure-eight 面积 4+4 同锚。
**备选**：多交点排列面提取（even-odd faces of arrangement）。**否决**：GEOS
make_valid 在多交点/缠绕情形的输出结构与任何单一简单规则都不同（如五角星的
孔洞建模），冻结价值低、错误风险高——归 shapely_optional。

## D4 · oracle 比较用「规范化坐标集合」，因为 GEOS 输出顺序不是契约

**决策**：规范化规则（生成器与 C++ 测试各自实现、语义一致）：
- 环：去重闭合点 → 旋转到字典序最小顶点在首位 → 保留方向；
- Polygon：|面积| 最大的环为 exterior（valid 多边形外环必含洞故必最大）、洞按
  规范化序列排序、外环若为 CW 则反转（外环 CCW 化）、洞 CW 化；
- MultiPolygon：按 (round(面积,6), 规范化 exterior) 排序；
- 折线片段：每段旋转到最小顶点 + 方向取「沿原折线方向」由生成器冻结为无向规范化
  （GEOS 片段方向跟随原线，但两段对称片段顺序不可依赖）→ 片段多重集比较；
- 坐标：冻结值 round(v,9)，C++ 比较差值 ≤1e-9（与 contouring 切片坐标 <1e-9 同门禁）。
**备选**：逐坐标严格序列比较。**否决**：GEOS 输出环起点/片序是内部细节，
test_geotopo_parity 用面积多重集已是仓内先例。
**理由**：比较仍强（坐标集合逐点对账，非仅面积），但不受 GEOS 排序扰动。

## D5 · portable / shapely_optional 分类由「输入形态」判定，不看出输出

**决策**：生成器对每个案例按输入属性分类（自交检出、环简单性、交点类型枚举），
`portable=true` 的案例其期望值 = 真实 Python 产品代码输出（真实 shapely 2.1.2），
C++ 必须对账；`portable=false` 案例只冻结输入 + Python 结局（ok/none/error 文案存档），
C++ 测试显式 skip 计数并打印 id。分类器是生成器内的输入检视代码，不参考 C++ 行为。
**备选**：按「C++ 跑不跑得过」回填分类。**否决**：循环论证，冻结失去意义。
**红线映射**：期望值全部来自真实 Python（import paleo_workbench 真模块），无手写。

## D6 · CMake 追加方式与测试目标名

**决策**：`libs/mapping_kernel/CMakeLists.txt` 尾部追加 `# BEGIN CONV-04` …
`# END CONV-04` 块，`option(PWB_BUILD_CONV_04 … OFF)` 门控把 `src/ring_ops.cpp`
追加进 pwb_mapping_kernel 源列表并登记测试 `mapping_kernel.ring_ops`；
根 CMakeLists 追加同样的 BEGIN/END 块（option 默认 OFF，不影响既有 configure）。
**备选**：新建独立库目标。**否决**：ring_ops 与 polygonization 共享 `Polygon`
类型（pwb/mapping/polygonization.hpp），独立库徒增链接复杂度——但源文件独立
（不改任何已绿 .cpp/.hpp，红线）。
**注意**：root 块的 `option()` 无条件声明缓存变量（默认 OFF）；真正被
`-DPWB_BUILD_CONV_04=ON` 门控的是 libs/mapping_kernel 块内的
`target_sources`/测试注册（命令行传入的缓存变量在任何处理前已存在）。

## D7 · 短环分支的实证修正（生成器开发期间用真实 Python 钉死）

**决策**：闭环后 <3 个坐标的环：shapely 构造抛
"A linearring requires at least 4 coordinates" → `except: pass` 返回闭环后
geometry（恒等回退，可移植，C++ 同样输出闭环结果）。闭环后**恰 3 个坐标**的环
（必然是首尾重复的零面积环）：实证 `shape()` 能构造成功（不抛 ValueError），
`is_valid=False` → `make_valid` 把零面积多边形分解为 **LineString**（GEOS 行为）
——不可移植，C++ 返回 unsupported。
**依据**：venv python 实证 probe（`Polygon([[0,0],[1,0]])` 直接构造抛 ValueError；
`repair_invalid_geometry({"Polygon", [[[0,0],[1,0],[0,0]]]})` 返回
`{"type":"LineString","coordinates":[[0,0],[1,0]]}`）。
**教训留痕**：预测（"3 坐标环也走 ValueError 回退"）被实证推翻——按红线以真实
Python 输出为准修正契约，而非按预测写死。

## D8 · 非几何类型 / 非 Polygon-MultiPolygon 输入与有界契约的有意保守

**决策**：repair 对 `type` 不属于 {Polygon, MultiPolygon} 的输入恒等返回；
clip_polygon_to_ring 对 subject 非 Polygon/MultiPolygon → unsupported（Python 会
在 shape() 处抛/或交出非面结果，属 GEOS 行为，不在契约内）；clip_polyline 少于
2 点 → shapely 构造即抛（实证为 GEOSException
"IllegalArgumentException: point array must contain 0 or >1 elements"，
**不是** ValueError——fixture 如实冻结该文案），C++ unsupported。
**有界契约的有意保守（审核后留痕）**：①折线零长段——真实 Python 不抛错
（GEOS 丢弃退化段返回其余片段），可移植但 C++ 拒绝（unsupported）；②MultiPolygon
的未闭合 3 坐标环（自动闭合后为合法三角形）——Python 走 orient 路径，C++
不再误拒（已在 spec 审核 F2 后修正为「仅闭合的 3 坐标零面积环才 unsupported」）。
两者均无正确性风险（诚实拒绝 ≠ 错误答案），语料以 optional 钉住。
**理由**：恒等返回是纯 dict 语义（可移植）；其余异常路径冻结其存在而非复刻其
引擎内部细节。

## D9 · 折线裁剪片段的输出顺序

**决策**：C++ 按**沿原折线的遍历顺序**输出片段（自然、可复现）；与冻结期望比较时
按 D4 片段多重集匹配。Python/GEOS 的片段顺序不冻结。
**理由**：用户流程（等值线裁剪）按 level 逐条出图，片段顺序不影响要素语义；
顺序契约留给未来 C++ 宿主自行定义（比 GEOS 内部顺序更诚实）。

## D10 · 数据结构与依赖

**决策**：`ring_ops.hpp` 复用 `pwb::mapping::Polygon/Ring/Point`（contouring.hpp 的
Point + polygonization.hpp 的 Polygon），Qt/GEOS/numpy-free；结果类型
`RingOpsResult{status, reason, geom_type, polygons}`；折线结果
`PolylineClipResult{status, reason, pieces}`。unsupported 的 reason 字符串是 C++
契约（英文短语，供测试断言与日志），不与 Python 异常文案互译（Python 文案在
fixture 存档，跨语言字符串断言是假精度）。
