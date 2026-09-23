# Backend

## Что это

FastAPI-сервер принимает документы «до» и «после», запускает анализ в фоне, хранит его статус и результат, показывает источник вывода и отдаёт DOCX-отчёт. Связь с пакетом `ai` проходит только через `app/clients/ai.py`.

## Быстрый старт

PowerShell, из корня репозитория:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

По умолчанию включён мок. API: <http://localhost:8000/docs>. Для полного локального запуска откройте второй терминал в `frontend/`, выполните `npm install` и `npm run dev`; фронт будет на <http://localhost:5173>. Когда пакет `ai/` получит `pyproject.toml` и `ai.pipeline.run_analysis`, установите его в окружение бэкенда командой `.venv\Scripts\python.exe -m pip install -e ../ai` и установите `AI_MOCK=false` в `backend/.env`.

## Переменные окружения

| Имя | Зачем | Пример |
|---|---|---|
| `AI_MOCK` | Использовать демонстрационный результат | `true` |
| `STORAGE_DIR` | Каталог заданий и загруженных файлов | `C:\\work\\analysis-storage` |
| `FRONTEND_ORIGIN` | Разрешённый CORS-адрес фронта | `http://localhost:5173` |

Пустые значения в `.env.example` означают значения по умолчанию. Файлы в `backend/storage/` сохраняются между перезапусками и игнорируются Git. Можно загрузить до 10 файлов на сторону, каждый не больше 20 МБ.

## API / интерфейс

Полный контракт: [shared/api.md](../shared/api.md).

| Метод | Путь | Результат |
|---|---|---|
| `GET` | `/health` | `{"status":"ok"}` |
| `POST` | `/api/analyses` | multipart `before`, `after` (по одному или несколько DOCX/PDF/XLSX) → `{"id":"..."}` |
| `POST` | `/api/analyses/demo` | Встроенный иллюстративный комплект → `{"id":"..."}` |
| `GET` | `/api/analyses/{id}` | `{"id":"...","status":"done","step":"report","progress":1}` |
| `GET` | `/api/analyses/{id}/result` | `AnalysisResult`; до завершения: 409 |
| `GET` | `/api/analyses/{id}/documents/{doc_id}/clauses/{clause_id}` | `{"clause_id":"3.4","text":"..."}` |
| `GET` | `/api/analyses/{id}/report.docx` | DOCX-отчёт; до завершения: 409 |

Пример: `Invoke-RestMethod -Method Post http://localhost:8000/api/analyses/demo` вернёт `id`. Затем запросите `http://localhost:8000/api/analyses/<id>` и `http://localhost:8000/api/analyses/<id>/result`. Ошибки имеют вид `{"error":"..."}`.

## Статус

Загрузка, фоновая задача, статус, результат, источник, CORS и экспорт работают. `AI_MOCK=true` возвращает `mocks/result.json`: это учебный пример, **не анализ загруженных пользователем файлов**. Встроенные документы тоже являются короткими иллюстративными выдержками, не оригиналами редакций 8/9. При `AI_MOCK=false` обычная загрузка использует `ai.pipeline.run_analysis`; если пакет или анализ недоступен, статус станет `failed`. Демо-запрос при сбое ИИ переключается на мок. У сканированных PDF без текстового слоя поиск пункта не работает; задания в статусе `queued` или `running` после перезапуска процесса не возобновляются автоматически. На момент создания README пакет ИИ и интерфейс фронта ещё не готовы к сквозной проверке.

## Как проверить

```powershell
cd backend
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Тест проверяет `/health`, загрузку, демо, статус, результат, источник, DOCX-экспорт и формат ошибок. Для ручной проверки после запуска сервера откройте `/docs` и вызовите `POST /api/analyses/demo`.
