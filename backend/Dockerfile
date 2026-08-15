# syntax=docker/dockerfile:1
# Loqi backend production image (PR10.1).
#
# Multi-stage: a builder stage compiles native wheels (pyiceberg -> storage3
# dependency chain needs gcc/g++/make + Python headers on python:3.14-slim),
# and the runtime stage installs only those prebuilt wheels — so build tools
# never remain in the final image. Production startup only (no reload),
# non-root runtime user, /data volume for persisted conversation state.
FROM python:3.14-slim AS builder

# Minimum system build deps for the production dependency set.
# (Confirmed against the real resolver: storage3 -> pyiceberg -> pyroaring,
# mmh3, zstandard — all compile C/C++ extensions that need gcc/g++/make and
# Python.h from python3-dev.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements-prod.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements-prod.txt

FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    CONVERSATIONS_STATE_FILE=/data/conversations.json \
    COMMUNICATION_STATE_FILE=/data/communication.json \
    LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE=false

WORKDIR /app

# Prebuilt wheels only — no compiler required at runtime.
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl \
    && rm -rf /wheels

# Application code only (no tests, no venv, no local state).
COPY main.py workflows.py workflow_dispatcher.py ./
COPY services ./services

# Non-root runtime user + writable data dir for persisted conversation state.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data

USER appuser

EXPOSE 10000
# shit causes a failed railway deploy VOLUME ["/data"]

# Production startup (matches render.yaml); never a reload server.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}"]
