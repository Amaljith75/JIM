@echo off
cd /d "%~dp0\.."
if not exist .venv (
  echo First run: setting up JIM...
  python -m venv .venv || (echo Python 3.10+ is required: https://www.python.org/downloads/ & pause & exit /b)
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\pip install -r requirements.txt
)
.venv\Scripts\python run.py %*
pause
