@echo off
if exist "python-3.10.11-embed-amd64\pythonw.exe" (
    start "" "python-3.10.11-embed-amd64\pythonw.exe" Datahelper.py
) else (
    start "" pythonw Datahelper.py
)
