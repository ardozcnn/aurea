@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
)
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m app
