# Один образ для Render (Deploy an existing image): фронт + бэк + ИИ.
# nginx слушает $PORT, раздаёт фронт и проксирует /api и /health на uvicorn.
# Ключи LLM в образ не кладутся — задаются переменными окружения сервиса.
FROM node:22-alpine AS front
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend .
ENV VITE_USE_MOCKS=false VITE_API_URL=/
RUN npm run build

FROM python:3.11-slim
ENV PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    PORT=10000 AI_MOCK=false AI_CACHE_DIR=/app/ai/.cache
RUN apt-get update && apt-get install -y --no-install-recommends nginx gettext-base \
    && rm -rf /var/lib/apt/lists/* /etc/nginx/sites-enabled/default
COPY ai /app/ai
COPY backend/requirements.txt /app/backend/requirements.txt
WORKDIR /app/backend
RUN pip install -r requirements.txt
COPY backend /app/backend
COPY --from=front /app/dist /usr/share/nginx/html
COPY docker/render-nginx.conf.template /etc/nginx/templates/app.conf.template
COPY docker/render-start.sh /start.sh
RUN sed -i "s/$//" /start.sh && chmod +x /start.sh
EXPOSE 10000
CMD ["/start.sh"]
