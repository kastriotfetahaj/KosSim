FROM node:23.1-alpine AS frontend

WORKDIR /app

COPY package.json .
COPY package-lock.json .
RUN npm install
COPY mainpage/vite mainpage/vite
COPY vite.config.ts .
COPY tsconfig.json .
COPY tsconfig.node.json .
COPY tsconfig.app.json .
RUN npx vite build

FROM python:3.12-alpine AS django

RUN apk add wireguard-tools 7zip imagemagick imagemagick-jpeg imagemagick-heic \
    imagemagick-svg imagemagick-webp imagemagick-raw

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV VIRTUAL_ENV=/venv
RUN uv venv --python 3.13 "$VIRTUAL_ENV"
ENV PATH=$VIRTUAL_ENV/bin/:$PATH

WORKDIR /opt/app/
COPY pyproject.toml .
COPY uv.lock .

RUN uv sync --compile-bytecode --active --frozen --exact
COPY manage.py .
COPY mainpage mainpage
COPY --from=frontend /app/vite_build vite_build
