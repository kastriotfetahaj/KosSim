FROM ubuntu:24.04@sha256:353675e2a41babd526e2b837d7ec780c2a05bca0164f7ea5dbbd433d21d166fc
ADD https://raw.githubusercontent.com/reproducible-containers/repro-sources-list.sh/d15cf12b26395b857b24fba223b108aff1c91b26/repro-sources-list.sh /var/lib/repro-sources-list.sh
RUN \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt,sharing=locked \
  bash /var/lib/repro-sources-list.sh && \
  apt-get update && \
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential \
    socat \
    cron && \
  rm -rf /var/lib/repro-sources-list.sh /var/log/* /var/cache/ldconfig/aux-cache

# Copy runtime sources
WORKDIR /service
COPY runtime ./runtime

# Build
WORKDIR /service/runtime
# Compile AngelScript
RUN cd angelscript/projects/gnuc && CXXFLAGS="-O2" make static
# Compile service
#RUN CXXFLAGS="-O2 -DTRACY_ENABLE=1" make all
RUN CXXFLAGS="-O2" make all

# Copy AngelScript sources
WORKDIR /service
COPY entrypoint.sh run.sh .

# Setup cleanup task
COPY cleanup.sh .
RUN chmod +x ./cleanup.sh
RUN echo "*/5 * * * * /service/cleanup.sh" | crontab -

CMD [ "/bin/bash", "entrypoint.sh" ]
