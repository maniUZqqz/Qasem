# Backend image: Django + Celery workers run from this same image.
#
# Multi-stage so the runtime layer carries no compiler. The build stage needs
# gcc for psycopg; shipping it would add weight and attack surface for nothing.

# ---------------------------------------------------------------- build
FROM python:3.12-slim AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /wheels
COPY requirements.txt requirements-production.txt ./
RUN pip wheel --wheel-dir /wheels -r requirements-production.txt


# -------------------------------------------------------------- runtime
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings

# ffmpeg is not optional: video assembly and the audio mix both shell out to
# it, and its absence only shows up when a render job fails minutes in.
# libpq5 is the psycopg runtime; curl is used by the healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /wheels /wheels
COPY requirements.txt requirements-production.txt ./
RUN pip install --no-index --find-links=/wheels -r requirements-production.txt \
    && rm -rf /wheels

# Run as a normal user. A container that runs as root shares that root with
# any mounted volume.
RUN useradd --create-home --uid 10001 upmarket
WORKDIR /app
COPY --chown=upmarket:upmarket . /app

# Media and static live on volumes; create them owned by the app user so a
# first run does not fail on permissions.
RUN mkdir -p /app/media /app/staticfiles && chown -R upmarket:upmarket /app/media /app/staticfiles

USER upmarket
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/plans/ >/dev/null || exit 1

# Two workers per core is the usual starting point, but this app spends most
# of its time waiting on Ollama, ComfyUI and the database rather than on CPU,
# so threads carry more of the load than processes here.
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--threads", "4", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
