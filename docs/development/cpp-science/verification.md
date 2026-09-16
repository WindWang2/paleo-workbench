# C 线验证记录（cpp-science-viz 第一轮）

> 状态标记：**已验证** = 本轮实际执行并附输出；**blocked-on-memory** = 因共享资源
> 门禁（≥8 GiB）拒绝而尚未执行的步骤——机器可用内存长期 ~4.3–4.8 GiB（桌面应用
> 稳态占用；Available≈Free，非门禁度量缺陷，诊断见 handoff §6）。
> 门禁拒绝记录均为真实 exit 75，未把 75 计为任何测试结果。

## 1. Oracle 逐项状态

| # | Oracle | 状态 | 证据 |
|---|---|---|---|
| O1 | 独立 configure/build 退出码 0；核心无 Python/Qt Widgets/QGIS | blocked-on-memory（configure/build 未获门禁放行） | MSVC `/Zs` 语法检查核心 4 库文件 + 4 测试文件 EXIT=0；O6 静态检查通过（见 §3） |
| O2 | 真实算法 Python 对照（容差+异常/取消/近似） | fixture 侧已验证；C++ 比对 blocked-on-memory | oracle 7 case 生成成功（含真实 tiny.sgy ×2 参数组），生成输出见 §2 |
| O3 | task runtime 三分支 + provenance + 取消不伪成功 | 代码+自审查完成；ctest blocked-on-memory | 用例清单 test-plan §3（7 用例含 e2e 真算法） |
| O4 | 真实 WLE Qt adapter 渲染/选择/关闭 | blocked-on-memory | WLE@f845e7ab 子模块就绪；Qt 6.9.2 conda base 开发配置定位完成 |
| O5 | 三轴切片 oracle + 生命周期 | fixture 侧已验证；ctest blocked-on-memory | tiny.sgy crossline-major + 三轴 expected + indexed8 oracle 生成成功 |
| O6 | 生产路径无 PySide/Shiboken/pybind GUI；无重复地图栈 | **已验证** | §3 grep 输出：核心命中仅 2 处注释文字；无 layer tree/地图渲染代码 |
| O7 | CTest 有测试且必选组无失败 | blocked-on-memory | 测试注册 4+1 项（science.contracts / science.algorithms.coherence_c3_oracle / science.workflow.task_runtime / science.seismic.slice / opt-in science.viewer.well_log） |
| O8 | 文档矩阵 + review 修复 + 提交 | 文档已交付；review 第一轮完成并修复 3 处 | 本目录 4+2 文档；自审查修复：task_runtime 持锁发布×2、析构语义注释；提交见 §4 |

## 2. Python oracle 实际输出（fixture 生成，已验证）

coherence_c3（oracle = geoviz_seismic.attributes.compute_coherence_c3@08851951，numpy 路径）：

```
synth_default:      shape=(24,20,40) win=(5,5,5)  n=19200  min=0.6715 max=0.9843 mean=0.9195
synth_asym_window:  shape=(24,20,40) win=(3,7,2)  n=19200  min=0.8735 max=0.9924 mean=0.9593
synth_small_dims:   shape=(4,3,9)    win=(5,5,5)  n=108    min=0.9764 max=0.9946 mean=0.9884
synth_constant:     shape=(8,8,16)   win=(3,3,3)  n=1024   min=max=0.99999976（float32 幂迭代漂移，非精确 1.0）
synth_nan_region:   shape=(8,8,16)   win=(2,2,2)  n=1024   min=0.8723 max=1.0（NaN 窗→1.0 路径）
tiny_sgy_real_w3:   shape=(8,8,32)   win=(3,3,3)  n=2048   min=0.1895 max=0.5668 mean=0.2951
tiny_sgy_real_w1x1x5: shape=(8,8,32) win=(1,1,5)  n=2048   min=0.2155 max=0.7148 mean=0.3812
```

seismic（oracle = geoviz_seismic.loader + native_backend._py_fast_slice_to_indexed8@671ee426）：

```
tiny_sgy: shape=(8,8,32) dt=2ms iline/xline 1..8 step 1，存储为 crossline-major（置换 strides）
indexed8 自动拉伸范围 = (-2.167734146118164, 2.459895610809326)
```

容差：`max_abs_diff ≤ 2e-3`（冻结于 00-baseline §5；C++ 实测值在构建放行后回填本节）。

**实际 case 数**（写死在测试中，构建后以 ctest 输出复核）：
- 数值对照 7 case（上表全部）+ 全零体精确 1.0 断言 1 case；
- 异常输入 4 case（win_il=0 / win_xl=-3 / win_t="abc" / 版本不匹配）；
- 取消 2 case（预置 stop / progress 回调中取消）；
- 近似标记 1 case（descriptor+provenance.approximate）；
- 进度单调+终值 1.0 1 case；确定性重跑位一致 1 case。

## 3. O6 静态检查实际命令与输出（已验证）

```
$ grep -rn "PySide\|Shiboken\|pybind\|Python\.h\|QWidget\|QGIS\|qgs" \
    libs/algorithms libs/workflow libs/visualization/include \
    libs/visualization/src/seismic_volume.cpp -il
libs/algorithms\include\pwb\science\types.hpp        → 命中行为注释（"no QWidget/Python/QGIS headers"）
libs/visualization/include/pwb/viz/selection.hpp     → 命中行为注释（"without dragging QWidget/Python/QGIS types"）
（无其它命中；核心源零代码级引用）

$ grep -rn "layer_tree\|LayerTree\|map_render\|MapRender\|gsMapLayer" libs/ -i
（空——未引入第二 GIS layer tree / 地图渲染栈）
```

PySide/Shiboken/pybind 仅存在于 `tests/cpp/science/oracle/*.py`（oracle 工具，非生产
目标）与 WLE 子模块自身（未构建 Python 绑定，WELLLOG_BUILD_PYTHON=OFF）。

## 4. 提交

- `013d9354` feat(science): C-line first-round sources, frozen oracle fixtures, C0 docs
  （源码 33 文件 + fixture 二进制/manifest + C0 四文档 + 账本）
- 后续提交见 git log（verification 回填后）。

## 5. 构建放行后的既定验证序列（复验两遍关键项）

```powershell
# 1) 核心（Qt-free）
& ./scripts/cpp-migration/Invoke-ResourceGate.ps1 -Action Configure `
    -SourceDir ./libs/science_suite -BuildDir ./build/cpp-science `
    -CmakeArguments @('-G','Ninja','-DPWB_SCIENCE_BUILD_TESTS=ON')
& ./scripts/cpp-migration/Invoke-ResourceGate.ps1 -Action Build -BuildDir ./build/cpp-science
& ./scripts/cpp-migration/Invoke-ResourceGate.ps1 -Action Test -BuildDir ./build/cpp-science `
    -TestRegex '^science\.(contracts|algorithms|workflow|seismic)\.'
# 2) viewer（真实 WLE + conda base Qt 6.9.2）
& ./scripts/cpp-migration/Invoke-ResourceGate.ps1 -Action Configure `
    -SourceDir ./libs/science_suite -BuildDir ./build/cpp-science-viewer `
    -CmakeArguments @('-G','Ninja','-DPWB_SCIENCE_VIEWER_TESTS=ON',
                      '-DCMAKE_PREFIX_PATH=C:/ProgramData/anaconda3/Library')
... Build/Test 同上（TestRegex '^science\.viewer\.')
# 3) 关键复验：coherence oracle + seismic + task_runtime 各再跑一遍（ctest --rerun-failed 或整组重跑）
```

工具链：VS2022 MSVC 14.38 + VS 自带 CMake/Ninja（路径见 handoff）。
