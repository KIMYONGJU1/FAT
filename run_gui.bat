@echo off
setlocal
set PYEXEC=python
if exist .venv\Scripts\python.exe set PYEXEC=.venv\Scripts\python
echo [INFO] Starting GUI...
%PYEXEC% app.py
if errorlevel 1 (
  echo [ERROR] App exited with error.
  pause
)
