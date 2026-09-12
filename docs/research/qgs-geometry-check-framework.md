# QgsGeometryCheck 拓扑检查框架与插件源码可移植性（调研）

> wayfinder 票 WindWang2/paleo-workbench #1280。2026-09-11。
> 一手源码考证，基于 `third_party/qgis`（QGIS 4.2.0 源码快照）。
> 共享底座：`docs/research/topological-editing-baseline.md`（vendored 构建只含
> core+gui+analysis，无 app 库、无插件——本报告所有结论均以"只链
> core+gui+analysis"为前提）。

除特别说明，文中 `src/...` 路径均相对 `third_party/qgis/`。

## 1. analysis 库 QgsGeometryCheck 体系

### 1.1 全部检查类都在 analysis 库里

`src/analysis/vector/geometry_checker/` 下共有 **23 个具体检查类**（另有
2 个抽象基类 `QgsGeometryCheck`、`QgsSingleGeometryCheck` 与错误类、基础设施类），
全部 `ANALYSIS_EXPORT`（类声明见各 `qgsgeometry*check.h`；多数标 `SIP_NO_FILE`
即未导出 Python 绑定，但 C++ 符号完整导出）。按 `CheckType`
（`qgsgeometrycheck.h:148-153`：`FeatureNodeCheck`/`FeatureCheck`/`LayerCheck`，
其中 LayerCheck 即拓扑检查）分类：

| 检查 | 类 | 类型 | 说明 |
|---|---|---|---|
| 面重叠 | `QgsGeometryOverlapCheck` | LayerCheck | **本票关注** |
| 面缝隙 | `QgsGeometryGapCheck` | LayerCheck | **本票关注**（`qgsgeometrygapcheck.cpp:521-524`） |
| 缺失共享节点 | `QgsGeometryMissingVertexCheck` | LayerCheck | 邻接多边形共享边缺顶点 |
| 线自相交 | `QgsGeometrySelfIntersectionCheck` | FeatureNodeCheck | |
| GEOS 有效性 | `QgsGeometryIsValidCheck` | FeatureNodeCheck（单几何） | |
| 悬挂点 | `QgsGeometryDangleCheck` | FeatureNodeCheck | **本票关注**（`qgsgeometrydanglecheck.cpp:143-146`） |
| 伪节点/自接触 | `QgsGeometrySelfContactCheck` | FeatureNodeCheck | |
| 重复几何 | `QgsGeometryDuplicateCheck` | LayerCheck | |
| 重复连续节点 | `QgsGeometryDuplicateNodesCheck` | FeatureNodeCheck | |
| 内环（洞） | `QgsGeometryHoleCheck` | FeatureCheck | |
| 退化多边形 | `QgsGeometryDegeneratePolygonCheck` | FeatureCheck | |
| 最小面积 | `QgsGeometryAreaCheck` | FeatureCheck | |
| 狭长多边形 | `QgsGeometrySliverPolygonCheck`（继承 Area） | FeatureCheck | |
| 最小角度 | `QgsGeometryAngleCheck` | FeatureNodeCheck | |
| 最小线段长 | `QgsGeometrySegmentLengthCheck` | FeatureNodeCheck | |
| 线相交 | `QgsGeometryLineIntersectionCheck` | LayerCheck | 同层线 |
| 线跨层相交 | `QgsGeometryLineLayerIntersectionCheck` | LayerCheck | 对第二层 |
| 点未在线上 | `QgsGeometryPointCoveredByLineCheck` | LayerCheck | |
| 点不在面内 | `QgsGeometryPointInPolygonCheck` | LayerCheck | |
| 面不含点 | `QgsGeometryContainedCheck` | LayerCheck | |
| 多部件 | `QgsGeometryMultipartCheck` | FeatureCheck（单几何） | |
| 几何类型 | `QgsGeometryTypeCheck` | FeatureCheck（单几何） | |
| 跟随边界 | `QgsGeometryFollowBoundariesCheck` | LayerCheck | 对参考层 |

### 1.2 注册/工厂机制——存在**两套互不相通**的注册表

**A. analysis 库自带注册表（桥内可直接用）**：`QgsAnalysis` 单例在构造时通过
`QgsGeometryCheckRegistry::registerGeometryCheck()` 只注册 5 个检查
（`src/analysis/qgsanalysis.cpp:45-49`）：

- `QgsGeometrySelfIntersectionCheck`、`QgsGeometryIsValidCheck`、
  `QgsGeometryGapCheck`、`QgsGeometryOverlapCheck`、`QgsGeometryMissingVertexCheck`

恰好就是带 `AvailableInValidation` 旗标、供 app「图层属性→数字化→几何校验」
实时校验用的那批（消费方见 `src/app/qgsgeometryvalidationservice.cpp:235-276`，
按 `checkRegistry->geometryCheckFactories(layer, CheckType, AvailableInValidation)`
过滤后 `createGeometryCheck()`）。

**枚举全部可用检查的 API**（`qgsgeometrycheckregistry.h:71`、
`qgsgeometrycheckregistry.cpp:35-44`）：

```cpp
QgsAnalysis::geometryCheckRegistry()->geometryCheckFactories(
    layer, QgsGeometryCheck::LayerCheck, QgsGeometryCheck::Flags());
// 按 id 创建实例（工厂把 context+QVariantMap 配置传给检查构造函数）：
QgsAnalysis::geometryCheckRegistry()->geometryCheck(checkId, context, config);
```

**B. geometry_checker 插件私有注册表（不在桥内）**：桌面「检查几何有效性」
对话框的另外 21 个工厂注册在插件自己的
`QgsGeometryCheckFactoryRegistry`（`src/plugins/geometry_checker/qgsgeometrycheckfactory.h:44-64`，
静态单例 + `REGISTER_QGS_GEOMETRY_CHECK_FACTORY` 宏
`qgsgeometrycheckfactory.h:73-77`，21 处注册遍布
`src/plugins/geometry_checker/qgsgeometrycheckfactory.cpp:79-725`）。
注意此注册表**不写入** `QgsAnalysis::geometryCheckRegistry()`——两套系统并列。

**关键可移植性事实**：插件的工厂模板以 `Ui::QgsGeometryCheckerSetupTab&`
为参数（`src/plugins/geometry_checker/qgsgeometrycheckfactory.h:29-31`），
纯 UI 耦合、不含算法；而 analysis 库自带一个**通用工厂模板**
`QgsGeometryCheckFactoryT<T>`（`src/analysis/vector/geometry_checker/qgsgeometrycheckfactory.h:89-103`，
仅调用 `T::factoryId()/factoryDescription()/factoryIsCompatible()/factoryFlags()/factoryCheckType()`
静态函数）。**需要注意的不对称**：5 个旗舰检查完整实现了这组静态函数
（含 `factoryFlags()`，如 `qgsgeometrygapcheck.cpp:496-524`、
`qgsgeometryisvalidcheck.cpp:87`），而其余 18 个检查只实现了
description/id/isCompatible/checkType 四项、**没有 `factoryFlags()`**
（对照 `qgsgeometrydanglecheck.h:50-54` 与 `qgsgeometryholecheck.h:40-53`，
全目录 `factoryFlags` 仅出现在 5 个旗舰检查中；实例方法 `flags()` 基类有默认
空实现，`qgsgeometrycheck.cpp:45-48`）。因此：

- 直接 `new QgsGeometryDangleCheck(context, QVariantMap())` 等**构造函数路径对
  全部 23 个检查都开放**（构造签名统一 `(const QgsGeometryCheckContext*, const QVariantMap&)`，
  `qgsgeometrycheck.h:223`；gap：`qgsgeometrygapcheck.h:107`）——这是桥接层
  最省事的用法；
- 要走注册表统一枚举，旗舰 5 个可直接用模板注册；其余 18 个需自写一个
  返回 `Flags()` 的微型工厂（或复制模板去掉 factoryFlags 一行）：
  `QgsGeometryCheckFactoryT<QgsGeometryDangleCheck>()` 现状**不能**直接编译。

### 1.3 运行上下文与容器

- `QgsGeometryCheckContext(precision, mapCrs, transformContext, project, uniqueIdFieldIndex=-1)`
  （`qgsgeometrycheckcontext.h:44-46`）：`tolerance = 10^-precision`，
  `reducedTolerance = 10^(-precision/2)`（面积用，`qgsgeometrycheckcontext.h:53-61`）。
  `project` 指针仅供主线程 `prepare()` 解析参考层（`qgsgeometrycheckcontext.h:81-87`）。
- 要素池 `QgsFeaturePool`（抽象，`qgsfeaturepool.h:37`）：带 1000 条要素缓存 +
  空间索引（`qgsfeaturepool.h:211-218`），`collectErrors` 在工作线程经
  `QgsVectorLayerFeatureSource` 跨线程读要素。

## 2. 插件源码依赖审计（逐文件）

### 2.1 `src/plugins/geometry_checker/` —— 全部是 UI 壳，无可搬逻辑

| 文件 | 分类 | 说明 |
|---|---|---|
| `qgsgeometrycheckerplugin.cpp/.h` | UI 壳 | 插件入口，`QgisInterface` 菜单/动作 |
| `qgsgeometrycheckerdialog.cpp/.h` | UI 壳 | QTabWidget 对话框（setup+result 两页） |
| `qgsgeometrycheckersetuptab.cpp/.h` + `.ui` | UI 壳 | 勾选检查项、容差、输出方式 |
| `qgsgeometrycheckerresulttab.cpp/.h` + `.ui` | UI 壳 | 错误表、rubber band 高亮、修复按钮（`QgisInterface` 10 处） |
| `qgsgeometrycheckfixdialog.cpp/.h` | UI 壳 | 逐条修复的交互对话框 |
| `qgsgeometrycheckerfixsummarydialog.cpp/.h` + `.ui` | UI 壳 | 修复统计 |
| `qgsgeometrycheckfactory.cpp/.h` | **UI 耦合胶水** | 21 个工厂特化，从 UI 控件读配置/QgsSettings 存取（见 §1.2）；算法零含量 |

**结论：该插件没有任何独立于 analysis 的检查/修复算法**。检查逻辑在
analysis（§1.1），修复逻辑也在各检查类的 `fixError()`（§3）。setup tab 组装
checker 的方式（`qgsgeometrycheckersetuptab.cpp:465-489`）就是桥接层要复刻的
全部"业务"：`QgsVectorDataProviderFeaturePool` 池（468 行）→ `QgsGeometryCheckContext`（478 行）
→ 工厂造检查（481-488 行）→ `new QgsGeometryChecker(checks, context, featurePools)`（489 行）。
result tab 的修复循环就是 `mChecker->fixError( error, fixMethod )`
（`qgsgeometrycheckerresulttab.cpp:529`）。**需重写的只有面板本身，胶水约 25 行。**

### 2.2 `src/plugins/topology/` —— 独立遗留引擎，规则可搬但价值低

| 文件 | 分类 | 说明 |
|---|---|---|
| `topolTest.cpp/.h` | **规则引擎（近纯逻辑）** | 自有规则表 `mTopologyRuleMap`（构造于 `topolTest.cpp:59-70`：must not have dangles/overlaps/gaps 等 15 条）；唯一 app 依赖是 `qgsInterface->mapCanvas()->extent()` 取画布范围（`topolTest.cpp:177,230,544,1345-1369` 等 14 处，仅用于 extent 模式过滤），以及构造函数接 `QgisInterface*`（`topolTest.h:101,228`——存了但只用于取 canvas） |
| `topolError.cpp/.h` | **规则逻辑（可搬）** | 错误模型 + 修复函数，直接 `layer->changeGeometry()/deleteFeature()`（edit buffer；`topolError.cpp:48,79-80,104,122,128`） |
| `dockModel.cpp/.h` | 近纯逻辑 | QAbstractTableModel 错误列表模型，0 处 app 依赖 |
| `checkDock.cpp/.h` + `.ui`、`rulesDialog.* + .ui`、`topol.cpp/.h` | UI 壳 | dock、规则配置对话框、插件入口（`topol.cpp:19` 含 `qgisinterface.h`） |

**与 analysis 框架的能力对比**（决定不值得搬）：

- 拓扑插件 `checkGaps`（`topolTest.cpp:431-570`）：GEOS 直算 union→bbox buffer(2,3)→difference，
  **跳过第 0 个部件**当外环（`topolTest.cpp:546` 的 `for (int i = 1; ...)`，
  启发式，大缝隙若排第一会被误跳）；无面积阈值、无豁免层；缝隙/重叠的修复
  函数被注释掉（`topolError.cpp:199-221`，`TopolErrorGaps/TopolErrorOverlaps`
  的 mFixMap 为空）；悬挂点唯一修复是"删除要素"（`topolError.cpp:188-193`）。
- analysis `QgsGeometryGapCheck` 同类检查语义更严谨（见 §4），且带完整修复。

## 3. 错误模型与修复 API

### 3.1 QgsGeometryCheckError 生命周期

错误对象由 `collectErrors()` 在检查中 new 出，生命周期由
`QgsGeometryChecker` 持有并在析构时统一删除（`qgsgeometrychecker.cpp:50-52`）。
状态机（`qgsgeometrycheckerror.h:40-46`）：

```
StatusPending ──setFixed(method)──▶ StatusFixed          (qgsgeometrycheckerror.h:156)
             └─setFixFailed(reason)▶ StatusFixFailed     (qgsgeometrycheckerror.h:161)
任何状态 ──────setObsolete()──────▶ StatusObsolete        (qgsgeometrycheckerror.h:166)
```

错误携带：`layerId/featureId`、`geometry()`（缝隙错误即缝隙多边形）、
`location()`、`vidx()`（节点级检查的 part/ring/vertex）、`value()+valueType()`
（面积/长度）、`affectedAreaBBox()`/`contextBoundingBox()`（缩放定位）、
`involvedFeatures()`（缝隙的邻居要素表，`qgsgeometrygapcheck.cpp:563-566`）。
`isEqual()/closeMatch()/update()` 供复查时去重合并
（`qgsgeometrycheckerror.h:173-185`）。

### 3.2 修复在 analysis 层，不在插件层

每个检查类实现 `fixError(featurePools, error, method, mergeAttributeIndices, changes)`
（虚函数声明 `qgsgeometrycheck.h:290-291`，注释明确"executed on the main thread"）。
可选修复清单由 `availableResolutionMethods()` 返回
`QList<QgsGeometryCheckResolutionMethod>`（`qgsgeometrycheck.h:298`；
默认实现包装废弃的 `resolutionMethods()`，`qgsgeometrycheck.cpp:75-81`）。
`QgsGeometryCheckResolutionMethod` = `{methodId, name, description, isStable}`
（`qgsgeometrycheckresolutionmethod.h:29`）。

**编排器 `QgsGeometryChecker`**（`qgsgeometrychecker.h:48-66`）：

- `execute()` 用 `QtConcurrent::map` 并行跑各检查（`qgsgeometrychecker.cpp:91`），
  进度经 `progressValue` 信号；错误经 `errorAdded/errorUpdated` 信号流出。
- `fixError(error, method)`（`qgsgeometrychecker.cpp:103-283`）干四件事：
  1. 调 `error->check()->fixError(...)`（117 行）；
  2. 按 `changes`（`QMap<layerId, QMap<fid, QList<Change>>>`，
     `qgsgeometrycheck.h:218`）收集受影响要素 + 外扩范围（147-194 行）；
  3. **自动局部复查**：只对受影响要素/范围重跑检查（196-214 行）；
  4. 用复查结果更新旧错误（`update`/`setObsolete`）并追加新错误（216-272 行）。
  这个"修复→复查→级联失效"闭环是插件面板零成本获得的，也是自制面板直接
  复用 `QgsGeometryChecker` 的最大理由。
- 构造时把各池的图层设只读 + `dataProvider()->enterUpdateMode()`（OGR 延迟
  repack），析构还原（`qgsgeometrychecker.cpp:39-47,54-62`）。

### 3.3 修复如何落到图层：edit buffer 还是 provider？——两种池二选一

| 池 | 写路径 | 出处 |
|---|---|---|
| `QgsVectorLayerFeaturePool` | `lyr->updateFeature()/deleteFeatures()/addFeature()` → **图层 edit buffer**（`QgsVectorLayer::updateFeature` 无 `mEditBuffer` 直接返回 false，`src/core/vector/qgsvectorlayer.cpp:1373-1376`） | `qgsvectorlayerfeaturepool.cpp:109-135` |
| `QgsVectorDataProviderFeaturePool` | `dataProvider()->changeGeometryValues()+changeAttributeValues()/deleteFeatures()/addFeatures()` → **直接写 provider** | `qgsvectordataproviderfeaturepool.cpp:126-164` |

两条路径都经 `QgsThreadingUtils::runOnMainThread` 派发（同文件，44/81/114/128、
65/101/142/157 行）——桥接层必须保证主线程事件循环可用（现有桥已是 Qt 主线程
模型，满足）。桌面检查器对话框走 provider 池（setup tab 468 行），
app 实时校验服务走图层池（`qgsgeometryvalidationservice.cpp:408`）。

**对本项目的含义**：基线文档明确镜像层从不 `startEditing()`、更新走 provider
增量重发——所以桥内应选 **`QgsVectorDataProviderFeaturePool`**，修复直接落
memory provider，再由既有 `snapshot_layers/mirror` 链路回推 Python 权威会话
（若要求修复也过 Python 撤销栈，可在桥暴露 fix API 时改为回调 Python 落账，
错误对象本身不关心写路径）。

## 4. 缝隙检查语义（"must not have gaps"）

### 4.1 analysis 版算法（`qgsgeometrygapcheck.cpp:60-220`）

层内全部面（跨所有参与层）做 GEOS `combine` 联合（126 行）→ 取联合的
envelope 再 buffer(2, 0, Square, Miter)（146 行，即外扩 2 单位的矩形）→
`difference(envelope, union)` 得候选缝隙多边形集（152 行）→ 逐部件过滤：

1. **外环带豁免**：`gapGeom->boundingBox().snappedToGrid(tolerance) ==
   envelope->boundingBox().snappedToGrid(tolerance)` 则跳过
   （170-174 行，注释 "Skip the gap between features and boundingbox"）；
2. **面积过滤**：`area > gapThreshold`（配置键 `gapThreshold`，>0 时生效）或
   `area < reducedTolerance`（碎屑）跳过（177-180 行）。**注意方向**：
   `gapThreshold` 是"最大接受面积"——比它大的缝隙被放过，不是被报
   （`qgsgeometrygapcheck.h:102-106` 文档原文 "Any gaps which are larger
   than this area are accepted"）；
3. **邻接判定**：对 bbox 相交（空间索引）且 `distance(gap, feature) < tolerance`
   的面收集为 `neighbors`（185-202 行）——错误带完整邻居表；
4. **豁免层**：`allowedGapsEnabled/allowedGapsLayer/allowedGapsBuffer` 三个配置键
   在 `prepare()` 解析出豁免源层（41-58 行），豁免面 buffer 后取联合
   （70-97 行），`contains(gap)` 则跳过（209-212 行）。

错误 = `QgsGeometryGapCheckError(缝隙几何, 邻居表, 面积, bbox...)`
（217 行，`layerId=""`、`featureId=FID_NULL`——缝隙不属于任何要素，
`qgsgeometrygapcheck.h:41-48`）。

### 4.2 对相图（铺满工区的面镶嵌）意味着什么：**工区边界开口不算缝隙**

判定基准是**数据自身联合的外包矩形**，不是配置的工区范围。与外侧 2 单位
缓冲带连通的开口会与缓冲带合并成一个部件，其 bbox == envelope bbox → 被
规则 1 豁免。因此：

- 相图内部的洞（被相带完全包围）→ 报缝隙 ✔
- 相图外缘缺一块（开口与数据外边界连通）→ **不报** ✘
- 工区为矩形但相图缺角/缺边 → 通常不报（除非缺口四面被相带围死）✘

**若规格要求"铺满工区"，必须补一层自制检查**：`工区多边形.difference(union)`
即外缘缺口，纯 QgsGeometry 运算即可（桥内已有几何算子管道）；或把工区矩形
作为一个"参考面"参与 gap 检查不可行（它自己会被当数据）。这一点桌面版同样
做不到，属我们需在 #1284 中自定义的语义。

**可配置豁免（边界环）**：桌面级豁免即 §4.1-4 的 allowedGaps 机制——豁免层
+ 豁免 buffer，UI 在「图层属性→数字化」暴露（`src/app/qgsvectorlayerdigitizingproperties.cpp:108-121,166-169`
读写同三个配置键）。修复方法 `AddToAllowedGaps` 会把缝隙几何写进豁免层
（`qgsgeometrygapcheck.cpp:252-280`），实现"永久忽略此类缝隙"。

### 4.3 修复方法（`qgsgeometrygapcheck.cpp:464-478,222-322`）

| 方法 | 语义 |
|---|---|
| `MergeLongestEdge` | 并入共享边最长的邻居（含缝隙顶点吸附到邻居顶点，401-429 行） |
| `MergeLargestArea` | 并入面积最大的邻居 |
| `CreateNewFeature` | 用缝隙几何新建要素（282-305 行） |
| `AddToAllowedGaps` | 写入豁免层（需豁免层可编辑） |
| `NoChange` | 标记已处理不动几何 |

## 5. QgsCheckValidityAlgorithm（批量有效性）

`src/analysis/processing/qgsalgorithmcheckvalidity.cpp`（QGIS 4.2 新写法，
旧版是 Python `scripts/CheckValidity.py` 逻辑迁入）：

- **输入**：`INPUT_LAYER`（任意几何矢量源）、`METHOD`（枚举 0=跟随数字化
  设置 /1=QGIS /2=GEOS，85-95 行）、`IGNORE_RING_SELF_INTERSECTION`
  （布尔，97 行）。
- **输出**（98-103 行）：三个可选 sink——`VALID_OUTPUT`（原要素）、
  `INVALID_OUTPUT`（原要素 + 追加 `_errors` 字符串字段拼接全部错误文本，
  130-133、190-195 行）、`ERROR_OUTPUT`（点几何 + `message` 字段，逐错误
  一条，135-138、174-188 行），外加 `VALID_COUNT/INVALID_COUNT/ERROR_COUNT`
  三个数字。
- **核心逻辑只有一行**：`geom.validateGeometry(errors, engine, flags)`
  （165 行）——这是 **core 库 `QgsGeometry` 的方法**，processing 框架只提供
  参数解析、sink 管道和进度。`flags = AllowSelfTouchingHoles` 当且仅当
  忽略环自相交（125 行）。
- **不跑 processing 完全可行**：直接对要素循环调
  `QgsGeometry::validateGeometry(QVector<QgsGeometry::Error>&, engine, flags)`
  即可，错误对象含 `where()`（位置点）与 `what()`（消息）。基线已确认桥的
  `geometry_service` 暴露了 `validate`（基线 §4"makeValid/validateGeometry——
  桥接已暴露"）。analysis 的 `QgsGeometryIsValidCheck` 是同一能力的
  QgsGeometryCheck 封装（错误进统一面板模型，但 `resolutionMethods()` 为空、
  无自动修复，`qgsgeometryisvalidcheck.cpp:62-64`）。

## 6. 倾向性选型

**结论：直接用 analysis 检查器体系 + 自制面板（桥暴露 check 运行 API），
不移植任何插件代码。** 理由：

1. **插件无可搬之物**：geometry_checker 插件的检查与修复 100% 在 analysis
   （§2.1），其私有价值只剩 UI；topology 插件是能力更弱的平行实现
   （gap 检查启发式跳部件、缝隙/重叠无修复，§2.2），搬它等于引入退化版。
2. **analysis 框架零 app 依赖且已在链上**：全部 23 个检查类、错误模型、
   修复编排（含修复后局部复查闭环）都在 `qgis_analysis`（基线 §6 确认已链），
   只需 core+gui+analysis。
3. **枚举/配置问题有现成答案**：`QgsGeometryCheckFactoryT<T>` 模板 +
   `QgsAnalysis::geometryCheckRegistry()`（§1.2）十几行即可把需要的检查
   全量注册，面板按 `geometryCheckFactories()` 动态列检查项，配置统一走
   `QVariantMap`（各检查的配置键见其头文件文档，如 gap 的 `gapThreshold`）。
4. **修复落地路径可选**：provider 池直接写镜像层（与镜像架构一致），或桥
   只跑 `check->fixError()` 的几何计算、把 `Changes` 回传 Python 会话落账
   进撤销栈（错误模型对写路径透明，§3.3）。
5. 自制面板的唯一真实工作量是 UI（错误列表、缩放定位、修复选择），数据
   全部由 `errorAdded/errorUpdated` 信号 + `QgsGeometryCheckError` 访问器供给。

## 7. 对检查器产品规格票 #1284 的直接含义

1. **检查项目录直接采用 §1.1 清单**；首发建议聚焦相图场景四件套：
   `QgsGeometryGapCheck`（缝隙）、`QgsGeometryOverlapCheck`（重叠，配置键
   `maxOverlapArea`，`qgsgeometryoverlapcheck.cpp:31,96`）、
   `QgsGeometryMissingVertexCheck`（共享边缺节点，配合拓扑编辑）、
   `QgsGeometryIsValidCheck`/`validateGeometry`（有效性，已有）。悬挂点
   `QgsGeometryDangleCheck` 仅检测（唯一修复是 NoChange，
   `qgsgeometrydanglecheck.cpp:123-135`）——规格中的"自动收口悬挂点"需自制
   修复（拓扑插件的删除式修复 `topolError.cpp:188-193` 可作参考但不建议照搬）。
2. **运行 API 形状**：桥暴露 `run_checks(layerIds, checkConfigs, precision)` →
   组装 `QgsVectorDataProviderFeaturePool` + `QgsGeometryCheckContext` +
   `QgsGeometryChecker`，`execute()` 的 QFuture 完成后经
   `errorAdded`/`errorUpdated` 序列化回 Python（错误：checkId、layer/feature、
   geometry WKT/GeoJSON、value、bbox、neighbors、status）。参考组装代码：
   `qgsgeometrycheckersetuptab.cpp:465-489`。
3. **容差口径**：面板让用户设 `precision`（小数位），框架换算
   `tolerance=10^-precision`（`qgsgeometrycheckcontext.h:36,53`）；缝隙/重叠
   的面积比较用 `reducedTolerance`（10^(-precision/2)），规格中的阈值单位
   统一为"地图单位平方"。
4. **缝隙语义必须在规格中显式定义**：(a) QGIS 原生 gap 检查不报外缘开口
   （§4.2）——"铺满工区"需补 `工区面.difference(union)` 自制检查，建议把
   工区多边形作为图层级元数据参与校验；(b) `gapThreshold` 是"大于此面积
   的缝隙不报"，命名勿歧义（建议 UI 文案"忽略大于 X 的缝隙"）；
   (c) 豁免环用 `allowedGapsEnabled/allowedGapsLayer/allowedGapsBuffer` 三键，
   修复项 `AddToAllowedGaps` 可作为"忽略此类缝隙"交互。
5. **修复面板**：每检查 `availableResolutionMethods()` 动态出按钮；
   `fixError` 返回后错误状态机驱动 UI（Fixed/Failed/Obsolete 三色）；
   `changes` 可用于审计日志（`EditDelta` 风格）。若要修复进 Python 撤销栈，
   桥暴露"计算修复"（拿到 `Changes` + 新几何）而非直接写层，由
   `SetGeometryCommand`-类命令落账——与基线 §1 编辑权威模型一致。
6. **线程模型**：`collectErrors` 可并行（QtConcurrent），`fixError`/池写入
   必须主线程（`qgsgeometrycheck.h:287`、§3.3）——桥已有主线程派发惯例。
7. **不必接 processing**：批量有效性直接 `QgsGeometry::validateGeometry`
   （§5）；如未来要输出"无效要素图层"，按 `_errors` 字段约定即可。

## 附：关键文件速查

- 框架核心：`third_party/qgis/src/analysis/vector/geometry_checker/`
  （`qgsgeometrycheck.h`、`qgsgeometrycheckerror.h`、`qgsgeometrychecker.cpp`、
  `qgsgeometrycheckregistry.*`、`qgsgeometrycheckfactory.h`、
  `qgsgeometrycheckcontext.h`、`qgsfeaturepool.h` 及两种池实现）
- 注册点：`third_party/qgis/src/analysis/qgsanalysis.cpp:45-49`
- 缝隙：`qgsgeometrygapcheck.cpp:60-220`（检测）、`:222-322`（修复）、
  `:464-478`（方法表）
- 重叠：`qgsgeometryoverlapcheck.cpp:36-102`（检测，`overlaps()`+`intersection()`）、
  `:104-` 起（修复 Subtract 等）
- 悬挂点：`qgsgeometrydanglecheck.cpp:24-121`
- 有效性算法：`third_party/qgis/src/analysis/processing/qgsalgorithmcheckvalidity.cpp:106-267`
- 插件（仅参考）：`third_party/qgis/src/plugins/geometry_checker/`、
  `third_party/qgis/src/plugins/topology/`
