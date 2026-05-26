FROM ubuntu:noble-20240407.1@sha256:5b582c80ed6832665ffb6181ab4d3e5e70c30c2548fbcea1de8a0a51f161be8d

ENV DEBIAN_FRONTEND=noninteractive
ADD https://raw.githubusercontent.com/reproducible-containers/repro-sources-list.sh/d15cf12b26395b857b24fba223b108aff1c91b26/repro-sources-list.sh /var/lib/repro-sources-list.sh
RUN \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt,sharing=locked \
  bash /var/lib/repro-sources-list.sh && \
  apt-get update && \
  apt-get install -y openssh-client python3 python3-pip git gcc && \
  : "Clean up for improving reproducibility (optional)" && \
  rm -rf /var/lib/repro-sources-list.sh /var/log/* /var/cache/ldconfig/aux-cache

WORKDIR /tmp

RUN userdel ubuntu
RUN useradd -ms /bin/bash -u 1000 checker
RUN python3 -m pip install --break-system-packages uv git-pass-helper

COPY ./src/ /checker/
WORKDIR /checker
RUN chown checker -R /checker

USER checker
RUN --mount=type=secret,id=github-pat,env=GITHUB_PAT \
	git-pass -p "${GITHUB_PAT:?GITHUB PAT not set}" -- \
    uv sync --exact --frozen

ENTRYPOINT [ "uv", "run", "--no-sync", "gunicorn", "-c", "gunicorn.conf.py", "checker:app" ]
