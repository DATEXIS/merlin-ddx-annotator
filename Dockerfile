# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS frontend

WORKDIR /app
COPY package*.json ./
RUN npm ci

COPY index.html postcss.config.js tailwind.config.js tsconfig*.json vite.config.ts ./
COPY src ./src
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MERLIN_DDX_DATA_ROOT=/data \
    MERLIN_DDX_STATIC_DIR=/app/static \
    MERLIN_DDX_SYNC_GIT=false

WORKDIR /app
COPY requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt

COPY merlin_ddx ./merlin_ddx
COPY --from=frontend /app/dist ./static

EXPOSE 8000
CMD ["uvicorn", "merlin_ddx.sync_api:app", "--host", "0.0.0.0", "--port", "8000"]
