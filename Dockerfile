# Stage 1: Build frontend
FROM node:22-slim AS frontend
WORKDIR /app/services/client
COPY services/client/package*.json ./
RUN npm ci
COPY services/client/ ./
RUN npm run build

# Stage 2: Python app
FROM python:3.13-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /app/services/client/dist services/client/dist/

ENV APP_ENV=production

COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
