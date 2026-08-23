@echo off
cd /d "%~dp0"
echo Starting Paleo Workbench...
python -m paleo_workbench.main
if errorlevel 1 pause
