FROM attackinglab/heavensent-gnuradio

ENV OPENBLAS_THREAD_TIMEOUT=4

RUN python3 -m pip install --break-system-packages uv==0.8.15 git-pass-helper
WORKDIR /checker
COPY src/uv.lock src/pyproject.toml .
RUN uv venv -p 3.12 --system-site-packages
RUN --mount=type=secret,id=github-pat,env=GITHUB_PAT \
  git-pass -p "${GITHUB_PAT:?GITHUB PAT not set}" -- \
  uv sync -p 3.12 --frozen --exact
COPY src/* .

EXPOSE 8500
CMD [ "uv", "run", "--no-sync", "gunicorn", "-c", "gunicorn.conf.py", "checker:app" ]
