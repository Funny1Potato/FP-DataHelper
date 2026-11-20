@echo off
if exist "%~dp0python-3.10.11-embed-amd64\pythonw.exe" (
    start "" "%~dp0python-3.10.11-embed-amd64\pythonw.exe" "%~dp0Datahelper.py"
) else (
    start "" pythonw "%~dp0Datahelper.py"
)
