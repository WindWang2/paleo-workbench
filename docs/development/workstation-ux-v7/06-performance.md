# 06 — Performance（V7 性能）

政策延续 V6：**性能声明 = 结构 bound**（声明性断言），wall-time 仅作上限
护栏；所有预算显式（goal §17 要求「benchmark 必须有显式规模和内存上限」；
无 100GB seismic 相关项）。

## 结构 bound（tests/test_perf_bounds_v7.py，全绿）

| 场景 | 规模 | 结构断言 | 实测 |
|---|---|---|---|
| 同结构重发布 | 1000 图层 | 树行对象复用（无全清重建） | 行身份保持 ✓ |
| 装饰推送 | 200 图层 | 无 rebuild、无 QWidget 创建 | <2s 预算，实际毫秒级 |
| 统一可用性求值 | 1000 图层 | O(1)（读活动层聚合，不遍历） | <1s 预算 |
| 组聚合 | 1000 成员 | 单遍（无嵌套重扫） | <2s 预算 |

## 高频路径处理（评审 R3-F4）

- `extent_changed`（pan/zoom 每帧）：轻路径——仅工具勾选态 + 状态条；
  统一可用性/树装饰与视野无关，不再每 pan 重算（满载 1000 层时原为
  ~27ms/次，超 60fps 预算）。
- 树重载：同结构差分（单元格更新）；`set_layer_decorations` 只写已存在行。
- 任务中心：400ms 轮询差分模型（V6 既有）。
- 主题切换：`style.bind` 注册表重渲染 + 装饰重推（颜色随 palette()）。

## 内存

无新增全量物化路径；装饰/聚合为 O(layers) 临时 dict，随事件丢弃。
live 因子网格缓存沿用既有上限（PALEO_LIVE_FACTOR_GRIDS_MAX=64 /
256MiB）。

## 未做（显式）

- 1000 层的 mirror publish 重序列化（V6 已知项，native-only 路径，
  本环境不可测——保持登记）。
- wall-clock benchmark 套件（结构 bound 覆盖 goal §17 的「无全清重建/
  无逐行 QWidget/无全量物化」要求；GUI wall-time 在 CI 环境噪声过大，
  V5 D8 政策延续）。
