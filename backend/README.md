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

`requirements.txt` устанавливает соседний `ai/` как редактируемый Python-пакет в это же окружение. Отдельный сервер ИИ не нужен. По умолчанию включён мок; API: <http://localhost:8000/docs>. Если порт 8000 занят или запрещён Windows, укажите `--port 8001`. Для полного локального запуска откройте второй терминал в `frontend/`, выполните `npm install` и `npm run dev`; фронт будет на <http://localhost:5173>.

Для анализа загруженных документов задайте `AI_MOCK=false` в `backend/.env`, создайте `ai/.env` по образцу `ai/.env.example` и заполните ключи/модели согласно `ai/README.md`. Пакет ИИ сам читает `ai/.env`; секреты не нужно переносить в код бэкенда. Затем запустите сервер и отправьте файлы в `POST /api/analyses`. При отсутствии ключа статус объяснит, что нужно настроить `ai/.env`. Без ключей используйте `AI_MOCK=true` или `POST /api/analyses/demo`.

## Переменные окружения

| Имя | Зачем | Пример |
|---|---|---|
| `AI_MOCK` | Использовать демонстрационный результат | `true` |
| `STORAGE_DIR` | Каталог заданий и загруженных файлов | `C:\\work\\analysis-storage` |
| `FRONTEND_ORIGIN` | Разрешённый CORS-адрес фронта | `http://localhost:5173` |

Пустые значения в `.env.example` означают значения по умолчанию. Файлы в `backend/storage/` сохраняются между перезапусками и игнорируются Git. На каждую сторону нужен хотя бы один `.docx`, `.pdf` или `.xlsx`, каждый не больше 20 МБ.

## API / интерфейс

Полный контракт: [shared/api.md](../shared/api.md).

| Метод | Путь | Результат |
|---|---|---|
| `GET` | `/health` | `{"status":"ok"}` |
| `POST` | `/api/analyses` | multipart `before`, `after` (по одному или несколько DOCX/PDF/XLSX) → `{"id":"..."}` |
| `POST` | `/api/analyses/demo` | Встроенный иллюстративный комплект → `{"id":"..."}` |
| `GET` | `/api/analyses` | История: `[{"id":"...","status":"done","created_at":"...","documents":[],"counts":{"findings":1,"rejected":0,"high":0}}]` |
| `GET` | `/api/analyses/{id}` | `{"id":"...","created_at":"...","status":"done","step":"report","progress":1}` |
| `GET` | `/api/analyses/{id}/result` | `AnalysisResult`; до завершения: 409 |
| `PATCH` | `/api/analyses/{id}/findings/{finding_id}` | JSON `{"status":"accepted","comment":"Проверено"}` → обновлённый `AnalysisResult` |
| `GET` | `/api/analyses/{id}/documents/{doc_id}/clauses/{clause_id}` | `{"clause_id":"3.4","text":"..."}` |
| `GET` | `/api/analyses/{id}/report.docx` | Служебная записка `zaklyuchenie_<id>.docx`; до завершения: 409 |

Пример: `Invoke-RestMethod -Method Post http://localhost:8000/api/analyses/demo` вернёт `id`. Затем запросите `http://localhost:8000/api/analyses/<id>` и `http://localhost:8000/api/analyses/<id>/result`. Ошибки имеют вид `{"error":"..."}`.

### Файлы для проверки загрузки

- [before_reorganization.docx](samples/before_reorganization.docx) — поле `before`.
- [after_reorganization.docx](samples/after_reorganization.docx) — поле `after`.

В Postman выберите **Body → form-data**. Добавьте строки `before` и `after`, переключите тип каждой строки с `Text` на `File` (в новом интерфейсе Postman меню может появиться при наведении на имя ключа), затем выберите соответствующий DOCX. Оставьте `Content type` равным `Auto`; Postman сам выставит `multipart/form-data` с нужной границей.

При стандартном `AI_MOCK=true` загрузка проходит, но `/result` возвращает фиксированный демонстрационный ответ, а не результат разбора этих файлов. При `AI_MOCK=false` файлы передаются прямо в `ai.pipeline.run_analysis`; их исходные имена сохраняются в результате и ссылках на источники.

## Статус

Загрузка, фоновая задача, статус, полный результат ИИ, источник, история, проверка выводов человеком, CORS и экспорт работают. `AI_MOCK=true` возвращает `mocks/result.json`: это учебный пример, **не анализ загруженных пользователем файлов**. Встроенные документы тоже являются короткими иллюстративными выдержками, не оригиналами редакций 8/9. При `AI_MOCK=false` обычная загрузка использует установленный пакет `ai` напрямую; если анализ или его настройки недоступны, статус станет `failed`. При проверке вывода реальное заключение пересобирает `ai.report.rebuild_conclusion`; при сбое LLM используется заключение из выводов с проверенными цитатами. Демо-запрос при сбое ИИ переключается на мок. `POST /api/analyses/{id}/ask` запланирован контрактом, но ждёт `ai.chat.ask` и ещё не реализован. Поиск пунктов в файлах поддерживает номера вида `3.4` и `3.4.а`; у сканированных PDF без текстового слоя он не работает. Задания в статусе `queued` или `running` после перезапуска процесса не возобновляются автоматически.

## Как проверить

```powershell
cd backend
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Тесты проверяют API, валидацию загрузки, CORS, хранение, DOCX/PDF/XLSX, экспорт и прямой вызов установленного `ai.pipeline` с заглушками только для LLM-этапов. Они не расходуют API-кредиты. Для ручной проверки реальной модели после настройки ключей загрузите документы при `AI_MOCK=false` и дождитесь `status = done`; для демо без ключей вызовите `POST /api/analyses/demo`.
