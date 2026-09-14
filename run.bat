@echo off
REM Launch Paleo Workbench.
REM
REM Preference order:
REM   1. the project's own uv-managed .venv  -- the ONLY environment this
REM      checkout is configured for (PySide6 pinned to the Qt the vendored QGIS
REM      bridge links, editable native extensions, vendored-QGIS DLL paths)
REM   2. a conda env at %USERPROFILE%\.conda\envs\py312  -- legacy fallback,
REM      kept only for machines that never created .venv. On this machine that
REM      env is PySide6 6.6.3 with no vendored-QGIS bridge and no osgeo, so the
REM      canvas runs on the fallback renderer.
REM   3. whatever `python` resolves to on PATH
REM
REM It goes through run_app.py rather than -m paleo_workbench.main because the
REM process can fault (0xC0000005) during CPython/Qt finalization after exec()
REM returns. run_app.py lets the app's own aboutToQuit cleanup run, then exits
REM without the crashing interpreter teardown, and writes .workbuddy\gui_run.log
REM + .workbuddy\gui_crash.log so a real failure is diagnosable instead of a
REM silent flash. See run_app.py for details.
REM
REM Control flow uses labels, never parenthesised blocks, around %ERRORLEVEL%:
REM inside a block cmd expands it while PARSING the block, i.e. before the
REM command on the preceding line has run, so the exit code read there is
REM always stale.
setlocal
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PY%" goto use_venv

set "CONDA_PY=%USERPROFILE%\.conda\envs\py312\python.exe"
if exist "%CONDA_PY%" goto use_conda

echo [run] no .venv and no conda py312 env found; falling back to PATH python
python -m paleo_workbench.main %*
goto report


:use_venv
echo [run] using %VENV_PY%
"%VENV_PY%" run_app.py %*
goto report


:use_conda
echo [run] .venv not found at "%VENV_PY%"
echo [run] falling back to %CONDA_PY%
echo [run] WARNING: that is NOT this checkout's configured environment.
echo [run]          Expect PySide6 / Qt version mismatches, no vendored-QGIS
echo [run]          bridge and no osgeo; the canvas will use the fallback.
"%CONDA_PY%" -m paleo_workbench.main %*
goto report


:report
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" goto ok
if %RC% LSS 0 goto crashed
echo [run] exited with code %RC%
pause
goto end


:crashed
echo [run] crashed with code %RC%
echo [run] crash stack : .workbuddy\gui_crash.log
echo [run] run timeline: .workbuddy\gui_run.log
pause
goto end


:ok
echo [run] exited cleanly


:end
endlocal
