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

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
