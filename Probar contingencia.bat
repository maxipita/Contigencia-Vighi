@echo off
title PRUEBA - Sistema de contingencia CAP Vighi
cd /d "%~dp0"
rem Modo prueba: base de datos aparte (data\prueba.db) y puerto 8001. No toca la base real.
rem Para empezar de cero, borrar data\prueba.db con el sistema cerrado.
set CONTINGENCIA_DB=%~dp0data\prueba.db
set CONTINGENCIA_PUERTO=8001

set PY=
where py >nul 2>nul && set PY=py
if not defined PY where python >nul 2>nul && set PY=python
if not defined PY (
  echo No se encontro Python.
  pause
  exit /b 1
)
echo *** MODO PRUEBA: los datos cargados aca NO son reales ***
%PY% -m pip install -q -r requirements.txt
%PY% app.py
pause
