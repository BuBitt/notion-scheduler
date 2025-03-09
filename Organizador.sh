#!/bin/bash
./venv/bin/python "$(dirname "$0")/scheduler.py"
echo
echo "Pressione qualquer tecla para fechar..."
read -n 1 -s