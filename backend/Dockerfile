FROM python:3.12-slim

WORKDIR /app

# Install system deps for psycopg2
# Acquire::Retries handles transient CDN mirror-sync errors
RUN apt-get update && apt-get install -y --no-install-recommends \
    -o Acquire::Retries=3 \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["sh", "entrypoint.sh"]
