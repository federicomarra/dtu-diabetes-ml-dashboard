FROM python:3.10-slim

WORKDIR /app

# Install system deps for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Use Gunicorn for production
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT --workers 4 wsgi:app"]