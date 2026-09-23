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
| GET  | `/api/analyses/{id}/report.docx` | файл отчёта (опционально) |

Ошибки: `{ "error": "описание" }` + корректный HTTP-код.

## Схемы

```ts
type Side = "before" | "after";

interface AnalysisStatus {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  step?: string;        // "parsing" | "units" | "unit_matching" | "functions" | "function_matching" | "duplicates" | "conflicts" | "evidence" | "report"
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
  function: string; before_unit_id?: string; after_unit_ids: string[];
  status: "preserved" | "moved" | "modified" | "lost";
  confidence: number;   // 0..1
  evidence: Evidence[];
}

interface Finding {
  id: string;
  type: "function_loss" | "duplication" | "conflict_of_interest" | "structure_change";
  severity: "high" | "medium" | "low";
  title: string; description: string; recommendation?: string;
  unit_ids: string[]; evidence: Evidence[];
}

interface AnalysisResult {
  units: Unit[];
  unit_changes: UnitChange[];
  function_mappings: FunctionMapping[];
  findings: Finding[];
  conclusion_md: string;
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
```

## Общие соглашения

- JSON, UTF-8, поля в `snake_case`.
- CORS на бэкенде разрешает `http://localhost:5173`.
- Пример результата для моков: `mocks/result.json` (на данных Положения о ВА ред. 8 → ред. 9).

## История

- 2026-09-23 — первая версия контракта.
