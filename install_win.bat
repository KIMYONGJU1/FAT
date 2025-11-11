@echo off
setlocal
echo [INFO] Creating virtual environment (.venv)...
py -3 -m venv .venv
if errorlevel 1 goto :fail

echo [INFO] Upgrading pip...
call .venv\Scripts\python -m pip install --upgrade pip

echo [INFO] Installing requirements...
call .venv\Scripts\pip install -r requirements.txt
if errorlevel 1 goto :fail

echo [OK] Installation succeeded.
pause
exit /b 0

:fail
echo [ERROR] Installation failed. See logs above.
pause
exit /b 1
