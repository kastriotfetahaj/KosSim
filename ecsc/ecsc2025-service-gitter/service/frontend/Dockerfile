FROM node:24-slim@sha256:3e69116c924bfcba6c6979aff60d966c37aef56d488ce091c69d442ebec9f103
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    --mount=type=bind,source=./repro-sources-list.sh,target=/usr/local/bin/repro-sources-list.sh \
    repro-sources-list.sh && \
    apt-get update && \
    apt-get install -y git && \
    : "Clean up for improving reproducibility (optional)" && \
    rm -rf /var/log/* /var/cache/ldconfig/aux-cache

WORKDIR /app

COPY package.json package-lock.json ./

RUN npm ci

COPY . .

RUN npm run build

USER node

# Set git configuration
RUN git config --global user.name "Gitter" && \
    git config --global user.email "gitter@gitter.local"

EXPOSE 3000

USER root
CMD env $(cat /init-config/.env) runuser -w POSTGRES_URL,POSTGRESS_PASSWORD,JWT_SECRET node -c 'npm start'
