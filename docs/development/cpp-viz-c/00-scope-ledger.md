# VIZ-C 井震联合 3D + store 并发收口 — scope ledger

- 基线：origin/main `7290f72728c0b6ff04c33a573cb0e964e3b5ff58`（worktree `codex/viz-c-joint3d`）
- 任务：V4 批次（well_seismic_3d 剩余 → libs/geo3d_viz 扩展 + SceneTransform 接通）+ #1380/#1381 store 并发修复
- 排除（已等价覆盖/他线）：相机、对象注册、基础拾取、剖切、GL viewport、workspace 状态基础、SEG-Y 读取、tile cache、通用 job runtime、联合页面/建模页面壳（#1394 UI-09）、profile_2d（不在任务 C 清单）
- 复用：`libs/geo3d_viz`（SceneTransform seam scene_adapter.hpp:75-87）、`libs/seismic_service`（SeismicVolumeService/TileCache）、`libs/seismic_io`（inspect_segy/read_pwbvol_window）、JobCenter/JobOwner
- oracle 源：geo-viz-engine @ 08851951f3bbc0beb90886adf52e1928f4383c16（submodule）

## 迭代账本

| 轮 | 改动 | 验证 | 结果 | 下一步 |
|---|---|---|---|---|
| 1 | 读计划/issues/三线探索报告/Python 源全量 | 文献对照 | 完成 | #1380/#1381 修复 |
| 2 | #1380/#1381 修复：CommitCoordinator+CatalogRepository 全公有方法递归互斥（锁序 coordinator→repository）；WritableSession/PwbDataStore Impl 改为从 sqlite 路径就地构造 repository；submitSegyJob 拆 collect(GUI)/compute(worker 读+落盘)/apply(GUI 发布)并捕获 store shared_ptr；修 GEO3D_VIZ=ON 平台配置的 4 个存量编译缺陷（geo3d_dock.hpp 命名空间/moc、Geo3DDock 前置声明作用域、importSegyDialog version_id 作用域、QTemporaryDir::tempPath→QDir::tempPath）；geo3d widget 测试加 X 错误处理器（坏 GLX 主机软失败→诚实降级路径） | viz_c.store_concurrency 3/3 (MALLOC_CHECK_=3)；data.*/platform.*/geo3d.* 全绿×2；pwb-platform+platform_attribute_ui 链接运行通过 | 通过 | 联合场景核实现 |

## 预存缺陷记录（非本线造成、不修复）

- `integration.attribute_chain`（tests/cpp/integration/test_attribute_chain.cpp:249 `registered_ids.size() == 4`）：纯净 origin/main 同样失败（属性注册计数断言过期，注册数已被 #1369 扩到 10+）。归 seismic/属性线（D）。
- 本机 X 服务器 :1 GLX 损坏（glxinfo 同样 BadValue）；软件 GL 经 Wayland+Mesa llvmpipe 可用（OpenGL 4.6 core, renderer llvmpipe），geo3d.widget_test 真实软件 GL 11/11 通过。
