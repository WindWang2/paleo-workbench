# ADR 0060: Vendored GDAL — 连源码编译进项目，不再依赖系统 GDAL

日期: 2026-08-23
状态: 已实施

## 背景

参考图功能（`paleo_workbench/mapping/reference_layers.py`、`scalar_raster_mirror.py`）依赖
`osgeo.gdal`。此前的安装方式是 pip `gdal>=3.6`：sdist 编译时链接系统 `libgdal`，
CI 再用 `gdal-config` 把版本钉到系统版本。这带来三类持续性问题：

1. **绑定/系统库版本漂移（#851 一类）**：本机系统 libgdal 3.13.3，pip 安装的 osgeo
   绑定版本不一致时 `from osgeo import gdal` 直接 ImportError，进而让
   `mapping_page` 相关测试长期红（参考层用例失败）。
2. **CI 每腿重编 sdist**：Ubuntu runner 系统 GDAL 随镜像漂移，pip 需按
   `gdal-config --version` 现场编译绑定（numpy 預装、约束文件等一整套变通）。
3. **不可复现**：不同机器、不同时间安装出的 GDAL 能力集（驱动、PROJ 数据）不同。

## 决策

**GDAL（连同其必需依赖 PROJ）以 git submodule 源码形式进入项目，用项目内
superbuild 脚本编译到项目内 prefix，运行时完全不查找系统 GDAL。**

- 子模块：`third_party/gdal`（v3.10.3）、`third_party/proj`（9.5.1）。
- 构建脚本：`scripts/build_vendored_gdal.sh`（CMake + Ninja）：
  - PROJ → 前缀安装（禁 curl/tiff/projsync，仅 sqlite 运行数据）；
  - GDAL → 链接刚装的 PROJ，**最小驱动集**（GTiff/COG/VRT + GeoJSON/CSV/Shapefile），
    其余外部库全部走 GDAL 内置副本（`GDAL_USE_EXTERNAL_LIBS=OFF`），
    并在同一前缀编译 **Python osgeo 绑定**（`BUILD_PYTHON_BINDINGS=ON`，
    绑定直接链接本构建的 libgdal）。
- 产物布局（gitignored）：`native/gdal-vendored/build/`（编译树）、
  `native/gdal-vendored/install/`（前缀 + `env.sh`）。
- `env.sh` 导出 `GDAL_DATA`、`LD_LIBRARY_PATH`、`PYTHONPATH`（绑定位于
  `<prefix>/lib/pythonX.Y/site-packages`）。**不导出 `PROJ_DATA`**：vendored libproj
  已内嵌安装前缀可自行找到 proj.db；而 rasterio wheel 自带更新的 libproj，强制
  PROJ_DATA 会让它读到布局不兼容的 vendored proj.db 而 CRSError。
- 接线：
  - `pyproject.toml` 移除 pip `gdal>=3.6` 依赖（osgeo 来自 vendored 构建）；
  - `scripts/run_tests.sh` 存在 `env.sh` 即 source（本地开发自动启用）；
  - `.github/workflows/ci.yml` 与 `slow-tests.yml` 删除 `gdal-bin/libgdal-dev` 安装
    与 pip gdal sdist 编译，改为运行 superbuild 步骤（fail-closed：构建后立即
    `from osgeo import gdal` 冒烟），测试步骤 source `env.sh`。

## 系统依赖边界

superbuild 仍从系统取"无处不在"的构建件：C++17 编译器、CMake、Ninja、sqlite3/zlib
头文件。SWIG **不**用系统的：脚本把 `swig` wheel 装进目标 Python 环境并显式向
CMake 传 `-DSWIG_EXECUTABLE`（PATH 上的残留旧包装器会赢 `find_program`，且 < 4.1
的 SWIG 生成不兼容 Python 3 的 typemap）。同时脚本每次删除过期 `*_wrap.cpp` 保证
重新生成。

**v3.10.3 源码补丁（worktree 内，不提交子模块）**：`swig/include/python/
typemaps_python.i` 含 Python 2 残留 `PyInt_Check` / `PyInt_FromLong`，新 Python
头文件不再声明它们导致包装编译失败；上游 master 已改为 `PyLong_*` 系列。脚本用
sed 幂等应用同一替换：
`s/ || PyInt_Check($input)//g; s/PyInt_FromLong/PyLong_FromLong/g;
s/PyInt_AsLong/PyLong_AsLong/g`。升级到 ≥3.11 子模块后 grep 落空即自动跳过。

## 后果

- 正面：osgeo 与 libgdal 永远同源同版本；参考层测试不再受系统 GDAL 漂移影响；
  CI 安装步骤变薄；GDAL 能力集（驱动）在所有机器一致且显式。
- 负面/成本：CI 每腿增加一次 vendored 编译（Release 最小驱动集，可接受；
  后续可加 ccache/action 缓存优化）；克隆体积增加两个浅子模块；GDAL 升级
  变成显式的子模块 re-pin。
- 范围外：`qgis-renderer.yml` 构建 vendored QGIS 时链接系统 `libgdal-dev`——那是
  QGIS C++ 构建冒烟腿自身的依赖面，与本项目运行时 osgeo 无关，保持原状
  （后续若要统一，可让该腿也消费同一前缀，另立决策）。
- `rasterio` 依赖仍在（其自带 manylinux wheel，链接自带的 libgdal，不受影响；
  若未来要统一为同一 libgdal 需另行评估）。
