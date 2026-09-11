# 08 — 空间查询路径（V10）

## 1. 双路径分工（D14，维持）

| 路径 | 交互命中/捕捉权威 | 依据 |
|---|---|---|
| fallback（Python canvas） | `FeatureSpatialIndex` + `SnappingService` | V8 D3（docs/development/qgis-spatial-authoring-v8/03-decisions.md D3，M4 收敛边界：双索引合并延后——轻量索引已被证明够用） |
| native（桥画布） | `QgsMapToolIdentifyFeature` / `QgsPointLocator`（snapToMap） | QGIS 自带空间索引与捕捉定位器，C++ 热路径 |

两路径各自的语义面：识别（identify）与捕捉（snap）在 fallback 侧
由 Python 服务承担、在 native 侧由 QGIS 工具承担；**同一画布帧内
不存在混用**——画布类型决定路径，路径决定权威，无仲裁层。

分工是**记录在案的边界**，不是待消除的重复：两条路径服务两个
documented gate（fallback 双视觉栈为 V8 裁定保留），各自有权威。

## 2. fallback 的画布坐标系假设成立性

`FeatureSpatialIndex` 的 canvas-frame 假设（索引坐标 = 画布帧坐标）
在 fallback 路径**由构造保证**：fallback 画布是单一 project-CRS-frame
（无 per-canvas destination 重投影面），不存在混合帧查询。V10 的
CRS 链改动（02-crs-transform.md）不触碰 fallback 画布的帧构造，
该假设继续成立。

## 3. 捕捉路径的坐标语义闭环

native 捕捉消费画布帧坐标（`set_destination_crs` 恒推送后不再有
陈旧目标 CRS 帧——02-crs-transform.md §3）；fallback 捕捉
（`SnappingService`）消费 Python 画布帧，per-layer 覆盖在工程重载后
经持久化通道恢复（03-qgsproject-authority.md §3）。两条捕捉路径的
模式词表维持 SnappingService 既有词汇（V9 D5 谱系），本批不发明
第二套模式语言。

## 4. 不新建 Python index

V10 审计复核确认：无需也不新建第二个 Python 空间索引
（00-baseline.md §E 硬排除「不建新面」在查询域的落点）。
native 路径的捕捉/识别全部走 QgsPointLocator/QgsMapToolIdentifyFeature，
Python 侧零平行实现。若未来出现双索引合并诉求，按 V8 D3 的延后裁定
路径重新立项，不在本批夹带。
