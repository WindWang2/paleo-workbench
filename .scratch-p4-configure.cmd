@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x64 >nul 2>&1
set "CMAKE=C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
cd /d C:\Users\wangj.KEVIN\projects\paleo-workbench-v14-data-fabric-lineage
"%CMAKE%" --preset windows-msvc -DPython3_EXECUTABLE=C:/Users/wangj.KEVIN/projects/paleo-workbench/.venv/Scripts/python.exe -DPWB_QGIS_DEPS_PREFIX=C:/deps/vcpkg/installed/x64-windows -DPWB_SCIENCE_BUILD_VIEWER=ON || exit /b 1
