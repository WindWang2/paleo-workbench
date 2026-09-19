# 06 — findings

## 2026-09-19 盘点轮（base 06211541）

- F1: main_window.cpp:460 `setProperty("pwb_job_center",...)` 落在 MainWindow；
  geo3d_dock.cpp:240 在 Geo3DDock::joint_host() 里读自身 property。QObject property
  不继承 → 产品路径 joint_host() 恒 nullptr，真实 host 从未创建（C 线仅示例直接构造
  host 通过）。归类：viz-c 潜伏缺陷，本线修复（属于本线独占的 geo3d_dock/joint host 范围）。
- F2: app_shell.cpp:180 `joint_host_ = new UnavailableJointHost()` → 页面永远诚实占位。
  真实 host 需从 Geo3DDock 注入；MainWindow 中 app_shell_(L404) 先于 geo3d_dock_(L452)
  创建 → 需具名块顺序调整或 attach API。
- F3: VizCTimeSliceMap::refresh()（viz_c_time_map.cpp:71）GUI 线程 slice_time(active)
  + colorize；set_prepared_slice 接缝已在但仅同步调用。host 的
  assemble_joint_objects（viz_c_joint_host.cpp:575）build_fence_curtain /
  build_active_time_slice 亦 GUI 线程读体（冷 tile = 磁盘读 → UI 冻结）。
- F4: assemble_joint_objects 只渲染 active fence（viz_c_joint_host.cpp:611-620 注释
  自认）。scene 核有 fences() 列表/激活/删除/可见性 API + extract_active_fence 仅
  active。多 fence 需 scene 级 extract_fence(id)（复用 extract 缓存核）。
- F5: save_state/restore_state 用全局 QSettings key（viz_c_joint_host.cpp:26），
  无工程身份 → 工程切换串状态。readiness_inputs（main_window.cpp:3005-3089）
  GUI 直读 store document()（#1380 audit 记录的竞争边界）。
- F6: 示例 viz_c_joint_example 证明 offscreen 无 GL 诚实降级 + wayland llvmpipe
  软件 GL 双路径可用（本机 GLX 损坏，软件 GL 经 Wayland+Mesa llvmpipe）。
- F7: C 线 ledger 记录预存失败（与本线零交集）：integration.attribute_chain（D 线
  断言过期）、ui_pages_preview.qt_widgets_smoke（#1394 宿主环境）。

## 2026-09-19 实施轮补充

- F8: 本机无系统 cmake/ninja（仅 SDK 工具链 /home/kevin/pwb-sdks/root/usr/bin，
  其 cmake 需 LD_LIBRARY_PATH 指向 SDK lib/librhash）。已固化到 /tmp/gate_queue.sh。
- F9: invoke-resource-gate.sh 用 flock -n 探测式获取；兄弟会话（01/13/14 线 agent
  同主机）持续持锁导致轮询饥饿。适配：flock -w 阻塞排队赢得内核等待队列后再
  交还 gate 脚本（同一锁文件，无活跃锁移除，无绕过）。等待窗口记录于 progress。
- F10: QGIS SDK 路径：vendored 源在各 worktree third_party/qgis；vendor 构建产物
  在主工作区 native/qgis_render_bridge/build/qgis-vendor/output（只读复用）。
  sibling-main 默认（~/project/main）在本机不存在，需显式 -D 传入。

## 2026-09-19/20 验证轮

- F11: 冻结语义确认——Python `_sync_well_order_fence` 复用单一 well-order fence
  （井对 fence 不新建）；多 fence = 手绘/持久化 fence 共存。host 新增
  add_fence_vertices（draw-mode 接缝）。井无 TD 表时拒绝井对 fence
  （"无时深" fail-closed，MD 不冒充 TWT）——测试井已带 TD。
- F12: 竞态缺陷（本线修复 #1）：`prep_finished` 曾将 applied 键记为"当前键"，
  cooperative-cancel 下作业可带旧数据"成功完成"→ 收敛环不再重发。改为如实记录
  作业对应请求。
- F13: 崩溃缺陷（本线修复 #2）：`scene_.fences()` 按值返回临时 vector，
  assemble 持其内指针 → 悬垂（垃圾顶点 ±inf → SceneObjectError，约 1/8 复现）。
  改为单次拷贝。修复后 15/15 干净。
- F14: 递归环（本线修复 #3，真实 host 注入后暴露）：页面 on_scene_updated →
  apply_display_settings/sync_joint_visibility → host set_color_scales/
  set_well_width/set_layer_visibility/set_well_visibility → 重发 scene_updated →
  无限递归栈溢出（platform.qgis_smoke_app SEGFAULT）。Python 中显示设置/可见性
  直写 scene 不重发通知——四处 setter 移除重发。
- F15: GL 路径现状：GLX 本次会话可用（glxinfo direct rendering: Yes；C 线期
  GLX 损坏）；xcb 真实 GL 截图 800×600（43 色、地震蓝红 699 采样像素、井黄
  168）；offscreen 无 GL 诚实降级 15/15 exit 0。Wayland 插件因无合成器早期
  崩溃（环境限制，非本线代码）。
