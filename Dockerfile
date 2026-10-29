# syntax=docker/dockerfile:1

############################
# Stage 1 — build frontend #
############################
# Vite 8 needs Node >= 20.19 / 22.12. The build lands in /frontend/dist, which
# Flask serves as static files (see app/__init__.py static_folder).
FROM node:22-alpine AS frontend

WORKDIR /frontend

# Dependencies first, so a source-only change reuses this layer.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install

COPY frontend/ ./
ENV NODE_ENV=production
RUN npm run build


##############################################
# Stage 2 — compile Python deps into wheels  #
##############################################
# The build toolchain lives only here: pyodbc needs gcc and the unixODBC headers
# to compile, and building wheels up front keeps the runtime image compiler-free.
FROM python:3.12-slim AS builder

# Which database driver to include. Matches DB_PROVIDER at runtime:
#   sqlite (default) | postgresql | mysql | mssql
ARG DB_PROVIDER=sqlite
# Include Authlib for AUTH_PROVIDER=oidc.
ARG WITH_OIDC=false

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc \
    && if [ "$DB_PROVIDER" = "mssql" ]; then \
         apt-get install -y --no-install-recommends unixodbc-dev; \
       fi \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt ./
COPY requirements/ ./requirements/

# gunicorn is the production server and is deliberately not in requirements.txt,
# which describes what the app needs to run under `flask run` in development.
RUN set -eux; \
    EXTRA=""; \
    if [ -f "requirements/${DB_PROVIDER}.txt" ]; then EXTRA="-r requirements/${DB_PROVIDER}.txt"; fi; \
    if [ "$WITH_OIDC" = "true" ]; then EXTRA="$EXTRA -r requirements/oidc.txt"; fi; \
    pip wheel --wheel-dir=/wheels -r requirements.txt $EXTRA gunicorn


#####################################
# Stage 3 — runtime                 #
#####################################
FROM python:3.12-slim AS runtime

ARG DB_PROVIDER=sqlite

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GUNICORN_WORKERS=4 \
    GUNICORN_THREADS=4 \
    GUNICORN_TIMEOUT=120 \
    PORT=5000

WORKDIR /app

# Microsoft ODBC driver, only for the SQL Server build: it adds ~150 MB and an
# apt repository, which no other provider should carry.
#
# libgssapi-krb5-2 is dlopen()ed by the driver but not declared as a dependency.
# curl happens to pull it in, so `purge --auto-remove curl` would take it away
# and the driver would then fail with the misleading unixODBC error
# "Can't open lib ... : file not found". Installing it explicitly marks it manual.
RUN if [ "$DB_PROVIDER" = "mssql" ]; then \
      apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
      && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
           | tee /etc/apt/trusted.gpg.d/microsoft.asc > /dev/null \
      && echo "deb [arch=amd64,arm64,armhf] https://packages.microsoft.com/debian/12/prod bookworm main" \
           > /etc/apt/sources.list.d/mssql-release.list \
      && apt-get update \
      && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 libgssapi-krb5-2 \
      && apt-get purge -y --auto-remove curl gnupg \
      && apt-get clean && rm -rf /var/lib/apt/lists/*; \
    fi

# Install from the prebuilt wheels only: offline, no compiler, no source builds.
COPY --from=builder /wheels /wheels
COPY requirements.txt ./
COPY requirements/ ./requirements/
RUN set -eux; \
    EXTRA=""; \
    if [ -f "requirements/${DB_PROVIDER}.txt" ]; then EXTRA="-r requirements/${DB_PROVIDER}.txt"; fi; \
    pip install --no-index --find-links=/wheels -r requirements.txt $EXTRA gunicorn; \
    rm -rf /wheels

# Application code, then the built SPA. config.BASE_DIR resolves to /app, so
# Flask serves /app/frontend/dist.
COPY app/ ./app/
COPY cli/ ./cli/
COPY lib/ ./lib/
# The schema is SQL, so it is part of the image: `flask db-apply` runs in
# the container on first deploy.
COPY sql/ ./sql/
COPY config.py run.py ./
COPY --from=frontend /frontend/dist ./frontend/dist

# Logs are written inside the image by default; mount a volume here to keep them.
RUN mkdir -p /app/logs

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

# /health answers 503 when the database (or a required Redis) is unreachable, so
# an unhealthy container is one that genuinely cannot serve.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request,sys; \
    sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','5000'), timeout=3).status==200 else 1)"

# gthread workers: the work here is IO-bound (database, Redis, upstream APIs),
# where threads are cheaper than processes. Scale workers to ~(2 × CPU) + 1.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers ${GUNICORN_WORKERS} --threads ${GUNICORN_THREADS} --worker-class gthread --timeout ${GUNICORN_TIMEOUT} --access-logfile - --error-logfile - run:app"]
