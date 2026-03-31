# Stage 1: Build frontend
FROM node:22-slim AS frontend
WORKDIR /app/services/dashboard/ui
COPY services/dashboard/ui/package*.json ./
RUN npm ci
COPY services/dashboard/ui/ ./
RUN npm run build

# Stage 2: Python app
FROM python:3.13-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /app/services/dashboard/ui/dist services/dashboard/ui/dist/

ENV APP_ENV=production

COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
