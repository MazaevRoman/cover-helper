FROM python:3.12-slim

# Прокси только на время сборки (ARG не попадает в рантайм-образ).
# Нужен, если билд-хост Dokploy не достаёт PyPI напрямую.
# В Dokploy задать как Build Args: HTTP_PROXY, HTTPS_PROXY.
ARG HTTP_PROXY=
ARG HTTPS_PROXY=

WORKDIR /app
COPY requirements.txt .
RUN HTTP_PROXY=$HTTP_PROXY HTTPS_PROXY=$HTTPS_PROXY \
    pip install --no-cache-dir -r requirements.txt
COPY bot.py .

# -u: логи без буферизации, чтобы Dokploy показывал их вживую
CMD ["python", "-u", "bot.py"]
