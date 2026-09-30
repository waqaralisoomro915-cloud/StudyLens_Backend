FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
RUN useradd -m -u 10001 app && mkdir -p /app/media /app/staticfiles && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["gunicorn","config.wsgi:application","--bind","0.0.0.0:8000","--workers","2","--timeout","240"]
