# Base image is pinned by tag only (no digest): see README, "Ограничения".
FROM python:3.11-slim
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
