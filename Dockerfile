FROM node:22-alpine AS web
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt -c requirements.lock
COPY arena/ ./arena/
COPY --from=web /build/dist/ ./frontend/dist/
ENV ARENA_HOST=0.0.0.0 ARENA_PORT=8010 ARENA_DATA_DIR=/app/data
EXPOSE 8010
CMD ["python", "-m", "arena.main"]
