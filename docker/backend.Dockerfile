FROM python:3.11-slim
ENV PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY ai /app/ai
COPY backend/requirements.txt /app/backend/requirements.txt
WORKDIR /app/backend
RUN pip install -r requirements.txt
COPY backend /app/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
