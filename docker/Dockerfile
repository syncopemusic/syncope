# Dockerfile
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY . /app/

RUN uv sync --frozen

COPY docker/start.sh /app/start.sh

EXPOSE 8000

CMD ["/app/start.sh"]
