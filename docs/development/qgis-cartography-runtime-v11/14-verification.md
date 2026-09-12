# 14 — Verification (V11)

## 1. 本地验证矩阵

| 族 | 文件 | 结果 |
|---|---|---|
| ordering | test_layer_order_v11 | 19 passed |
| plan | test_layer_tree_plan_v11 | 17 passed |
| diff | test_layer_tree_diff_v11 | 17 passed |
| reconcile 结构 | test_layer_tree_reconcile_v11 | 8 passed |
| native 事务 | test_tree_transaction_v11 | 10 passed（bridge） |
| 顺序平价 | test_layer_order_parity_v11 | 4 passed（bridge） |
| 五目标 | test_edit_targets_v11 | 5 passed |
| scale 结构 | test_runtime_scale_v11 | 8 passed |
| M0 拓扑 | test_topology_m0_v11 | 14 passed |
| lifecycle | test_mirror_lifecycle_v11 | 9 passed |
| 既有回归 | layer-groups/workspace/stage/facies/v10-edit/mirror | 全绿（bridge 环境） |

V11 新增测试：111（19+17+17+8+10+4+5+8+14+9）。

## 2. 回归命令（bridge 环境）

```
PALEO_QGIS_BUILD_DIR=C:\Users\wangj.KEVIN\paleo-qgis-build\qgis-vendor
PALEO_QGIS_CONDA_QT=1 QT_QPA_PLATFORM=offscreen
.venv/Scripts/python.exe -m pytest <files> -q --timeout=60 -p no:cacheprovider
```

## 3. C++ 构建状态

bridge 0.7.0a0：本机增量构建（REUSE_VENDOR=1，~2min）+ 符号/行为验证。
vendor QGIS 本体未重建（neutral 构建复用）。Linux 未验证（PR 声明）。
