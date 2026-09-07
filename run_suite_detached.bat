@echo off
set QT_QPA_PLATFORM=offscreen
cd /d C:/Users/wangj.KEVIN/projects/paleo-workbench/.worktrees/qgis-native-authoring-v7
.venv\Scripts\python.exe -m pytest tests/ -q --ignore=tests\perf --ignore=tests\test_theme_and_sidebar.py -m "not slow and not opengl" --timeout=300 -rf --tb=no > C:/Users/wangj.KEVIN/projects/paleo-workbench/.worktrees/qgis-native-authoring-v7\scratch_full_tests.log 2>&1
echo PYTEST_EXIT=%ERRORLEVEL% >> C:/Users/wangj.KEVIN/projects/paleo-workbench/.worktrees/qgis-native-authoring-v7\scratch_full_tests.log
