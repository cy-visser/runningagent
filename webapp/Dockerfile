# Stage 1: Build the Vite + React 19 SPA
FROM node:24-slim AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN node -e 'const fs=require("fs");const l=JSON.parse(fs.readFileSync("package-lock.json","utf8"));for(const v of Object.values(l.packages||{})){if(v&&typeof v.resolved==="string"&&!v.resolved.startsWith("https://registry.npmjs.org/"))delete v.resolved;}fs.writeFileSync("package-lock.json",JSON.stringify(l,null,2)+"\n");' && \
    npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: FastAPI + Uvicorn runtime serving /api/* and static SPA
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STATIC_DIR=/app/static \
    PORT=8080

RUN groupadd --gid 10001 appuser && \
    useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin appuser

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && \
    pip uninstall -y pytest pytest-asyncio >/dev/null 2>&1 || true

COPY backend/app ./app
COPY --from=frontend-builder /build/dist ./static

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips='*'"]
