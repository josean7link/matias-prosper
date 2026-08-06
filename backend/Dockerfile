# bullseye (Debian 11) uses OpenSSL 1.1.1 — compatible with MongoDB Atlas M0.
# bookworm (Debian 12) uses OpenSSL 3.0 which causes TLS handshake failures
# against Atlas free-tier clusters.
FROM python:3.11-slim-bullseye AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libffi-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8001

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsSL http://localhost:8001/api/v1/status || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001", "--proxy-headers", "--forwarded-allow-ips=*"]
