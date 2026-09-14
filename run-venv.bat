@echo off
REM Launch Paleo Workbench with the project's own uv-managed venv -- strict mode.
REM
REM Difference from run.bat: run.bat falls back to a conda env or PATH python when
REM .venv is missing. This script does not. Use it when you want a hard failure
REM instead of silently running in an environment that is not configured for this
REM checkout (on this machine the conda py312 env is PySide6 6.6.3 with no
REM vendored-QGIS bridge and no osgeo, so the canvas would fall back).
REM
REM We go through run_app.py rather than -m paleo_workbench.main because the
REM process faults (0xC0000005) during CPython/Qt finalization after exec()
REM returns. run_app.py lets the app's own aboutToQuit cleanup run, then exits
REM without the crashing interpreter teardown, and writes the run timeline. See
REM run_app.py for details.
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if exist "%PY%" goto run

echo [run-venv] .venv not found at "%PY%"
echo [run-venv] create it first:  uv venv --python 3.12 .venv
echo [run-venv] then:             uv pip install -r requirements-geoviz.txt
echo [run-venv] then:             uv pip install -e .
pause
endlocal
exit /b 1


:run
echo [run-venv] using %PY%
"%PY%" run_app.py %*
REM NOTE: read %ERRORLEVEL% here, outside any parenthesised block -- inside one
REM cmd expands it while parsing, i.e. before the command above has run.
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" goto ok
REM run_app.py exits hard from inside aboutToQuit, so a negative code means the
REM fault happened *before* shutdown (during startup/running) -- the case worth
REM stopping for. Both logs are rewritten on every launch.
if %RC% LSS 0 goto crashed
echo [run-venv] exited with code %RC%
pause
endlocal
exit /b %RC%


:crashed
echo [run-venv] crashed with code %RC%
echo [run-venv] crash stack : .workbuddy\gui_crash.log
echo [run-venv] run timeline: .workbuddy\gui_run.log
pause
endlocal
exit /b %RC%


:ok
echo [run-venv] exited cleanly
endlocal
exit /b 0
