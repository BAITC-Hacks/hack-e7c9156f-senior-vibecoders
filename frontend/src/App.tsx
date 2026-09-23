import { useEffect, useState } from 'react'
import { api, useMocks } from './api/client'
import type { AnalysisResult, AnalysisStatus, ClauseResponse, Evidence, Finding, Side } from './api/types'
import { DocumentComparison } from './components/DocumentComparison'
import { FunctionFlows } from './components/FunctionFlows'
import './App.css'

type View = 'upload' | 'progress' | 'result'
type Tab = 'comparison' | 'conclusion' | 'units' | 'functions' | 'flows' | 'risks'
const tabs: { id: Tab; label: string }[] = [
  { id: 'comparison', label: 'Сравнение документов' }, { id: 'conclusion', label: 'Заключение' }, { id: 'units', label: 'Подразделения' },
  { id: 'functions', label: 'Функции' }, { id: 'flows', label: 'Перемещение функций' }, { id: 'risks', label: 'Риски' },
]
const stepNames: Record<string, string> = {
  parsing: 'Чтение документов', alignment: 'Сопоставление пунктов', units: 'Поиск подразделений',
  functions: 'Извлечение функций', conflicts: 'Проверка конфликтов', evidence: 'Проверка источников',
  critic: 'Проверка выводов', report: 'Подготовка заключения',
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
    <h3>{name}</h3><p>Добавьте документ этой редакции</p>
    <label className="file-button">Выбрать файлы
      <input type="file" accept=".docx,.pdf,.xlsx" onChange={(event) => { onChange(Array.from(event.target.files ?? []).slice(0, 1)); event.currentTarget.value = '' }} />
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

function FindingCard({ finding, result, onOpen, rejected = false }: { finding: Finding; result: AnalysisResult; onOpen: (source: Evidence) => void; rejected?: boolean }) {
  const verdict = finding.critic
  return <article className={`finding-card ${rejected ? 'finding-rejected' : ''}`}>
    <div className="finding-meta"><span className={`severity ${finding.severity}`}>{finding.severity === 'high' ? 'Высокий' : finding.severity === 'medium' ? 'Средний' : 'Низкий'} приоритет</span><span>{finding.type === 'structure_change' ? 'Структура' : finding.type === 'function_loss' ? 'Потеря функции' : finding.type === 'duplication' ? 'Дублирование' : 'Конфликт интересов'}</span></div>
    <h3>{finding.title}</h3><p>{finding.description}</p>
    {finding.unit_ids.length > 0 && <p className="finding-units">Подразделения: {finding.unit_ids.map((id) => result.units.find((unit) => unit.id === id)?.abbr || result.units.find((unit) => unit.id === id)?.name || id).join(', ')}</p>}
    {finding.rule_id && <p className="finding-rule">Правило разделения обязанностей: <code>{finding.rule_id}</code></p>}
    {finding.recommendation && !rejected && <p className="recommendation"><b>Рекомендация:</b> {finding.recommendation}</p>}
    <SourceButton evidence={finding.evidence} onOpen={onOpen} />
    {verdict && <div className="critic-verdict"><strong>{verdict.verdict === 'upheld' ? 'Вывод подтверждён критиком' : verdict.verdict === 'refuted' ? 'Вывод опровергнут критиком' : 'Вывод требует проверки'}</strong><p>{verdict.argument}</p>{verdict.counter_evidence.length > 0 && <><span>Контраргументы:</span><SourceButton evidence={verdict.counter_evidence} onOpen={onOpen} /></>}</div>}
  </article>
}

function App() {
  const [view, setView] = useState<View>('upload')
  const [before, setBefore] = useState<File[]>([])
  const [after, setAfter] = useState<File[]>([])
  const [analysisId, setAnalysisId] = useState<string | null>(null)
  const [status, setStatus] = useState<AnalysisStatus | null>(null)
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [tab, setTab] = useState<Tab>('comparison')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [source, setSource] = useState<Evidence | null>(null)
  const [clause, setClause] = useState<ClauseResponse | null>(null)
  const [sourceError, setSourceError] = useState<string | null>(null)
  const [reportBusy, setReportBusy] = useState(false)
  const [reportError, setReportError] = useState<string | null>(null)

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
          if (!cancelled) { setResult(data); setTab('comparison'); setView('result') }
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
  const downloadReport = async () => {
    if (!analysisId) return
    setReportBusy(true); setReportError(null)
    try {
      const blob = await api.downloadReport(analysisId)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `analysis-${analysisId}.docx`
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (cause) {
      setReportError(cause instanceof Error ? cause.message : 'Не удалось скачать отчёт.')
    } finally { setReportBusy(false) }
  }
  const unitName = (id: string) => result?.units.find((unit) => unit.id === id)?.abbr || result?.units.find((unit) => unit.id === id)?.name || id
  const count = (type: string) => result?.findings.filter((finding) => finding.type === type).length ?? 0
  const created = result?.unit_changes.filter((change) => change.status === 'created').length ?? 0
  const abolished = result?.unit_changes.filter((change) => change.status === 'abolished').length ?? 0
  const isLocalPreview = result?.meta.model === 'local-preview'

  return <div className="app-shell">
    <header className="topbar"><div className="brand"><span className="brand-mark" aria-hidden="true">◉</span><span>Kazakhtelecom <span className="brand-light">Business</span><small>Анализ структуры</small></span></div><span className="topbar-note">ОРГАНИЗАЦИОННЫЙ АУДИТ</span><span className="mode-pill">{useMocks ? 'Демо-режим' : 'Подключено к API'}</span></header>
    <main className="main-content">
      <nav className="journey" aria-label="Этапы анализа"><span className={view === 'upload' ? 'current' : 'complete'}>01 <b>Документы</b></span><i /><span className={view === 'progress' ? 'current' : view === 'result' ? 'complete' : ''}>02 <b>Анализ</b></span><i /><span className={view === 'result' ? 'current' : ''}>03 <b>Результат</b></span></nav>
      {view === 'upload' && <>
        <div className="page-heading"><div><div className="eyebrow">НОВЫЙ АНАЛИЗ</div><h1>Сравнение документов<br /><em>до и после изменений</em></h1><p>Загрузите две редакции. Мы покажем изменения в тексте, структуре и функциях с указанием источников.</p></div><div className="heading-decoration" aria-hidden="true">01<span>/03</span></div></div>
        <div className="picker-grid"><DocumentPicker side="before" files={before} onChange={setBefore} /><div className="compare-arrow" aria-hidden="true">→</div><DocumentPicker side="after" files={after} onChange={setAfter} /></div>
        {error && <div className="alert" role="alert">{error}</div>}
        <div className="action-row"><button className="primary-button" disabled={busy || !before.length || !after.length} onClick={() => void start(false)}>{busy ? 'Читаем файлы…' : useMocks ? 'Сравнить тексты файлов' : 'Анализировать документы'} <span>→</span></button><span className="action-or">или</span><button className="text-button" disabled={busy} onClick={() => void start(true)}>Запустить демо-комплект ↗</button></div>
        <p className="helper-line">Для сравнения загрузите по одному файлу в каждую колонку. {useMocks && 'В демо-режиме файлы читаются в браузере; выводы ИИ не формируются.'}</p>
      </>}
      {view === 'progress' && <section className="progress-layout"><div className="eyebrow">ОБРАБОТКА ДОКУМЕНТОВ</div><h1>Сопоставляем документы<span className="moving-dots">...</span></h1><p className="intro">Готовим текст двух редакций и находим различия.</p><div className="progress-card"><div className="progress-summary"><div><span className="small-label">ТЕКУЩИЙ ЭТАП</span><h2>{stepNames[status?.step || ''] || (status?.status === 'queued' ? 'В очереди' : 'Подготовка анализа')}</h2></div><strong>{Math.round((status?.progress ?? 0) * 100)}%</strong></div><div className="progress-track"><div style={{ width: `${Math.round((status?.progress ?? 0) * 100)}%` }} /></div><div className="progress-steps"><span className="active">01 Чтение файлов</span><span className={(status?.progress ?? 0) > .3 ? 'active' : ''}>02 Сравнение</span><span className={(status?.progress ?? 0) > .7 ? 'active' : ''}>03 Проверка источников</span></div></div>{error && <div className="alert" role="alert">{error}<div><button className="text-button" onClick={() => { setError(null); setView('upload') }}>Вернуться к документам</button></div></div>}</section>}
      {view === 'result' && result && <>
        <div className="result-heading"><div><div className="eyebrow">{isLocalPreview ? 'ЛОКАЛЬНЫЙ ПРЕДПРОСМОТР' : 'АНАЛИЗ ЗАВЕРШЁН'} · {result.meta.documents.length} ДОКУМЕНТА</div><h1>{isLocalPreview ? 'Текст загруженных файлов' : 'Результаты сравнения'}</h1><p>{isLocalPreview ? 'Показан извлечённый текст и технические различия. Выводы ИИ появятся после подключения backend.' : 'Каждый вывод можно проверить по исходному пункту документа.'}</p></div><div className="result-actions">{!useMocks && <button className="outline-button" disabled={reportBusy} onClick={() => void downloadReport()}>{reportBusy ? 'Скачиваем…' : 'Скачать отчёт DOCX'}</button>}<button className="outline-button" onClick={() => { setView('upload'); setResult(null); setStatus(null); setAnalysisId(null); setError(null); setReportError(null) }}>+ Новый анализ</button></div></div>
        {reportError && <div className="alert" role="alert">{reportError}</div>}
        {!isLocalPreview && <div className="metrics"><div><strong>{created}</strong><span>Создано</span></div><div><strong>{abolished}</strong><span>Упразднено</span></div><div><strong>{count('function_loss')}</strong><span>Потерь функций</span></div><div><strong>{count('duplication')}</strong><span>Дублирований</span></div><div><strong>{count('conflict_of_interest')}</strong><span>Конфликтов</span></div></div>}
        <div className="result-panel"><div className="tabs" role="tablist" aria-label="Разделы результата">{tabs.filter((item) => !isLocalPreview || item.id === 'comparison').map((item) => <button key={item.id} role="tab" aria-selected={tab === item.id} className={tab === item.id ? 'selected' : ''} onClick={() => setTab(item.id)}>{item.label}</button>)}</div>
          {tab === 'comparison' && <DocumentComparison key={analysisId} result={result} />}
          {tab === 'conclusion' && <section className="tab-content"><div className="section-kicker">ИТОГОВОЕ ЗАКЛЮЧЕНИЕ</div><h2>Что изменилось</h2><Conclusion text={result.conclusion_md} />{result.findings.length > 0 && <div className="highlight-finding"><span>КЛЮЧЕВОЙ ВЫВОД</span><h3>{result.findings[0].title}</h3><p>{result.findings[0].description}</p><SourceButton evidence={result.findings[0].evidence} onOpen={openSource} /></div>}</section>}
          {tab === 'units' && <section className="tab-content"><div className="section-kicker">СТРУКТУРА</div><h2>Изменения подразделений</h2><div className="table-wrap"><table><thead><tr><th>До</th><th>После</th><th>Статус</th><th>Обоснование и источник</th></tr></thead><tbody>{result.unit_changes.map((change, index) => <tr key={index}><td>{change.before_unit_ids.map(unitName).join(', ') || '—'}</td><td>{change.after_unit_ids.map(unitName).join(', ') || '—'}</td><td><span className={`status-badge ${change.status}`}>{statusNames[change.status]}</span></td><td><p className="table-rationale">{change.rationale}</p><SourceButton evidence={change.evidence} onOpen={openSource} /></td></tr>)}</tbody></table></div>{!result.unit_changes.length && <p className="empty-state">Изменения подразделений не найдены.</p>}{result.units.length > 0 && <details className="unit-details"><summary>Состав подразделений ({result.units.length})</summary><div className="unit-grid">{result.units.map((unit) => <article key={unit.id}><span>{unit.side === 'before' ? 'ДО' : 'ПОСЛЕ'}</span><h3>{unit.name}</h3>{unit.parent && <p>В составе: {unitName(unit.parent)}</p>}{unit.positions.length > 0 && <p>Должности: {unit.positions.join(', ')}</p>}<SourceButton evidence={unit.evidence} onOpen={openSource} /></article>)}</div></details>}</section>}
          {tab === 'functions' && <section className="tab-content"><div className="section-kicker">ФУНКЦИИ</div><h2>Сопоставление функций</h2>{result.function_mappings.length ? <div className="table-wrap"><table><thead><tr><th>Функция / категория</th><th>До → после</th><th>Статус</th><th>Уверенность</th><th>Источник</th></tr></thead><tbody>{result.function_mappings.map((mapping) => <tr key={mapping.id}><td><strong>{mapping.function}</strong><small className="function-category">{result.categories.find((item) => item.id === mapping.category_id)?.name ?? mapping.category_id}</small></td><td>{mapping.before_unit_id ? unitName(mapping.before_unit_id) : '—'} → {mapping.after_unit_ids.map(unitName).join(', ') || '—'}</td><td><span className={`status-badge ${mapping.status}`}>{statusNames[mapping.status]}</span></td><td>{Math.round(mapping.confidence * 100)}%</td><td><SourceButton evidence={mapping.evidence} onOpen={openSource} /></td></tr>)}</tbody></table></div> : <p className="empty-state">В этом результате сопоставления функций нет.</p>}</section>}
          {tab === 'flows' && <section className="tab-content"><div className="section-kicker">ПЕРЕМЕЩЕНИЕ ФУНКЦИЙ</div><h2>Как распределились функции</h2><FunctionFlows result={result} onOpenSource={openSource} /></section>}
          {tab === 'risks' && <section className="tab-content"><div className="section-kicker">НАХОДКИ</div><h2>Риски и рекомендации</h2>{result.findings.length ? <div className="finding-list">{result.findings.map((finding) => <FindingCard key={finding.id} finding={finding} result={result} onOpen={openSource} />)}</div> : <p className="empty-state">Подтверждённых рисков в этом результате нет.</p>}{result.rejected_findings.length > 0 && <div className="rejected-section"><h3>Отклонённые выводы</h3><p>Агент-критик опроверг эти предположения. Они не включены в заключение.</p><div className="finding-list">{result.rejected_findings.map((finding) => <FindingCard key={finding.id} finding={finding} result={result} onOpen={openSource} rejected />)}</div></div>}</section>}
        </div>
      </>}
    </main>
    <footer>Выводы носят рекомендательный характер и требуют проверки ответственным сотрудником.</footer>
    {source && <div className="source-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) setSource(null) }}><aside className="source-panel" aria-label="Источник"><div className="source-header"><div><div className="eyebrow">ПЕРВОИСТОЧНИК</div><h2>Пункт {source.clause_id}</h2></div><button className="close-button" aria-label="Закрыть источник" onClick={() => setSource(null)}>×</button></div><div className="source-document"><span>ДОКУМЕНТ</span><strong>{source.doc_name}</strong><small>{source.side === 'before' ? 'До реорганизации' : 'После реорганизации'}</small></div><div className="source-body"><span className="small-label">ТЕКСТ ПУНКТА</span>{sourceError ? <p className="alert" role="alert">{sourceError}</p> : clause ? <p>{clause.text.includes(source.quote) ? <>{clause.text.split(source.quote)[0]}<mark>{source.quote}</mark>{clause.text.split(source.quote).slice(1).join(source.quote)}</> : clause.text}</p> : <p className="muted">Загружаем пункт…</p>}</div><div className="source-footer">{source.verified ? '✓ Цитата проверена' : 'Цитата требует проверки'}</div></aside></div>}
  </div>
}

export default App
