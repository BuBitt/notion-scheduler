@echo off
setlocal

:: Obtém o diretório do script
set "SCRIPT_DIR=%~dp0"

:: Executa o Python do ambiente virtual
"%SCRIPT_DIR%venv\Scripts\python.exe" "%SCRIPT_DIR%scheduler.py"

echo.
echo Pressione qualquer tecla para fechar...
pause >nul
