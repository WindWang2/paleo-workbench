# CPP-A 构建与运行说明

## 前置（本机已核验，见 00-baseline.md）

VS2022 MSVC 14.38.33130、Windows SDK 10.0.22621.0、Qt 6.8.0 msvc2022_64、
QGIS vendor SDK（主仓 install tree）、CMake 3.27 + Ninja（VS 内置）。

## 命令（在 platform worktree 根目录）

所有重活经共享资源门禁（单槽、2 jobs、≥8 GiB 空闲内存、exit 75=资源拒绝非失败）：

```powershell
# 探测（锁 + 内存）
powershell -File scripts/cpp-migration/Invoke-PlatformBuild.ps1 -Action Probe

# 配置/构建/测试（MSVC 环境由包装脚本手工组装，reg.exe 黑名单规避）
powershell -File scripts/cpp-migration/Invoke-PlatformBuild.ps1 -Action Configure -Configuration Debug
powershell -File scripts/cpp-migration/Invoke-PlatformBuild.ps1 -Action Build -Configuration Debug
powershell -File scripts/cpp-migration/Invoke-PlatformBuild.ps1 -Action Test -Configuration Debug -TestRegex '^platform\.'
```

等价裸门禁（环境自备 cmake/ninja/MSVC 时）：

```powershell
& ./scripts/cpp-migration/Invoke-ResourceGate.ps1 -Action Configure -SourceDir . -BuildDir ./build/cpp-platform -CmakeArguments @('-DPWB_BUILD_DATA=OFF')
```

## 交互运行

```powershell
$env:PATH = "C:/deps/Qt/6.8.0/msvc2022_64/bin;<qgis-sdk>/bin;" + $env:PATH
./build/cpp-platform/pwb-platform.exe
```

## Headless 自检（CTest platform.qgis_smoke_app 同路径）

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
./build/cpp-platform/pwb-platform.exe --self-check   # 退出码 0 = 全绿
```

## 链接审计（Oracle 1）

```powershell
dumpbin /dependents build/cpp-platform/pwb-platform.exe | findstr /i "python pyside shiboken qgis_render_bridge"
# 期望：0 命中
```
