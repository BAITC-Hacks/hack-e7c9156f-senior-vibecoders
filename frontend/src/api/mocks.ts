import type { AnalysisResult, ClauseResponse, Evidence } from './types'

const before: Evidence = {
  doc_id: 'r8', doc_name: 'Положение о ВА · редакция 8', side: 'before', clause_id: '3.4',
  quote: 'ДНМ, ДККМ', verified: false,
}
const after: Evidence = {
  doc_id: 'r9', doc_name: 'Положение о ВА · редакция 9', side: 'after', clause_id: '3.4',
  quote: 'ДИТААД, ДОА, ДНМ, ДККМ', verified: false,
}
const beforeMonitoring: Evidence = { doc_id: 'r8', doc_name: before.doc_name, side: 'before', clause_id: '2.2', quote: 'ДНМ проводит независимый мониторинг.', verified: false }
const afterMonitoring: Evidence = { doc_id: 'r9', doc_name: after.doc_name, side: 'after', clause_id: '2.2', quote: 'ДНМ проводит независимый мониторинг.', verified: false }
const beforeQuality: Evidence = { doc_id: 'r8', doc_name: before.doc_name, side: 'before', clause_id: '3.6', quote: 'ДККМ отвечает за контроль качества аудита.', verified: false }
const afterQuality: Evidence = { doc_id: 'r9', doc_name: after.doc_name, side: 'after', clause_id: '3.6', quote: 'ДККМ обеспечивает методологию и контроль качества аудита.', verified: false }

// Illustrative contract-shaped data. The exact quotes will be replaced by the backend result.
export const mockResult: AnalysisResult = {
  units: [
    { id: 'dnm-before', side: 'before', name: 'Департамент независимого мониторинга', abbr: 'ДНМ', positions: [], evidence: [before] },
    { id: 'dkkm-before', side: 'before', name: 'Департамент контроля качества и методологии', abbr: 'ДККМ', positions: [], evidence: [before] },
    { id: 'dnm-after', side: 'after', name: 'Департамент независимого мониторинга', abbr: 'ДНМ', positions: [], evidence: [after] },
    { id: 'dkkm-after', side: 'after', name: 'Департамент контроля качества и методологии', abbr: 'ДККМ', positions: [], evidence: [after] },
    { id: 'ditaad', side: 'after', name: 'Департамент ИТ-аудита и анализа данных', abbr: 'ДИТААД', positions: [], evidence: [after] },
    { id: 'doa', side: 'after', name: 'Департамент операционного аудита', abbr: 'ДОА', positions: [], evidence: [after] },
  ],
  unit_changes: [
    { before_unit_ids: ['dnm-before'], after_unit_ids: ['dnm-after'], status: 'preserved', rationale: 'Подразделение присутствует в обеих редакциях.', evidence: [before, after] },
    { before_unit_ids: ['dkkm-before'], after_unit_ids: ['dkkm-after'], status: 'preserved', rationale: 'Подразделение присутствует в обеих редакциях.', evidence: [before, after] },
    { before_unit_ids: [], after_unit_ids: ['ditaad'], status: 'created', rationale: 'Указано в новой структуре.', evidence: [after] },
    { before_unit_ids: [], after_unit_ids: ['doa'], status: 'created', rationale: 'Указано в новой структуре.', evidence: [after] },
  ],
  function_mappings: [
    { id: 'monitoring-1', function: 'Независимый мониторинг', category_id: 'monitoring', before_unit_id: 'dnm-before', after_unit_ids: ['dnm-after'], status: 'preserved', confidence: .94, evidence: [beforeMonitoring, afterMonitoring] },
    { id: 'quality-1', function: 'Контроль качества аудита', category_id: 'quality', before_unit_id: 'dkkm-before', after_unit_ids: ['dkkm-after'], status: 'modified', confidence: .86, evidence: [beforeQuality, afterQuality] },
  ],
  findings: [
    { id: 'structure-1', type: 'structure_change', severity: 'medium', title: 'Созданы ДИТААД и ДОА', description: 'В новой редакции структуры появились два подразделения.', recommendation: 'Проверить распределение задач и полномочий между новыми подразделениями.', unit_ids: ['ditaad', 'doa'], evidence: [before, after], critic: { verdict: 'upheld', argument: 'Новые подразделения перечислены в редакции 9 и отсутствуют в редакции 8.', counter_evidence: [] } },
  ],
  rejected_findings: [
    { id: 'rejected-1', type: 'structure_change', severity: 'low', title: 'Предположение об упразднении ДНМ', description: 'Первичная проверка ошибочно сочла ДНМ упразднённым.', unit_ids: ['dnm-before', 'dnm-after'], evidence: [before], critic: { verdict: 'refuted', argument: 'ДНМ присутствует и в новой редакции.', counter_evidence: [after] } },
  ],
  conclusion_md: 'В демонстрационном примере **ДИТААД** и **ДОА** появились в новой редакции. **ДНМ** и **ДККМ** сохранены. Для полноценного заключения необходимо выполнить анализ реальных документов.',
  documents: [
    { doc_id: 'r8', name: 'Положение о ВА · редакция 8', side: 'before', clauses: [
      { clause_id: '2.1', section: 'Функции', text: 'Бюро внутреннего аудита проводит независимую оценку деятельности компании.' },
      { clause_id: '2.2', section: 'Функции', text: 'ДНМ проводит независимый мониторинг.' },
      { clause_id: '3.4', section: 'Структура', text: 'В состав БВА входят ДНМ, ДККМ.' },
      { clause_id: '3.6', section: 'Структура', text: 'ДККМ отвечает за контроль качества аудита.' },
      { clause_id: '3.8', section: 'Структура', text: 'В состав ДККМ входит должность менеджера по аудиту.' },
      { clause_id: '5.1', section: 'Права и обязанности', text: 'Руководители подразделений представляют результаты проверок.' },
    ] },
    { doc_id: 'r9', name: 'Положение о ВА · редакция 9', side: 'after', clauses: [
      { clause_id: '2.1', section: 'Функции', text: 'Бюро внутреннего аудита проводит независимую оценку деятельности компании.' },
      { clause_id: '2.2', section: 'Функции', text: 'ДНМ проводит независимый мониторинг.' },
      { clause_id: '3.4', section: 'Структура', text: 'В состав БВА входят ДИТААД, ДОА, ДНМ, ДККМ.' },
      { clause_id: '3.6', section: 'Структура', text: 'ДККМ обеспечивает методологию и контроль качества аудита.' },
      { clause_id: '3.9', section: 'Структура', text: 'Новые подразделения формируют планы аудита по своим направлениям.' },
      { clause_id: '5.2', section: 'Права и обязанности', text: 'Руководители подразделений представляют результаты проверок.' },
    ] },
  ],
  alignments: [
    { before_clause_id: '2.1', after_clause_id: '2.1', status: 'unchanged', similarity: 1 },
    { before_clause_id: '2.2', after_clause_id: '2.2', status: 'unchanged', similarity: 1 },
    { before_clause_id: '3.4', after_clause_id: '3.4', status: 'modified', similarity: .78,
      diff: [ { op: 'equal', text: 'В состав БВА входят ' }, { op: 'insert', text: 'ДИТААД, ДОА, ' }, { op: 'equal', text: 'ДНМ, ДККМ.' } ] },
    { before_clause_id: '3.6', after_clause_id: '3.6', status: 'modified', similarity: .73,
      diff: [ { op: 'equal', text: 'ДККМ ' }, { op: 'delete', text: 'отвечает за' }, { op: 'insert', text: 'обеспечивает методологию и' }, { op: 'equal', text: ' контроль качества аудита.' } ] },
    { before_clause_id: '3.8', status: 'removed', similarity: 0 },
    { after_clause_id: '3.9', status: 'added', similarity: 0 },
    { before_clause_id: '5.1', after_clause_id: '5.2', status: 'moved', similarity: 1 },
  ],
  flows: [
    { source_unit_id: 'dnm-before', target_unit_id: 'dnm-after', function_ids: ['monitoring-1'], value: 1 },
    { source_unit_id: 'dkkm-before', target_unit_id: 'dkkm-after', function_ids: ['quality-1'], value: 1 },
  ],
  categories: [ { id: 'monitoring', name: 'Мониторинг' }, { id: 'quality', name: 'Качество аудита' } ],
  meta: { model: 'mock', provider: 'local', duration_s: 4, documents: [
    { doc_id: 'r8', name: 'Положение о ВА · редакция 8', side: 'before' },
    { doc_id: 'r9', name: 'Положение о ВА · редакция 9', side: 'after' },
  ] },
}

export function mockClause(result: AnalysisResult, docId: string, clauseId: string): ClauseResponse {
  const document = result.documents.find((item) => item.doc_id === docId)
  const clause = document?.clauses.find((item) => item.clause_id === clauseId)
  return { clause_id: clauseId, text: clause?.text ?? 'Пункт не найден в демонстрационном документе.' }
}
