FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY src/pyproject.toml ./pyproject.toml
RUN uv pip install --system --no-cache-dir \
    'enochecker3 @ git+https://github.com/attacking-lab/enochecker3@v0.13.4' \
    'httpx>=0.27' \
    'gunicorn>=22.0' \
    'uvicorn>=0.30'

COPY src ./src

WORKDIR /app/src

ENV PYTHONUNBUFFERED=1 \
    SERVICE_PUSH_SECRET=rotate-secret \
    SERVICE_PORT=8080

EXPOSE 8500

CMD ["gunicorn", "-c", "gunicorn.conf.py", "checker:app"]
