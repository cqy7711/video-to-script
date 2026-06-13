@echo off
chcp 65001 >nul 2>nul
title Video to Script
:: Double-click this file to launch Video to Script
set "DIR=%~dp0"
set "DIR=%DIR:~0,-1%"
call "%DIR%\run.bat"
