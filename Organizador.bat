@echo off
echo Iniciando o script de exportação do cronograma...
python main.py
if %ERRORLEVEL% NEQ 0 (
    echo Erro ao executar o script!
    pause
) else (
    echo Script concluído com sucesso! Arquivos gerados na pasta 'export'.
    pause
)