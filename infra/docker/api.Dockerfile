# API, worker, and migrations (one image, three commands). Build from the repository root:
#   docker build -f infra/docker/api.Dockerfile -t meridian-api .
# Runtime dependencies only (apps/api/requirements.txt); the model services and the training tools are separate.
# Not built on the development machine (no Docker there): build and test before use.
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY apps/api/requirements.txt ./requirements.txt
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements.txt

FROM python:3.12-slim AS run
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/apps/api MS_ENV=production
# Libraries for PDF reports (WeasyPrint) and the map image; the map browser is installed by the report setup step.
RUN apt-get update && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b curl \
    && rm -rf /var/lib/apt/lists/* && useradd --system --uid 10001 --no-create-home app
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY apps/api ./apps/api
COPY data/seed ./data/seed
COPY data/scripts ./data/scripts
COPY pyproject.toml ./
USER app
EXPOSE 8090
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8090/api/v1/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "meridian.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8090", "--no-server-header", "--workers", "2"]
