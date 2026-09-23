# API-контракт

Единственный источник правды о формате данных между `frontend`, `backend` и `ai`.
Изменения — только по договорённости команды. При изменении обнови дату и раздел «История».

Последнее обновление: 2026-09-23

## Backend (FastAPI, :8000) — для фронтенда

| Метод | Путь | Ответ |
|---|---|---|
| GET  | `/health` | `{ "status": "ok" }` |
| POST | `/api/analyses` | multipart: `before` (файлы), `after` (файлы) → `{ "id": "a1b2" }` |
| POST | `/api/analyses/demo` | запуск на встроенном комплекте → `{ "id": "a1b2" }` |
| GET  | `/api/analyses/{id}` | `AnalysisStatus` |
| GET  | `/api/analyses/{id}/result` | `AnalysisResult` (только при `status = "done"`, иначе 409) |
| GET  | `/api/analyses/{id}/documents/{doc_id}/clauses/{clause_id}` | `{ "clause_id": "3.4", "text": "..." }` |
| GET  | `/api/analyses/{id}/report.docx` | служебная записка .docx (см. «Экспорт») |
| GET  | `/api/analyses` | `AnalysisSummary[]` — история запусков, новые сверху |
| PATCH | `/api/analyses/{id}/findings/{finding_id}` | тело `ReviewRequest` → обновлённый `AnalysisResult` (с пересобранным `conclusion_md`) |
| POST | `/api/analyses/{id}/ask` | тело `{ "question": "..." }` → `AskAnswer` — **запланировано**, ждёт функцию из `ai/` |

Ошибки: `{ "error": "описание" }` + корректный HTTP-код.

### Задачи бэкенда (по приоритету — каждая добавляет баллы)

1. **Проверка человеком** — закрывает требование ТЗ «выводы проверяет ответственный сотрудник».
   - `PATCH …/findings/{finding_id}`: ищет вывод в `findings` **и** в `rejected_findings`, записывает `review` (см. схему), сохраняет `result.json`.
   - Затем пересобирает заключение: `from ai.report import rebuild_conclusion; result.conclusion_md = rebuild_conclusion(result)` (вызов LLM, ~5–15 с; делать синхронно или фоном со статусом).
   - Правило: `review.status = "rejected"` → вывод исключается из заключения; `"accepted"` → включается, даже если критик его опроверг. 404 — нет анализа/вывода, 409 — анализ не в `done`.
2. **Экспорт служебной записки `.docx`** — `report.docx`: заголовок, дата, список документов, `conclusion_md` (markdown → абзацы/списки), таблица выводов (тип, критичность, заголовок, источники «документ, п. X — «цитата»»), отметки проверки человеком, дисклеймер «Выводы носят рекомендательный характер…». Имя файла: `zaklyuchenie_<id>.docx`.
3. **История анализов** — `GET /api/analyses`: читает `storage/*/status.json` + `documents.json`, сортировка по `created_at`.
4. **Проверка загрузки** — только `.docx/.pdf/.xlsx`, ≤ 20 МБ на файл, ≥ 1 файл на каждую сторону; ошибки `400/413/415` с понятным русским текстом в `error` (напр. «Файл «x.doc» не поддерживается: загрузите .docx, .pdf или .xlsx»).
5. **Воспроизводимость (25 баллов за README)** — одна команда запуска всего проекта (`docker-compose up` или скрипт `run.ps1`/`Makefile`), корневой `README.md` (что это, архитектура со ссылкой на `ARCHITECTURE.md`, запуск за 5 минут, демо-сценарий), по возможности деплой с живой ссылкой для жюри.
6. **Чат с документами** (`POST …/ask`) — после того как в `ai/` появится `ai.chat.ask(result, question) -> AskAnswer`.

## Схемы

```ts
type Side = "before" | "after";

interface AnalysisStatus {
  id: string;
  created_at?: string;  // ISO 8601 — нужен для истории
  status: "queued" | "running" | "done" | "failed";
  step?: string;        // "parsing" | "alignment" | "units" | "functions" | "conflicts" | "evidence" | "critic" | "report"
  progress: number;     // 0..1
  error?: string;
}

interface Evidence {
  doc_id: string; doc_name: string; side: Side;
  clause_id: string;    // "3.4"
  quote: string;        // точная цитата из пункта
  verified: boolean;    // цитата найдена в тексте пункта кодом
}

interface Unit {
  id: string; side: Side; name: string; abbr?: string;
  parent?: string; positions: string[]; evidence: Evidence[];
}

interface UnitChange {
  before_unit_ids: string[]; after_unit_ids: string[];
  status: "preserved" | "renamed" | "created" | "abolished" | "merged" | "split" | "transformed";
  rationale: string; evidence: Evidence[];
}

interface FunctionMapping {
  id: string;
  function: string;
  category_id: string;  // id из AnalysisResult.categories (каталог функций)
  before_unit_id?: string; after_unit_ids: string[];
  status: "preserved" | "moved" | "modified" | "lost";
  confidence: number;   // 0..1
  evidence: Evidence[];
}

interface CriticVerdict {             // агент-критик пытался опровергнуть вывод
  verdict: "upheld" | "refuted" | "uncertain";
  argument: string;
  counter_evidence: Evidence[];
}

interface Finding {
  id: string;
  type: "function_loss" | "duplication" | "conflict_of_interest" | "structure_change";
  severity: "high" | "medium" | "low";
  title: string; description: string; recommendation?: string;
  unit_ids: string[]; evidence: Evidence[];
  rule_id?: string;       // для conflict_of_interest: id правила несовместимости функций
  critic?: CriticVerdict;
  review?: Review;        // решение сотрудника; ставит только бэкенд через PATCH
}

interface Review {
  status: "accepted" | "rejected";
  comment?: string;
  reviewed_at: string;    // ISO 8601
}

interface ReviewRequest { status: "accepted" | "rejected"; comment?: string; }

interface AnalysisSummary {             // строка истории
  id: string;
  status: "queued" | "running" | "done" | "failed";
  created_at: string;                   // ISO 8601
  documents: { name: string; side: Side }[];
  counts?: { findings: number; rejected: number; high: number };   // только для done
}

interface AskAnswer {                   // запланировано
  answer_md: string;
  evidence: Evidence[];                 // каждое утверждение ответа — со ссылкой; verified как везде
}

interface Clause { clause_id: string; section: string; text: string; }   // clause_id: "3.4", "2.4.7", "3.4.а"

interface DocumentText { doc_id: string; name: string; side: Side; clauses: Clause[]; }

interface ClauseAlignment {           // redline: пары пунктов «до ↔ после»
  before_clause_id?: string;          // нет → пункт добавлен
  after_clause_id?: string;           // нет → пункт удалён
  status: "unchanged" | "modified" | "added" | "removed" | "moved";   // moved = текст тот же, номер другой
  similarity: number;                 // 0..1
  diff?: { op: "equal" | "insert" | "delete"; text: string }[];       // пословный дифф, для modified
}

interface Flow {                      // Sankey: откуда куда ушли функции
  source_unit_id: string;             // Unit «до»
  target_unit_id: string;             // Unit «после» или "lost"
  function_ids: string[];             // FunctionMapping.id
  value: number;                      // = function_ids.length
}

interface AnalysisResult {
  units: Unit[];
  unit_changes: UnitChange[];
  function_mappings: FunctionMapping[];
  findings: Finding[];                // подтверждённые (critic.verdict !== "refuted")
  rejected_findings: Finding[];       // опровергнутые критиком — показываем отдельно
  conclusion_md: string;
  documents: DocumentText[];          // полный текст по пунктам — для redline и панели «Источник»
  alignments: ClauseAlignment[];
  flows: Flow[];
  categories: { id: string; name: string }[];
  meta: {
    model: string; provider: string; duration_s: number;
    documents: { doc_id: string; name: string; side: Side }[];
  };
}
```

## AI-пакет — для бэкенда

```python
from ai.pipeline import run_analysis

result: AnalysisResult = run_analysis(
    before_files: list[Path],
    after_files: list[Path],
    on_progress: Callable[[str, float], None],   # (step, progress 0..1)
)

from ai.report import rebuild_conclusion
result.conclusion_md = rebuild_conclusion(result)   # после изменения review у выводов
```

Бэкенду: результат `run_analysis` — объект Pydantic из `ai.schemas`; сохраняйте его через `result.model_dump(mode="json")`, не прогоняйте через устаревшие схемы — иначе пропадут новые поля.

## Общие соглашения

- JSON, UTF-8, поля в `snake_case`.
- CORS на бэкенде разрешает `http://localhost:5173`.
- Пример результата для моков: `mocks/result.json` (на данных Положения о ВА ред. 8 → ред. 9).

## История

- 2026-09-23 — первая версия контракта.
- 2026-09-23 — добавлено: redline (`documents`, `alignments`), Sankey (`flows`), каталог функций (`categories`, `FunctionMapping.id/category_id`), агент-критик (`Finding.critic`, `rejected_findings`), SoD-правила (`Finding.rule_id`). Pydantic-эталон: `ai/ai/schemas.py`.
- 2026-09-23 — задачи бэкенда: проверка человеком (`Finding.review`, `PATCH …/findings/{id}`, `ai.report.rebuild_conclusion`), история (`GET /api/analyses`, `AnalysisSummary`, `AnalysisStatus.created_at`), экспорт `.docx`, валидация загрузки, запланирован `POST …/ask`.
