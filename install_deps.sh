#!/bin/sh
# Установка зависимостей. Если pip выдаёт SSL certificate error — используй этот скрипт.
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
