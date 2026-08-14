FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ECA_DATA_DIR=/tmp/eca-webapp-data \
    ECA_MAX_UPLOAD_MB=100

RUN apt-get update \
    && apt-get install --no-install-recommends -y gdal-bin \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY open_eca ./open_eca
COPY webapp ./webapp

EXPOSE 10000

CMD ["sh", "-c", "exec uvicorn webapp.app:app --host 0.0.0.0 --port ${PORT:-10000}"]
