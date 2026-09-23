import { diffArrays, diffWordsWithSpace } from 'diff'
import type { AnalysisResult, Clause, ClauseAlignment, DocumentText, Side } from './types'

function paragraphsToClauses(paragraphs: string[], section: string): Clause[] {
  return paragraphs
    .map((text) => text.trim())
    .filter(Boolean)
    .map((text, index) => ({
      clause_id: String(index + 1),
      section,
      text,
    }))
}

async function readDocx(file: File): Promise<Clause[]> {
  const mammoth = (await import('mammoth')).default
  const { value } = await mammoth.extractRawText({ arrayBuffer: await file.arrayBuffer() })
  return paragraphsToClauses(value.split(/\n\s*\n/), 'Текст документа')
}

async function readPdf(file: File): Promise<Clause[]> {
  const pdfjs = await import('pdfjs-dist')
  const workerUrl = (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default
  pdfjs.GlobalWorkerOptions.workerSrc = workerUrl
  const task = pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()) })
  const pdf = await task.promise
  const clauses: Clause[] = []
  try {
    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
      const page = await pdf.getPage(pageNumber)
      const content = await page.getTextContent()
      const lines: string[] = []
      let line = ''
      for (const item of content.items) {
        if (!('str' in item)) continue
        line += item.str
        if (item.hasEOL) {
          if (line.trim()) lines.push(line.trim())
          line = ''
        } else if (item.str && !/\s$/.test(item.str)) {
          line += ' '
        }
      }
      if (line.trim()) lines.push(line.trim())
      lines.forEach((text, index) => clauses.push({
        clause_id: `${pageNumber}.${index + 1}`,
        section: `Страница ${pageNumber}`,
        text,
      }))
    }
  } finally {
    await task.destroy()
  }
  return clauses
}

async function readXlsx(file: File): Promise<Clause[]> {
  const readXlsxFile = (await import('read-excel-file/browser')).default
  const sheets = await readXlsxFile(file)
  const clauses: Clause[] = []
  sheets.forEach(({ sheet, data }, sheetIndex) => {
    data.forEach((row, rowIndex) => {
      const text = row.map((cell) => cell == null ? '' : String(cell)).join(' | ').trim()
      if (text.replace(/[|\s]/g, '')) clauses.push({
        clause_id: `${sheetIndex + 1}.${rowIndex + 1}`,
        section: sheet,
        text,
      })
    })
  })
  return clauses
}

async function readDocument(file: File, side: Side): Promise<DocumentText> {
  const extension = file.name.split('.').pop()?.toLowerCase()
  let clauses: Clause[]
  if (extension === 'docx') clauses = await readDocx(file)
  else if (extension === 'pdf') clauses = await readPdf(file)
  else if (extension === 'xlsx') clauses = await readXlsx(file)
  else throw new Error(`Формат файла «${file.name}» не поддерживается. Выберите DOCX, PDF или XLSX.`)
  if (!clauses.length) {
    throw new Error(`Не удалось извлечь текст из файла «${file.name}». Для сканированного PDF потребуется OCR на backend.`)
  }
  return { doc_id: side, name: file.name, side, clauses }
}

function wordDiff(before: string, after: string): ClauseAlignment['diff'] {
  // Avoid a long synchronous comparison for unusually large paragraphs.
  if (before.length + after.length > 8000) return undefined
  return diffWordsWithSpace(before, after).map(({ added, removed, value }) => ({
    op: added ? 'insert' as const : removed ? 'delete' as const : 'equal' as const,
    text: value,
  }))
}

function alignClauses(before: Clause[], after: Clause[]): ClauseAlignment[] {
  const chunks = diffArrays(before.map((item) => item.text), after.map((item) => item.text))
  const alignments: ClauseAlignment[] = []
  let beforeIndex = 0
  let afterIndex = 0
  let chunkIndex = 0
  while (chunkIndex < chunks.length) {
    const chunk = chunks[chunkIndex]
    if (!chunk.added && !chunk.removed) {
      for (let index = 0; index < chunk.value.length; index += 1) {
        alignments.push({
          before_clause_id: before[beforeIndex++].clause_id,
          after_clause_id: after[afterIndex++].clause_id,
          status: 'unchanged',
          similarity: 1,
        })
      }
      chunkIndex += 1
      continue
    }

    let removed = 0
    let added = 0
    while (chunkIndex < chunks.length && (chunks[chunkIndex].added || chunks[chunkIndex].removed)) {
      if (chunks[chunkIndex].added) added += chunks[chunkIndex].value.length
      if (chunks[chunkIndex].removed) removed += chunks[chunkIndex].value.length
      chunkIndex += 1
    }
    const paired = Math.min(removed, added)
    for (let index = 0; index < paired; index += 1) {
      const oldClause = before[beforeIndex++]
      const newClause = after[afterIndex++]
      const diff = wordDiff(oldClause.text, newClause.text)
      const equalLength = diff?.filter((part) => part.op === 'equal').reduce((sum, part) => sum + part.text.length, 0) ?? 0
      alignments.push({
        before_clause_id: oldClause.clause_id,
        after_clause_id: newClause.clause_id,
        status: 'modified',
        similarity: equalLength / Math.max(oldClause.text.length, newClause.text.length, 1),
        ...(diff ? { diff } : {}),
      })
    }
    for (let index = paired; index < removed; index += 1) {
      alignments.push({ before_clause_id: before[beforeIndex++].clause_id, status: 'removed', similarity: 0 })
    }
    for (let index = paired; index < added; index += 1) {
      alignments.push({ after_clause_id: after[afterIndex++].clause_id, status: 'added', similarity: 0 })
    }
  }
  return alignments
}

export async function createLocalPreview(beforeFile: File, afterFile: File): Promise<AnalysisResult> {
  const started = performance.now()
  const [before, after] = await Promise.all([
    readDocument(beforeFile, 'before'),
    readDocument(afterFile, 'after'),
  ])
  return {
    units: [],
    unit_changes: [],
    function_mappings: [],
    findings: [],
    rejected_findings: [],
    conclusion_md: 'Это локальный предпросмотр текста. Анализ подразделений, функций и рисков появится после подключения backend и ИИ-агента.',
    documents: [before, after],
    alignments: alignClauses(before.clauses, after.clauses),
    flows: [],
    categories: [],
    meta: {
      model: 'local-preview',
      provider: 'browser',
      duration_s: (performance.now() - started) / 1000,
      documents: [
        { doc_id: before.doc_id, name: before.name, side: before.side },
        { doc_id: after.doc_id, name: after.name, side: after.side },
      ],
    },
  }
}
