@echo off
REM Liga o MAX na rede da empresa. Deixe esta janela aberta.
cd /d "%~dp0"
".venv\Scripts\python.exe" servidor.py
pause
