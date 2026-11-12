FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY decensio ./decensio
RUN pip install --no-cache-dir .

# Render fournit le port dans $PORT.
CMD ["sh", "-c", "uvicorn decensio.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
