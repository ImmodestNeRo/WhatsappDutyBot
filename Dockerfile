FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive
ENV DATA_DIR=/app/data

# system deps
RUN apt-get update && apt-get install -y \
    sqlite3 \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# install deps окремим шаром (для кешу)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# копіюємо код (після deps)
COPY . .

RUN mkdir -p /app/data

CMD ["python", "main.py"]