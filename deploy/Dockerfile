FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 CONTINGENCIA_PUERTO=8080 CONTINGENCIA_HTTPS=1 TZ=America/Argentina/Buenos_Aires
RUN apt-get update && apt-get install -y --no-install-recommends tzdata fonts-liberation && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --system --uid 10001 vighi && mkdir -p data && chown vighi data
USER vighi
EXPOSE 8080
CMD ["python", "-u", "app.py"]
