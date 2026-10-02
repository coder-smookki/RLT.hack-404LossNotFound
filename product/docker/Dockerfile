FROM node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c AS frontend
WORKDIR /build
COPY product/frontend/package.json product/frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY product/frontend/ ./
RUN npm run build

FROM python:3.13-slim-bookworm@sha256:5024f48ba9441d4b13a95d3945abc6365538e3a31109833367a1923523c6efed AS common
ARG APP_UID=1000
ARG APP_GID=1000
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN groupadd -f -g ${APP_GID} supply && useradd --uid ${APP_UID} --gid ${APP_GID} -m supply && mkdir /state && chown ${APP_UID}:${APP_GID} /state
WORKDIR /app
COPY src/ /app/src/
COPY scripts/recommend_frozen_p1.py scripts/recommend_enriched.py scripts/serve_local.py /app/scripts/
COPY product/docker/ /app/product/docker/

FROM common AS runtime
COPY product/docker/runtime.requirements.lock /tmp/runtime.requirements.lock
RUN pip install --no-cache-dir -r /tmp/runtime.requirements.lock
USER supply
CMD ["python", "scripts/serve_local.py", "--port", "8901"]

FROM common AS app
COPY product/backend/requirements.lock /tmp/backend.requirements.lock
RUN pip install --no-cache-dir -r /tmp/backend.requirements.lock
COPY product/backend/ /app/product/backend/
COPY --from=frontend /build/dist/ /app/product/frontend/dist/
ENV SUPPLY_DATA_DIR=/state
USER supply
ENTRYPOINT ["python", "product/docker/entrypoint.py"]
CMD ["web"]
