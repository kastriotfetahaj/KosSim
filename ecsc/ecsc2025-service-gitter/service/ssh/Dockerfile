FROM ubuntu:noble-20250925@sha256:728785b59223d755e3e5c5af178fab1be7031f3522c5ccd7a0b32b80d8248123
ENV DEBIAN_FRONTEND=noninteractive
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    --mount=type=bind,source=./repro-sources-list.sh,target=/usr/local/bin/repro-sources-list.sh \
    repro-sources-list.sh && \
    apt-get update && \
    apt-get install -y libc++1 openssh-server libcurl4-openssl-dev git bc && \
    : "Clean up for improving reproducibility (optional)" && \
    rm -rf /var/log/* /var/cache/ldconfig/aux-cache

RUN userdel ubuntu
RUN useradd -ms /opt/gitter-shell git
RUN usermod -p '*' git

RUN mkdir -p /var/run/sshd
RUN chmod 0755 /var/run/sshd

COPY gitter-shell /opt/
COPY gitter-keys /opt/
COPY config/ssh/ /etc/ssh/

RUN chmod 500 /opt/gitter-keys

CMD ["/usr/sbin/sshd", "-D"]
