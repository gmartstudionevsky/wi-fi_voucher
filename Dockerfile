FROM python:3.11-slim

# LibreOffice for PPTX -> PDF conversion
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-impress libreoffice-core libreoffice-writer \
    fonts-dejavu fonts-liberation \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# --- add Circe fonts ---
COPY fonts/ /usr/local/share/fonts/circe/
RUN fc-cache -f -v

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY api /app/api
COPY web /app/web
COPY fonts /app/fonts

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data

ENV PYTHONUNBUFFERED=1
ENV DATABASE_PATH=/data/vouchers.db
VOLUME ["/data"]
EXPOSE 8080

USER appuser

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
