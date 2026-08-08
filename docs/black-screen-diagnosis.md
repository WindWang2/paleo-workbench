# WellLogView Wayland 黑屏问题诊断报告

## 现象
- WellPlot Desktop（Python/PySide6）在 Wayland 下，引擎视图（`WellLogView`，
  QOpenGLWidget 子类）显示**全黑**
- xcb 下完全正常
- 同一份引擎源码，C++ 直接实例化（`scripts/gl_debug_repro`）在 Wayland 下
  **完全正常**（白底+曲线）

## 排除项（全部实验验证过）

| 假设 | 结论 | 验证方式 |
|------|------|----------|
| 空场景/无数据 | ❌ 排除 | demo 井已加载，FBO readback 有曲线 |
| GL 上下文/驱动不可用 | ❌ 排除 | ctx 有效（GL 4.6），capability 检查通过 |
| Wayland 下 QOpenGLWidget 普遍失效 | ❌ 排除 | 最小 PySide6 QOpenGLWidget 全屏 glClear 蓝色能显示 |
| backing store 缺 alpha | ❌ 排除 | 设 alpha=8 仍黑 |
| FBO alpha 被写成 0 | ❌ 排除 | glReadPixels alpha=255 全不透明 |
| stencil<8 被引擎拒绝绘制 | ❌ 排除 | 两平台都是 8，capability graphics_available=1 |
| 误绑定 FBO 0 | ❌ 排除 | 用的是 defaultFramebufferObject() |
| scissor 状态泄漏 | ❌ 排除 | 末尾正常关闭，区间内无提前 return |
| paintGL 未被调用 | ❌ 排除 | stderr 计数器确认两边都调用 |
| frameSwapped 未触发 | ❌ 排除 | Python 下也触发 4 次/3s |
| Qt 实例混用 | ❌ 排除 | /proc/self/maps 确认进程内只有一套 Qt |
| Qt 二进制差异 | ❌ 排除 | LD_PRELOAD 系统 Qt 仍黑 |
| HiDPI/DPR | ❌ 排除 | C++ 在 DPR=2.0 下正常 |
| GL 状态恢复（paintGL 末尾重置） | ❌ 无效 | 加了 glBindFramebuffer/use(0)/disable(blend) 仍黑 |
| shiboken typesystem 移除 paintEvent 覆盖 | ❌ 无效 | remove="all" 后仍黑 |
| QOpenGLWindow + createWindowContainer | ❌ 无效 | Wayland 下嵌入式 GL 子窗口也有呈现问题 |

## 剩余差异（唯一未排除的方向）

C++ repro 和 Python 的唯一本质区别：**shiboken 生成的 `WellLogViewWrapper`**。

wrapper 对 WellLogView 做了：
1. 重写**所有** virtual（paintEvent/paintGL/resizeGL/actionEvent/...共 50+ 个），
   每个都经过 `Sbk_GetPyOverride` + `GilState` 分派层
2. 重写 `metaObject()` / `qt_metacall()` / `qt_metacast()`
   （Qt moc 元对象系统，QOpenGLWidget 合成可能经过此路径）

即使没有 Python 覆盖（走 C++ 原版），wrapper 的 vtable 存在和 GIL
管理可能改变 Wayland 合成的时序或线程状态。

shiboken wrapper 源码位置：
`build/env-gate-debug/welllog/_QtWidgets/welllog_welllogview_wrapper.{h,cpp}`

## 已尝试但未成功的修复

1. **GL 状态恢复**（`well_log_view.cpp` paintGL 末尾）→ 无效
2. **typesystem `modify-function paintEvent remove="all"`** → 无效
3. **QOpenGLWindow + createWindowContainer** → Wayland 下子窗口 GL 呈现也有问题
4. **LD_PRELOAD 系统 Qt** → 无效

## 建议的后续方向

### A. 深入 shiboken 的 qt_metacall / metaObject
QOpenGLWidget 的 FBO→窗口合成可能通过 QMetaObject::invokeMethod 或
qt_metacall 触发。WellLogViewWrapper 重写了这些——如果合成调用被
wrapper 的 qt_metacall 拦截/重定向，就会断裂。
**验证**：在 wrapper 的 qt_metacall 里加 stderr 打印，对比 C++ 和 Python
的调用序列。

### B. 用 `gdb`/`lldb` 对比调用栈
在 paintGL 末尾打断点，对比 C++ repro 和 Python 的完整调用栈，
找出 shiboken 在 paintEvent→paintGL 路径上插入的额外帧。

### C. 用 `apitrace` / `RenderDoc` 捕获 GL 调用流
对比 C++ 和 Python 进程的完整 GL 调用序列，找出合成阶段的差异
（哪个 glCall 在 Python 下缺失或不同）。

### D. 给 PySide6 提 issue
这是 PySide6 + Wayland + QOpenGLWidget 子类的已知问题域。
最小复现：任何 shiboken 包装的 QOpenGLWidget 子类在 Wayland 下都可能黑屏。

## 复现工程

`scripts/gl_debug_repro/`：独立 CMake 项目，链接引擎预构建库，带完整 GL 诊断
（KHR debug 回调、paintGL 前后状态快照、FBO readback、capability 报告）。

```bash
cd well-log-engine && eval "$(scripts/python_env.sh)" && source scripts/welllog_env.sh
cd ../scripts/gl_debug_repro && "$WELLLOG_CMAKE" --build build --target gl_debug_repro
./build/gl_debug_repro --mode=native --platform=wayland  # C++ 正常
```

## 相关文件

- 引擎视图：`well-log-engine/src/qtwidgets/well_log_view.cpp`
- 渲染器：`well-log-engine/src/render_gl/renderer.cpp`
- shiboken wrapper：`well-log-engine/src/python/typesystem_welllog.xml`
- Python 桥接：`well-log-engine/apps/wellplot-desktop/well_log_workstation/engine_bridge.py`
- 复现工程：`scripts/gl_debug_repro/`
