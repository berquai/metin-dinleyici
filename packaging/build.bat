@echo off
rem Metin Dinleyici - paketleme. Cift tiklayin; ayrintilar build.ps1 icinde.
rem Bastan derlemek icin: build.bat -Clean
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*
echo.
pause
