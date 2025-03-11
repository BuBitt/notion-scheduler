#!/bin/bash
echo "Iniciando o script de exportação do cronograma..."
python3 main.py
if [ $? -ne 0 ]; then
    echo "Erro ao executar o script!"
    exit 1
else
    echo "Script concluído com sucesso! Arquivos gerados na pasta 'export'."
fi