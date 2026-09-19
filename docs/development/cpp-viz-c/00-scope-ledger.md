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
| 3 | V4 联合核 11 组件（joint_types/depth_transform/survey/registration/well_geometry/volume_access/fence/probe/color_scales/joint_scene/segy_survey）+ 平台桥（TiledVolumeAccess/mesh builders/time map/JointHostController host）+ geo3d_dock joint_host 组合根 + viz_c_joint_example；oracle 生成器跑真实 Python @08851951 冻结 12KB fixture | viz_c.joint_oracle 9/9（含 tampered 检出 + >200 次比较守卫）；viz_c.joint_scene 7/7；全树 111 测试中 109 过（唯二失败 integration.attribute_chain=origin/main 预存、ui_pages_preview.qt_widgets_smoke=#1394 记录的预存环境问题，均与本线零文件交集）；受影响面 38/38×2 轮全绿；MALLOC_CHECK_=3 viz_c+platform 20/20 + data+geo3d 50/50 | 通过 | 三轮审核 |
| 4 | GL 双路径：offscreen GL-less 诚实降级（无截图+场景状态完整+drain）；Wayland+llvmpipe 真软件 GL 截图 1000x750，关键像素：seismic 蓝 3.9%/红 3.9%（对称标尺）、井黄 (242,204,20) 0.28%、41 distinct colors；快照 n_inline=4/n_crossline=4/active 2ms；井间 fence 帘幕+活动切片+双井全部在一致 render 空间 | viz_c_joint_example 双平台功能全通过；**勘误（审核 C）**：修复前退出段 JobOwner 双所有权 UAF 致 exit 139（首次记录 exit 0 有误）；修复（host 内层作用域先于 JobCenter 析构）后 exit 0 | 通过（修复后） | 三轮审核 |
| 5 | 三轮独立审核（A=Python/科学语义、B=C++/Qt 生命周期并发、C=产品接线/构建）并修复：same_time 补 rtol（np.isclose 语义）；fence/probe/rescale 的 llround→nearbyint（Python round half-even）且先 round 后 clamp；colorize P98 float32 量化；clamp_indices 非有限输入 fail-closed；set_orthogonal_slice_indices 保留 None；open_volume any_cast 改指针形式（防空回调抛 bad_any_cast）；QPointer 管 time_map_/volume_owner_ + host 析构解绑 scene；迟到回调 owner 身份检查；X11 改软探测；dock 接线 restore_state；a.out 误提交移除 + .gitignore；示例析构序修复（JobCenter 先于 host 析构，MainWindow 成员序复刻）；readiness_inputs 潜伏 document 竞争以注释记录边界（今日无 rebind 发布路径）；线程契约注释改为如实（GUI 为单读者） | 全量重建通过 | 通过 | 最终验证 |
| 6 | 最终验证：全部 111 测试 109 过（唯二失败均为预存且与本线零文件交集：integration.attribute_chain=origin/main 同败[stash 实测]、ui_pages_preview.qt_widgets_smoke=#1394 记录的宿主环境问题[直接运行二进制 exit 0]）；viz_c 4 项 + 受影响面 64 项 ×2 轮全绿；MALLOC_CHECK_=3 全程；示例 offscreen+wayland 双路径 exit 0 | 见左 | 通过 | 推送 PR |

## 验证证据汇总（截至第 4 轮）

- 构建：全闭包 554→增量（resource gate -j2，flock 全程；等待期多次 RESOURCE_BUSY 退避 30–240s 重试）
- viz_c.store_concurrency 3/3（MALLOC_CHECK_=3）；viz_c.joint_oracle 9/9；viz_c.joint_scene 7/7
- data.* 23、geo3d.* 3、seismic_io.* 3、seismic_service.service、platform.attribute_ui 全过
- GL：软件 GL=Wayland+Mesa llvmpipe（OpenGL 4.6 core）；GLX 损坏主机经 X 错误处理器软失败
- 资源锁竞争记录：与 viz-b（pid 1293096 等）多次互斥等待，均按退避协议处理
