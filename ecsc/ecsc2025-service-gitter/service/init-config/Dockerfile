FROM ubuntu:noble-20250925@sha256:728785b59223d755e3e5c5af178fab1be7031f3522c5ccd7a0b32b80d8248123
ENV DEBIAN_FRONTEND=noninteractive
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    --mount=type=bind,source=./repro-sources-list.sh,target=/usr/local/bin/repro-sources-list.sh \
    repro-sources-list.sh && \
    apt-get update && \
    apt-get install -y python3 && \
    : "Clean up for improving reproducibility (optional)" && \
    rm -rf /var/log/* /var/cache/ldconfig/aux-cache

RUN userdel ubuntu
RUN useradd -m git

RUN mkdir /home/git/.ssh
RUN mkdir /home/git/.gitter-keys
RUN chown git:git /home/git/.gitter-keys /home/git/.ssh/
COPY config/.gitconfig /home/git/.gitconfig
RUN chown -R git:git /home/git

COPY first-boot.py /opt/first-boot.py

CMD [ -f /init-config/.env ] || /opt/first-boot.py
