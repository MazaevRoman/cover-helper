FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .

# -u: логи без буферизации, чтобы Dokploy показывал их вживую
CMD ["python", "-u", "bot.py"]
