# The research workspace image (`compose.yaml`). It holds the package, its migrations and the
# migration runner -- and no credential, key or password of any kind: the database password is
# generated at first start into a volume, and language-model keys come from the environment at
# run time (see compose.yaml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The repository layout is kept (`lab_brain.spec.repo_root` finds `migrations/` beside `src/`), and
# the package is installed in place so its entry points -- `lab-brain`, the product vertical -- are
# registered.
COPY pyproject.toml README.md ./
COPY src ./src
COPY migrations ./migrations
COPY scripts/migrate.py ./scripts/migrate.py
COPY deployment/docker ./deployment/docker

RUN pip install -e ".[postgres]" \
    && install -m 0755 deployment/docker/entrypoint.sh /usr/local/bin/lab-brain-entrypoint \
    && groupadd --system --gid 10001 labbrain \
    && useradd --system --uid 10001 --gid labbrain --home-dir /var/lib/lab-brain \
       --shell /usr/sbin/nologin labbrain \
    && mkdir -p /var/lib/lab-brain/artifacts /var/lib/lab-brain/credentials \
    && chown -R labbrain:labbrain /var/lib/lab-brain \
    && chmod 0700 /var/lib/lab-brain/credentials

USER labbrain
ENTRYPOINT ["lab-brain-entrypoint"]
CMD ["lab-brain", "--help"]
