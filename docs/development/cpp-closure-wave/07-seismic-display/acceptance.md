# 07 — acceptance

验收基线：origin/main 06211541。每项给出证据位置（测试名/命令/文件），完成后回填。

| # | 验收项 | 证据 | 状态 |
|---|---|---|---|
| A1 | 同一体下模式/极性/增益/clip/色表/切片和 picks 状态保存重开一致 | view_state round-trip 测试（planned: tests/cpp/seismic_viewer） | 未验 |
| A2 | 跨体恢复拒绝错配（不同 volume_id 拒绝应用，状态不变） | view_state mismatch 测试 | 未验 |
| A3 | 导出数组值正确（npy 逐字节 v1.0 头 + 数据回读比对；csv %.6f 无表头） | slice_export 测试（独立头解析器回读） | 未验 |
| A4 | 导出轴和单位正确（行/列与显示面方向一致，坐标经 plane_point_at 校验） | export orientation 测试 | 未验 |
| A5 | PNG 含真实显示（widget.grab 渲染非空、含色表内容而非空白） | png 测试 + offscreen 证据 | 未验 |
| A6 | 无效体/全 NaN/常量面：诚实降级不崩溃（degenerate 状态、融合全零通道、导出错误回报） | negative-path 测试 | 未验 |
| A7 | 取消：导出/读取取消路径不残留脏状态（SliceController epoch 幂等） | controller 回归 + widget 测试 | 未验 |
| A8 | 2D 属性/RGB 融合显示：属性选择→真核计算→面板显示；RGB 融合→三通道 uint8 | attribute fusion 测试 + closure 装配测试 | 未验 |
| A9 | ui_wellseis 真面板绑定：资源选择→真实体→真 viewer（占位退役路径有测试） | closure_seismic 装配测试 | 未验 |
| A10 | 04 可注册的真实 seismic presenter（make_seismic_preview_presenter 真实现、注册词表一致） | viz_d.preview smoke 回归 + findings 记录 | 未验 |
| A11 | 回归：seismic_viewer 5 套件 + viz_d 3 套件 + ui_wellseis 相关套件全绿（≥2 遍确定性回归） | ctest -R 记录 | 未验 |
| A12 | oracle/篡改自检：解析手算用例 + 篡改期望值必须红 | fusion oracle 测试 | 已验（advanced_core fuse_rgb oracle 通道解析值 + 篡改自检（换序/取整）） |
