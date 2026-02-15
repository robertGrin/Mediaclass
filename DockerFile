FROM python:3.9-slim

WORKDIR /app

# Устанавливаем зависимости системы (нужны для сборки некоторых python-пакетов)
RUN apt-get update && apt-get install -y build-essential libpq-dev

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
