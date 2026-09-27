# Backend image for Google Cloud Run.
#
# Build context: neuro-symbolic-level-designer/ (see ../.dockerignore):
#   docker build -f backend/Dockerfile -t level-designer-backend .
#
# No secrets in the image: .env and creds.json are excluded from the context.
# On Cloud Run the Gemini client uses the service account (Application
# Default Credentials); configuration comes from environment variables.
FROM python:3.12.3-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FLUTTER_ROOT=/opt/flutter \
    PUB_CACHE=/opt/pub-cache \
    PATH=/opt/flutter/bin:/opt/flutter/bin/cache/dart-sdk/bin:$PATH

# System packages: Flutter needs git, curl, xz, unzip; OpenCV headless needs glib.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git unzip xz-utils libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Flutter SDK (pinned, same as local) for the dart_analyze verification check.
ARG FLUTTER_VERSION=3.47.5
RUN curl -fsSL "https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_${FLUTTER_VERSION}-stable.tar.xz" \
        | tar -xJ -C /opt \
    && git config --global --add safe.directory /opt/flutter \
    && flutter config --no-analytics --no-cli-animations > /dev/null \
    && dart --disable-analytics > /dev/null \
    && flutter --version

# Resolve the scratch package once at build time: no network needed at runtime.
WORKDIR /app/backend/codegen_check
COPY backend/codegen_check/pubspec.yaml ./
RUN flutter pub get

# Python dependencies (same pins as local).
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

# App code and the default spritesheet (asset packs point to it).
COPY game-assets/grassland_tiles.png /app/game-assets/grassland_tiles.png
COPY backend/ /app/backend/

EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
