@echo off
title Sistema de contingencia CAP Vighi
cd /d "%~dp0"
rem La base esta en Cloudflare D1: los datos de acceso van en data\cloudflare.env (ver LEEME). Necesita internet.

rem Usa "py" si existe; si no, "python" (Python de la Microsoft Store)
set PY=
where py >nul 2>nul && set PY=py
if not defined PY where python >nul 2>nul && set PY=python
if not defined PY (
  echo No se encontro Python. Instalalo desde https://www.python.org/downloads/ ^(marcar "Add python.exe to PATH"^).
  pause
  exit /b 1
)

%PY% -m pip install -q -r requirements.txt
%PY% app.py
pause
