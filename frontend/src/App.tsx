import { useEffect, useState } from 'react'
import { api, useMocks } from './api/client'
import type { AnalysisResult, AnalysisStatus, Clause, Evidence, Side } from './api/types'
import './App.css'

type View = 'upload' | 'progress' | 'result'
type Tab = 'conclusion' | 'units' | 'functions' | 'risks'
const tabs: { id: Tab; label: string }[] = [
  { id: 'conclusion', label: 'Заключение' }, { id: 'units', label: 'Подразделения' },
  { id: 'functions', label: 'Функции' }, { id: 'risks', label: 'Риски' },
]
const stepNames: Record<string, string> = {
  parsing: 'Чтение документов', units: 'Поиск подразделений', unit_matching: 'Сопоставление структуры',
  functions: 'Извлечение функций', function_matching: 'Сопоставление функций', duplicates: 'Поиск дублирования',
  conflicts: 'Проверка конфликтов', evidence: 'Проверка источников', report: 'Подготовка заключения',
}
const statusNames: Record<string, string> = {
  preserved: 'Сохранено', renamed: 'Переименовано', created: 'Создано', abolished: 'Упразднено',
  merged: 'Объединено', split: 'Разделено', transformed: 'Преобразовано',
  moved: 'Передано', modified: 'Изменено', lost: 'Утеряно',
}

function DocumentPicker({ side, files, onChange }: { side: Side; files: File[]; onChange: (files: File[]) => void }) {
  const name = side === 'before' ? 'До реорганизации' : 'После реорганизации'
  return <div className="document-picker">
    <div className="picker-top"><span className="picker-icon" aria-hidden="true">↥</span><span className="side-tag">{side === 'before' ? '01 / ДО' : '02 / ПОСЛЕ'}</span></div>
    <h3>{name}</h3><p>Добавьте один или несколько документов</p>
    <label className="file-button">Выбрать файлы
      <input type="file" multiple accept=".docx,.pdf,.xlsx" onChange={(event) => { onChange(Array.from(event.target.files ?? [])); event.currentTarget.value = '' }} />
    </label>
    <span className="file-hint">DOCX, PDF или XLSX</span>
    {files.length > 0 && <ul className="file-list">{files.map((file, index) => <li key={`${file.name}-${index}`}><span>▤ {file.name}</span><button type="button" aria-label={`Удалить ${file.name}`} onClick={() => onChange(files.filter((_, i) => i !== index))}>×</button></li>)}</ul>}
  </div>
}

function SourceButton({ evidence, onOpen }: { evidence: Evidence[]; onOpen: (source: Evidence) => void }) {
  return evidence.length ? <span className="source-links">{evidence.map((item, index) => <button key={`${item.doc_id}-${item.clause_id}-${index}`} className="source-button" type="button" onClick={() => onOpen(item)}>↗ {evidence.length > 1 ? `${item.side === 'before' ? 'До' : 'После'} · ` : 'Источник · '}п. {item.clause_id}</button>)}</span> : <span className="muted">Источник отсутствует</span>
}

function Conclusion({ text }: { text: string }) {
  return <div className="conclusion-text">{text.split('\n').filter(Boolean).map((line, index) => <p key={index}>{line.split(/(\*\*[^*]+\*\*)/g).map((part, i) => part.startsWith('**') && part.endsWith('**') ? <strong key={i}>{part.slice(2, -2)}</strong> : part)}</p>)}</div>
}

function App() {
  const [view, setView] = useState<View>('upload')
  const [before, setBefore] = useState<File[]>([])
  const [after, setAfter] = useState<File[]>([])
  const [analysisId, setAnalysisId] = useState<string | null>(null)
  const [status, setStatus] = useState<AnalysisStatus | null>(null)
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [tab, setTab] = useState<Tab>('conclusion')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [source, setSource] = useState<Evidence | null>(null)
  const [clause, setClause] = useState<Clause | null>(null)
  const [sourceError, setSourceError] = useState<string | null>(null)

  useEffect(() => {
    if (view !== 'progress' || !analysisId) return
    let cancelled = false
    let timer: number | undefined
    const poll = async () => {
      try {
        const current = await api.getStatus(analysisId)
        if (cancelled) return
        setStatus(current)
        if (current.status === 'failed') { setError(current.error || 'Анализ завершился с ошибкой.'); return }
        if (current.status === 'done') {
          const data = await api.getResult(analysisId)
          if (!cancelled) { setResult(data); setView('result') }
          return
        }
        timer = window.setTimeout(poll, 1200)
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : 'Не удалось получить состояние анализа.')
      }
    }
    void poll()
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [analysisId, view])

  useEffect(() => {
    if (!source || !analysisId) return
    let cancelled = false
    api.getClause(analysisId, source.doc_id, source.clause_id).then((value) => {
      if (!cancelled) setClause(value)
    }).catch((cause: unknown) => {
      if (!cancelled) setSourceError(cause instanceof Error ? cause.message : 'Не удалось загрузить пункт документа.')
    })
    return () => { cancelled = true }
  }, [source, analysisId])

  const start = async (demo: boolean) => {
    setError(null); setBusy(true); setStatus(null); setResult(null)
    try {
      const { id } = demo ? await api.createDemo() : await api.createAnalysis(before, after)
      setAnalysisId(id); setView('progress')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось запустить анализ.')
    } finally { setBusy(false) }
  }
  const openSource = (evidence: Evidence) => { setClause(null); setSourceError(null); setSource(evidence) }
  const unitName = (id: string) => result?.units.find((unit) => unit.id === id)?.abbr || result?.units.find((unit) => unit.id === id)?.name || id
  const count = (type: string) => result?.findings.filter((finding) => finding.type === type).length ?? 0
  const created = result?.unit_changes.filter((change) => change.status === 'created').length ?? 0
  const abolished = result?.unit_changes.filter((change) => change.status === 'abolished').length ?? 0

  return <div className="app-shell">
    <header className="topbar"><div className="brand"><span className="brand-mark">◈</span><span>Структура<span className="brand-light"> / Анализ</span></span></div><span className="topbar-note">ОРГАНИЗАЦИОННЫЙ АУДИТ</span><span className="mode-pill">{useMocks ? 'Демо-режим' : 'Подключено к API'}</span></header>
    <main className="main-content">
      <nav className="journey" aria-label="Этапы анализа"><span className={view === 'upload' ? 'current' : 'complete'}>01 <b>Документы</b></span><i /><span className={view === 'progress' ? 'current' : view === 'result' ? 'complete' : ''}>02 <b>Анализ</b></span><i /><span className={view === 'result' ? 'current' : ''}>03 <b>Результат</b></span></nav>
      {view === 'upload' && <>
        <div className="page-heading"><div><div className="eyebrow">НОВЫЙ АНАЛИЗ</div><h1>Сравнение структуры<br /><em>до и после изменений</em></h1><p>Загрузите документы двух редакций. Мы покажем изменения подразделений, функций и связанные риски с указанием источников.</p></div><div className="heading-decoration" aria-hidden="true">01<span>/03</span></div></div>
        <div className="picker-grid"><DocumentPicker side="before" files={before} onChange={setBefore} /><div className="compare-arrow" aria-hidden="true">→</div><DocumentPicker side="after" files={after} onChange={setAfter} /></div>
        {error && <div className="alert" role="alert">{error}</div>}
        <div className="action-row"><button className="primary-button" disabled={busy || !before.length || !after.length} onClick={() => void start(false)}>{busy ? 'Запускаем…' : 'Анализировать документы'} <span>→</span></button><span className="action-or">или</span><button className="text-button" disabled={busy} onClick={() => void start(true)}>Запустить демо-комплект ↗</button></div>
        <p className="helper-line">Для собственного анализа загрузите минимум по одному файлу в каждую колонку.</p>
      </>}
      {view === 'progress' && <section className="progress-layout"><div className="eyebrow">ИДЁТ АНАЛИЗ</div><h1>Сопоставляем документы<span className="moving-dots">...</span></h1><p className="intro">Проверяем структуру, функции и подтверждение каждого вывода документами.</p><div className="progress-card"><div className="progress-summary"><div><span className="small-label">ТЕКУЩИЙ ЭТАП</span><h2>{stepNames[status?.step || ''] || (status?.status === 'queued' ? 'В очереди' : 'Подготовка анализа')}</h2></div><strong>{Math.round((status?.progress ?? 0) * 100)}%</strong></div><div className="progress-track"><div style={{ width: `${Math.round((status?.progress ?? 0) * 100)}%` }} /></div><div className="progress-steps"><span className="active">01 Чтение файлов</span><span className={(status?.progress ?? 0) > .3 ? 'active' : ''}>02 Сравнение</span><span className={(status?.progress ?? 0) > .7 ? 'active' : ''}>03 Проверка источников</span></div></div>{error && <div className="alert" role="alert">{error}<div><button className="text-button" onClick={() => { setError(null); setView('upload') }}>Вернуться к документам</button></div></div>}</section>}
      {view === 'result' && result && <>
        <div className="result-heading"><div><div className="eyebrow">АНАЛИЗ ЗАВЕРШЁН · {result.meta.documents.length} ДОКУМЕНТА</div><h1>Результаты сравнения</h1><p>Каждый вывод можно проверить по исходному пункту документа.</p></div><button className="outline-button" onClick={() => { setView('upload'); setResult(null); setStatus(null); setAnalysisId(null); setError(null) }}>+ Новый анализ</button></div>
        <div className="metrics"><div><strong>{created}</strong><span>Создано</span></div><div><strong>{abolished}</strong><span>Упразднено</span></div><div><strong>{count('function_loss')}</strong><span>Потерь функций</span></div><div><strong>{count('duplication')}</strong><span>Дублирований</span></div><div><strong>{count('conflict_of_interest')}</strong><span>Конфликтов</span></div></div>
        <div className="result-panel"><div className="tabs" role="tablist" aria-label="Разделы результата">{tabs.map((item) => <button key={item.id} role="tab" aria-selected={tab === item.id} className={tab === item.id ? 'selected' : ''} onClick={() => setTab(item.id)}>{item.label}</button>)}</div>
          {tab === 'conclusion' && <section className="tab-content"><div className="section-kicker">ИТОГОВОЕ ЗАКЛЮЧЕНИЕ</div><h2>Что изменилось</h2><Conclusion text={result.conclusion_md} />{result.findings.length > 0 && <div className="highlight-finding"><span>КЛЮЧЕВОЙ ВЫВОД</span><h3>{result.findings[0].title}</h3><p>{result.findings[0].description}</p><SourceButton evidence={result.findings[0].evidence} onOpen={openSource} /></div>}</section>}
          {tab === 'units' && <section className="tab-content"><div className="section-kicker">СТРУКТУРА</div><h2>Изменения подразделений</h2><div className="table-wrap"><table><thead><tr><th>До</th><th>После</th><th>Статус</th><th>Основание</th></tr></thead><tbody>{result.unit_changes.map((change, index) => <tr key={index}><td>{change.before_unit_ids.map(unitName).join(', ') || '—'}</td><td>{change.after_unit_ids.map(unitName).join(', ') || '—'}</td><td><span className={`status-badge ${change.status}`}>{statusNames[change.status]}</span></td><td><SourceButton evidence={change.evidence} onOpen={openSource} /></td></tr>)}</tbody></table></div>{!result.unit_changes.length && <p className="empty-state">Изменения подразделений не найдены.</p>}</section>}
          {tab === 'functions' && <section className="tab-content"><div className="section-kicker">ФУНКЦИИ</div><h2>Сопоставление функций</h2>{result.function_mappings.length ? <div className="table-wrap"><table><thead><tr><th>Функция</th><th>До → после</th><th>Статус</th><th>Источник</th></tr></thead><tbody>{result.function_mappings.map((mapping, index) => <tr key={index}><td>{mapping.function}</td><td>{mapping.before_unit_id ? unitName(mapping.before_unit_id) : '—'} → {mapping.after_unit_ids.map(unitName).join(', ') || '—'}</td><td><span className={`status-badge ${mapping.status}`}>{statusNames[mapping.status]}</span></td><td><SourceButton evidence={mapping.evidence} onOpen={openSource} /></td></tr>)}</tbody></table></div> : <p className="empty-state">В этом результате сопоставления функций нет.</p>}</section>}
          {tab === 'risks' && <section className="tab-content"><div className="section-kicker">НАХОДКИ</div><h2>Риски и рекомендации</h2>{result.findings.length ? <div className="finding-list">{result.findings.map((finding) => <article className="finding-card" key={finding.id}><div className="finding-meta"><span className={`severity ${finding.severity}`}>{finding.severity === 'high' ? 'Высокий' : finding.severity === 'medium' ? 'Средний' : 'Низкий'} приоритет</span><span>{finding.type === 'structure_change' ? 'Структура' : finding.type === 'function_loss' ? 'Потеря функции' : finding.type === 'duplication' ? 'Дублирование' : 'Конфликт интересов'}</span></div><h3>{finding.title}</h3><p>{finding.description}</p>{finding.recommendation && <p className="recommendation"><b>Рекомендация:</b> {finding.recommendation}</p>}<SourceButton evidence={finding.evidence} onOpen={openSource} /></article>)}</div> : <p className="empty-state">Риски в этом результате не найдены.</p>}</section>}
        </div>
      </>}
    </main>
    <footer>Выводы носят рекомендательный характер и требуют проверки ответственным сотрудником.</footer>
    {source && <div className="source-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) setSource(null) }}><aside className="source-panel" aria-label="Источник"><div className="source-header"><div><div className="eyebrow">ПЕРВОИСТОЧНИК</div><h2>Пункт {source.clause_id}</h2></div><button className="close-button" aria-label="Закрыть источник" onClick={() => setSource(null)}>×</button></div><div className="source-document"><span>ДОКУМЕНТ</span><strong>{source.doc_name}</strong><small>{source.side === 'before' ? 'До реорганизации' : 'После реорганизации'}</small></div><div className="source-body"><span className="small-label">ТЕКСТ ПУНКТА</span>{sourceError ? <p className="alert" role="alert">{sourceError}</p> : clause ? <p>{clause.text.includes(source.quote) ? <>{clause.text.split(source.quote)[0]}<mark>{source.quote}</mark>{clause.text.split(source.quote).slice(1).join(source.quote)}</> : clause.text}</p> : <p className="muted">Загружаем пункт…</p>}</div><div className="source-footer">{source.verified ? '✓ Цитата проверена' : 'Цитата требует проверки'}</div></aside></div>}
  </div>
}

export default App
