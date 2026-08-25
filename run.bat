@echo off
cd /d "%~dp0"
echo Starting Paleo Workbench...
if exist "%USERPROFILE%\.conda\envs\py312\python.exe" (
    "%USERPROFILE%\.conda\envs\py312\python.exe" -m paleo_workbench.main %*
) else (
    python -m paleo_workbench.main %*
)
if errorlevel 1 pause
