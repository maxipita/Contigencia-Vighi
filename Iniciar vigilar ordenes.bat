@echo off
setlocal
title Subida automatica de ordenes escaneadas
cd /d "%~dp0"
set "CARPETA="
for /d %%D in ("%USERPROFILE%\OneDrive - Centro de diagn*") do set "CARPETA=%%D\Escaneos"
if not defined CARPETA (
    echo No encuentro la carpeta Escaneos de OneDrive en esta PC.
    pause
    exit /b 1
)
echo Carpeta que se vigila: %CARPETA%
echo.
set /p VIGHI_CLAVE=Pega la clave de integracion y apreta Enter:
set "VIGHI_URL=https://contingencia.sistemacapvighi.com"
set "VIGHI_CARPETA=%CARPETA%"
echo.
py "vighi\herramientas\vigilar_ordenes.py" --desde 2026-10-15
echo.
echo El programa se detuvo.
pause
