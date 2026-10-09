FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# The frozen lockfile includes Lite-Mem from GitHub.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock .python-version README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
    && mkdir -p /data

ENV EDUINSIGHT_MEMORY_DB_PATH=/data/eduinsight.db \
    EDUINSIGHT_AUTH_DB_PATH=/data/eduinsight_auth.db

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/health', timeout=4)" || exit 1

CMD ["sh", "-c", "exec uvicorn eduinsight.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
