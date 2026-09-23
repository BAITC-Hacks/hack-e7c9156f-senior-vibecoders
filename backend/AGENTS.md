# backend/ — инструкции для ИИ-агента (Python / FastAPI)

Сначала прочитай корневой `AGENTS.md` и `shared/api.md`. Здесь — правила именно для `backend/`.

## Роль модуля

Центр системы: принимает файлы от фронта, запускает анализ в фоне, отдаёт статус, результат и экспорт.
ИИ-часть подключается как Python-пакет: `pip install -e ../ai`, вызов `run_analysis(before, after, on_progress)`.
Бэкенд — **интегратор**: отвечает за то, чтобы весь проект запускался вместе. Эндпоинты — `ARCHITECTURE.md`, раздел 5.

## Стек

- Python 3.11+, FastAPI, uvicorn, Pydantic v2, `python-multipart` (загрузка файлов).
- Хранилище: папка `storage/<analysis_id>/` (исходные файлы, `status.json`, `result.json`). БД не нужна.
- Зависимости в `backend/requirements.txt` (или `pyproject.toml`), окружение `backend/.venv`.

## Структура

```
backend/
  app/main.py        ← создание FastAPI, CORS, подключение роутеров
  app/routers/       ← эндпоинты по темам
  app/schemas.py     ← Pydantic-схемы (совпадают с shared/api.md)
  app/services/      ← бизнес-логика
  app/clients/ai.py  ← единственное место, где вызывается run_analysis (или мок)
  app/config.py      ← настройки из env (pydantic-settings)
  tests/
  .env.example
  README.md
```

## Правила

1. **Контракт прежде всего.** Эндпоинты, поля и коды ответов — ровно как в `shared/api.md`. Pydantic-схемы = контракт.
2. **Все вызовы ИИ — через `app/clients/ai.py`.** Анализ идёт минуты → только в фоновой задаче, прогресс пишется в `status.json` через `on_progress`. Флаг `AI_MOCK=true` — вместо анализа отдаётся `mocks/result.json`.
3. **Бэкенд не падает, если анализ упал:** статус `failed` + понятное сообщение `{ "error": "..." }`, а не голый 500 со stack trace.
4. **CORS** разрешает `http://localhost:5173` (и прод-домен фронта, если будет деплой).
5. **Ошибки** в формате `{ "error": "..." }` с корректным HTTP-кодом.
6. **Валидация на входе** через Pydantic; не доверяй данным с фронта.
7. **Секреты и настройки** — только из env через `app/config.py`. В репо только `.env.example`.
8. **Проверяй каждый эндпоинт** после изменения: `curl` или `/docs` (Swagger), и хотя бы один тест в `tests/` на основной сценарий демо.
9. `GET /health` всегда существует и отвечает быстро.

## Запуск (обнови в README, если меняется)

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
# документация: http://localhost:8000/docs
```

## README для backend/ — дополнительно к обязательным разделам

- Как поднять **весь проект** (frontend + backend + ai) — пошагово или одной командой.
- Не называть пакет `app/models/`: корневой `.gitignore` игнорирует `models/`.
- Таблица эндпоинтов со ссылкой на `shared/api.md`.
- Как включить `AI_MOCK`, чтобы работать без ИИ-сервиса.
