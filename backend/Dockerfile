FROM siligent-api@sha256:9efe1b01290d236b7c4c68ae9c69cc5a96930aa75593f67db7c417578b2896f6

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY backend /app/backend
COPY optimizer /app/optimizer
COPY frontend /app/frontend
COPY database /app/database

EXPOSE 8443

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8443", "--ssl-certfile", "/certs/server.crt", "--ssl-keyfile", "/certs/server.key", "--no-access-log"]
