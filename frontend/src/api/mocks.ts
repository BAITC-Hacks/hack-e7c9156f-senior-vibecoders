import type { AnalysisResult, Clause, Evidence } from './types'

const before: Evidence = {
  doc_id: 'r8', doc_name: 'Положение о ВА · редакция 8', side: 'before', clause_id: '3.4',
  quote: 'ДНМ, ДККМ', verified: false,
}
const after: Evidence = {
  doc_id: 'r9', doc_name: 'Положение о ВА · редакция 9', side: 'after', clause_id: '3.4',
  quote: 'ДИТААД, ДОА, ДНМ, ДККМ', verified: false,
}

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
  function_mappings: [],
  findings: [
    { id: 'structure-1', type: 'structure_change', severity: 'medium', title: 'Созданы ДИТААД и ДОА', description: 'В новой редакции структуры появились два подразделения.', recommendation: 'Проверить распределение задач и полномочий между новыми подразделениями.', unit_ids: ['ditaad', 'doa'], evidence: [before, after] },
  ],
  conclusion_md: 'В демонстрационном примере **ДИТААД** и **ДОА** появились в новой редакции. **ДНМ** и **ДККМ** сохранены. Для полноценного заключения необходимо выполнить анализ реальных документов.',
  meta: { model: 'mock', provider: 'local', duration_s: 4, documents: [
    { doc_id: 'r8', name: 'Положение о ВА · редакция 8', side: 'before' },
    { doc_id: 'r9', name: 'Положение о ВА · редакция 9', side: 'after' },
  ] },
}

export function mockClause(docId: string, clauseId: string): Clause {
  const evidence = docId === 'r8' ? before : after
  return { clause_id: clauseId, text: `Демонстрационный текст пункта ${clauseId}: ${evidence.quote}. Точный текст будет получен из загруженного документа через API.` }
}
