@echo off
REM Liga o MAX na rede da empresa. Deixe esta janela aberta.
chcp 65001 >nul
cd /d "%~dp0"

if not exist "servidor.py" (
    echo Nao encontrei o servidor.py nesta pasta:
    echo   %CD%
    echo Abra o iniciar_servidor.bat de dentro da pasta projeto_MAX_IA.
    goto fim
)

if not exist ".venv\Scripts\python.exe" (
    echo Nao encontrei o Python do projeto .venv\Scripts\python.exe nesta pasta:
    echo   %CD%
    echo.
    echo Se o .bat estiver na pasta certa, crie a .venv com:
    echo   python -m venv .venv
    echo   .venv\Scripts\python -m pip install -r requirements.txt
    goto fim
)

".venv\Scripts\python.exe" servidor.py

:fim
echo.
pause
