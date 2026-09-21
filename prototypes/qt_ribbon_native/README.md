# Paleo Workbench · 原生 Qt Ribbon 交互原型

独立 C++17 / Qt 6 Widgets 程序。基于[五工作区 Ribbon 设计](../../docs/ui-redesign/qt-ribbon-workspaces-2026-09-21/README.md)，不修改当前生产主程序、真实工程或 catalog。

## 运行

Windows 双击 **Start Prototype.cmd**，或执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File prototypes/qt_ribbon_native/run.ps1
```

本机使用 `C:/deps/Qt/6.8.0/msvc2022_64`。其它 SDK 路径可通过 `-QtRoot` 指定。首次缺少可执行文件时自动编译，需要 VS2022 C++ 工具及 CMake；已有构建后只启动 GUI。`run.ps1` 设置当前子进程的 Qt DLL 和插件路径，不修改系统环境。

## 可体验的流程

1. 切换五工作区：数据管理、智能预测、约束与单因素、综合编图、验证。
2. 数据页搜索/分类筛选、选择行查看元信息。导入文件或扫描目录只登记元信息，不解析、不移动原文件；科学预览始终明确为合成数据。
3. 地图滚轮缩放、拖动平移、点击井点；井选择同步到各页及合成测井曲线。层位标签与状态栏下拉同步。
4. 右侧图层开关、透明度滑块；所有dock可关闭/浮动/重新停靠。文件→面板可重新打开和恢复布局。
5. Ribbon折叠（Ctrl+F1/双击活动标签）、紧凑模式、命令搜索（Ctrl+K）。Ribbon与工作流入口调用同一命令。
6. 运行预测/单因素/验证为约2秒的模拟任务，有进度、取消和重复提交保护，不生成实际科学结果。
7. 综合编图下方五个参考缩略图可选；缩略图由合成标量场绘制，主成果不被替换。
8. 验证问题点击定位井；井相带图支持并排/叠加/差异。填写备注后可记录复核，保留原检查结论，不假装通过。
9. 保存/打开原型JSON状态，恢复工作区、井、层位、Ribbon模式和复核记录。导出CSV包含真实当前表格或问题记录，导出PNG保存当前原型视图。

## 明确边界

- 地图底图是生成的设计示意；井坐标、曲线、地震、相带和因子图均为合成示例。没有调用预测模型、QGIS、真实地震体或数据库。
- 几何编辑、模型训练、版本血缘计算、图件模板/版式等次级入口仍为参数/结构演示，不能当作生产功能验收。
- 地震轴为双程时ms，井轴为深度m；本原型不假定时深关系，不把两个数值轴直接联动。
- 图标使用Qt标准图标，与设计图的线性图标还有视觉差异。后续接生产AppShell时应复用项目图标/动作/主题系统。
- 布局偏好保存在独立的 `PaleoWorkbenchPrototype/RibbonQt` QSettings 命名空间；测试不写这些偏好。数据状态仅在用户主动选择路径时写出。

## 构建与验证

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File prototypes/qt_ribbon_native/build.ps1 -Verify
```

独立CMake入口，只构建一个主源文件与资源，不重建仓库或第三方SDK。全程使用仓库资源锁，j1；小原型采用1.5GiB空闲内存准入阈值，锁忙或内存不足返回75。不要直接并行启动多份构建。

`--self-test --output <目录>` 运行Qt交互检查并生成五页截图、1280紧凑/1920宽屏截图、JSON和CSV证据。证据位于 `evidence/`，构建和证据不入Git。测试包括点击井点、筛选、取消、状态恢复、复核备注和导出内容。

## 文件

- `main.cpp`：原生Qt控件、场景交互、合成数据图表、原型状态与自测。
- `assets/facies-demo.png`：设计示意底图，嵌入Qt资源，不将整页设计图当可交互界面。
- `build.ps1` / `run.ps1`：受资源门控制的本机构建与启动。
- `design-qa.md`：实际窗口与参考方案的比对结果、保留差异。
