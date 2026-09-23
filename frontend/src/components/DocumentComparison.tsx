import { useRef, useState } from 'react'
import type { AnalysisResult, Clause, ClauseAlignment, DocumentText, Side } from '../api/types'

type Filter = 'all' | 'changed'

function ClauseText({ clause, alignment, side }: {
  clause: Clause
  alignment?: ClauseAlignment
  side: Side
}) {
  if (alignment?.status === 'modified' && alignment.diff?.length) {
    const segments = alignment.diff.filter(({ op }) =>
      op === 'equal' || op === (side === 'before' ? 'delete' : 'insert'))
    // Always show the complete original text when a backend diff is incomplete.
    if (segments.map(({ text }) => text).join('') === clause.text) {
      return <span>{segments.map(({ op, text }, index) =>
        op === 'equal' ? <span key={index}>{text}</span> :
          <mark key={index} className={side === 'before' ? 'diff-deletion' : 'diff-insertion'}>{text}</mark>,
      )}</span>
    }
  }

  if (alignment?.status === 'added' || alignment?.status === 'removed') {
    return <mark className={side === 'before' ? 'diff-deletion' : 'diff-insertion'}>{clause.text}</mark>
  }

  return <span>{clause.text}</span>
}

function DocumentReader({ document, side, filter, alignments, registerRef }: {
  document: DocumentText
  side: Side
  filter: Filter
  alignments: Map<string, ClauseAlignment>
  registerRef: (side: Side, clauseId: string, node: HTMLElement | null) => void
}) {
  const visibleClauses = document.clauses.filter((clause) => {
    const status = alignments.get(clause.clause_id)?.status
    return filter === 'all' || (status !== undefined && status !== 'unchanged')
  })

  return <section className="document-reader" aria-label={side === 'before' ? 'Полный текст старой редакции' : 'Полный текст новой редакции'}>
    <header className="reader-header">
      <span>{side === 'before' ? 'СТАРАЯ РЕДАКЦИЯ' : 'НОВАЯ РЕДАКЦИЯ'}</span>
      <strong>{document.name}</strong>
      <small>{filter === 'all' ? `Весь текст · ${document.clauses.length} фрагментов` : `Показано ${visibleClauses.length} фрагментов`}</small>
    </header>
    <div className="reader-body">
      {visibleClauses.map((clause, index) => {
        const alignment = alignments.get(clause.clause_id)
        const status = alignment?.status
        const sectionChanged = index === 0 || visibleClauses[index - 1].section !== clause.section
        return <div className={`reader-clause ${status ?? 'unmatched'}`}
          key={clause.clause_id}
          ref={(node) => registerRef(side, clause.clause_id, node)}>
          {sectionChanged && clause.section && <h3 className="reader-section">{clause.section}</h3>}
          <p className="reader-text"><ClauseText clause={clause} alignment={alignment} side={side} /></p>
        </div>
      })}
      {!visibleClauses.length && <p className="reader-empty">Пунктов для показа нет.</p>}
    </div>
  </section>
}

export function DocumentComparison({ result }: { result: AnalysisResult }) {
  const [filter, setFilter] = useState<Filter>('all')
  const [activeChange, setActiveChange] = useState(-1)
  const clauseRefs = useRef(new Map<string, HTMLElement>())
  const documents = result.documents ?? []
  const before = documents.find((item) => item.side === 'before')
  const after = documents.find((item) => item.side === 'after')
  const alignments = result.alignments ?? []
  const changedAlignments = alignments.filter((item) => item.status !== 'unchanged')
  const beforeAlignments = new Map(alignments.filter((item) => item.before_clause_id)
    .map((item) => [item.before_clause_id!, item]))
  const afterAlignments = new Map(alignments.filter((item) => item.after_clause_id)
    .map((item) => [item.after_clause_id!, item]))
  const extraDocuments = documents.filter((item) => item.side === 'before').length > 1
    || documents.filter((item) => item.side === 'after').length > 1

  function registerRef(side: Side, clauseId: string, node: HTMLElement | null) {
    const key = `${side}:${clauseId}`
    if (node) clauseRefs.current.set(key, node)
    else clauseRefs.current.delete(key)
  }

  function jump(direction: -1 | 1) {
    if (!changedAlignments.length) return
    const next = direction === 1
      ? (activeChange + 1) % changedAlignments.length
      : (activeChange <= 0 ? changedAlignments.length - 1 : activeChange - 1)
    setActiveChange(next)
    const alignment = changedAlignments[next]
    if (alignment.before_clause_id) {
      clauseRefs.current.get(`before:${alignment.before_clause_id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
    if (alignment.after_clause_id) {
      clauseRefs.current.get(`after:${alignment.after_clause_id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }

  if (!before || !after) {
    return <section className="comparison-unavailable">
      <div className="section-kicker">СРАВНЕНИЕ ТЕКСТА</div>
      <h2>Текст документов пока недоступен</h2>
      <p>Результат анализа не содержит текст обеих редакций. Сводные выводы доступны в соседних вкладках.</p>
    </section>
  }

  return <section className="comparison">
    <div className="comparison-intro">
      <div><div className="section-kicker">ПОЛНЫЙ ТЕКСТ ДОКУМЕНТОВ</div><h2>До и после изменений</h2>
        <p>Обе редакции показаны целиком, в исходном порядке. Выделение показывает изменения внутри текста.</p></div>
      <div className="change-total"><strong>{changedAlignments.length}</strong><span>изменений</span></div>
    </div>
    {result.meta.model === 'mock' && <p className="comparison-notice">Демо-режим показывает короткий образец документа. При подключении backend здесь появится весь текст загруженной пары файлов.</p>}
    {extraDocuments && <p className="comparison-notice">Сейчас показана первая пара документов. Сравнение нескольких файлов добавим позже.</p>}
    {!alignments.length && <p className="comparison-notice">Текст показан целиком. Сопоставление изменений пока отсутствует в результате анализа.</p>}
    <div className="comparison-toolbar">
      <div className="comparison-filters" aria-label="Фильтр пунктов">
        <button className={filter === 'all' ? 'active' : ''} aria-pressed={filter === 'all'} onClick={() => { setFilter('all'); setActiveChange(-1) }}>Весь текст</button>
        <button className={filter === 'changed' ? 'active' : ''} aria-pressed={filter === 'changed'} disabled={!alignments.length} onClick={() => { setFilter('changed'); setActiveChange(-1) }}>Только изменения <span>{changedAlignments.length}</span></button>
      </div>
      <div className="change-navigation">
        <button disabled={!changedAlignments.length} onClick={() => jump(-1)} aria-label="Предыдущее изменение">↑</button>
        <button disabled={!changedAlignments.length} onClick={() => jump(1)} aria-label="Следующее изменение">↓</button>
      </div>
    </div>
    <div className="document-readers">
      <DocumentReader document={before} side="before" filter={filter} alignments={beforeAlignments} registerRef={registerRef} />
      <DocumentReader document={after} side="after" filter={filter} alignments={afterAlignments} registerRef={registerRef} />
    </div>
  </section>
}
