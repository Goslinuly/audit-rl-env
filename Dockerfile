# python:3.11-slim, pinned by multi-arch index digest (Docker Hub, 2026-11-21).
FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends make && rm -rf /var/lib/apt/lists/*
# Exact versions of every runtime/dev dependency, including transitive ones.
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml LICENSE README.md ./
COPY auditgym ./auditgym
RUN pip install --no-cache-dir --no-deps -e .
COPY . .
# Network is not needed at run time: docker run --network none ...
CMD ["make", "check"]
