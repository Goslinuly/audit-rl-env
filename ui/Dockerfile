# Web explorer for auditgym episodes (Railway). Not used by the official check.
FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY auditgym ./auditgym
COPY pyproject.toml README.md LICENSE ./
RUN pip install --no-cache-dir .
COPY configs ./configs
COPY episodes ./episodes
COPY ui ./ui
EXPOSE 8000
CMD ["python", "ui/server.py"]
