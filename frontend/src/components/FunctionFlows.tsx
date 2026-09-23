import { useState } from 'react'
import type { AnalysisResult, Evidence, Flow } from '../api/types'

const colors = ['#0878c5', '#2b9bb5', '#4968b4', '#6b83bd', '#3d9a7b', '#8a75af']

type Node = { id: string; name: string; value: number; y: number; height: number }

function FlowDetails({ flow, result, onOpenSource }: {
  flow: Flow
  result: AnalysisResult
  onOpenSource: (source: Evidence) => void
}) {
  const mappings = flow.function_ids.map((id) => result.function_mappings.find((item) => item.id === id))
  return <div className="flow-details">
    <h3>Функции в переходе</h3>
    <ul>{flow.function_ids.map((id, index) => {
      const mapping = mappings[index]
      return <li key={id}>
        <strong>{mapping?.function ?? `Функция ${id}`}</strong>
        {mapping && <span>{mapping.status === 'lost' ? 'Потеряна' : mapping.status === 'moved' ? 'Передана' : mapping.status === 'modified' ? 'Изменена' : 'Сохранена'}</span>}
        {mapping?.evidence.map((source, sourceIndex) => <button key={`${source.doc_id}-${source.clause_id}-${sourceIndex}`} type="button" onClick={() => onOpenSource(source)}>Источник · {source.doc_name}, п. {source.clause_id}</button>)}
      </li>
    })}</ul>
  </div>
}

export function FunctionFlows({ result, onOpenSource }: { result: AnalysisResult; onOpenSource: (source: Evidence) => void }) {
  const [selected, setSelected] = useState<number | null>(null)
  const flows = result.flows.filter((flow) => flow.value > 0)
  if (!flows.length) return <p className="empty-state">Данных о перемещении функций пока нет.</p>

  const unitName = (id: string) => id === 'lost' ? 'Потеряны' : result.units.find((unit) => unit.id === id)?.abbr || result.units.find((unit) => unit.id === id)?.name || id
  const sourceIds = [...new Set(flows.map((flow) => flow.source_unit_id))]
  const targetIds = [...new Set(flows.map((flow) => flow.target_unit_id))]
  const scale = 18
  const gap = 22
  const buildNodes = (ids: string[], key: 'source_unit_id' | 'target_unit_id'): Node[] => {
    let y = 0
    return ids.map((id) => {
      const value = flows.filter((flow) => flow[key] === id).reduce((sum, flow) => sum + flow.value, 0)
      const height = Math.max(34, value * scale)
      const node = { id, name: unitName(id), value, y, height }
      y += height + gap
      return node
    })
  }
  const sources = buildNodes(sourceIds, 'source_unit_id')
  const targets = buildNodes(targetIds, 'target_unit_id')
  const columnHeight = (nodes: Node[]) => nodes.at(-1) ? nodes.at(-1)!.y + nodes.at(-1)!.height : 0
  const height = Math.max(280, columnHeight(sources), columnHeight(targets)) + 40
  const shift = (nodes: Node[]) => (height - columnHeight(nodes)) / 2
  const sourceOffsets = new Map(sources.map((node) => [node.id, node.y + shift(sources) + (node.height - node.value * scale) / 2]))
  const targetOffsets = new Map(targets.map((node) => [node.id, node.y + shift(targets) + (node.height - node.value * scale) / 2]))
  const ribbons = flows.map((flow, index) => {
    const sy = sourceOffsets.get(flow.source_unit_id) ?? 0
    const ty = targetOffsets.get(flow.target_unit_id) ?? 0
    const thickness = flow.value * scale
    sourceOffsets.set(flow.source_unit_id, sy + thickness)
    targetOffsets.set(flow.target_unit_id, ty + thickness)
    const path = `M 260 ${sy} C 435 ${sy}, 525 ${ty}, 700 ${ty} L 700 ${ty + thickness} C 525 ${ty + thickness}, 435 ${sy + thickness}, 260 ${sy + thickness} Z`
    return { path, color: colors[sourceIds.indexOf(flow.source_unit_id) % colors.length], index, flow }
  })

  return <>
    <p className="flow-intro">Толщина линии соответствует числу функций. Нажмите на переход, чтобы увидеть функции и источники.</p>
    <div className="flow-chart-wrap"><svg className="flow-chart" viewBox={`0 0 960 ${height}`} role="img" aria-label="Перемещение функций между подразделениями до и после реорганизации">
      <text x="20" y="24" className="flow-column-title">ДО</text><text x="710" y="24" className="flow-column-title">ПОСЛЕ</text>
      {ribbons.map(({ path, color, index, flow }) => <path key={`${flow.source_unit_id}-${flow.target_unit_id}-${index}`} d={path} fill={flow.target_unit_id === 'lost' ? '#dd9b8e' : color} className={`flow-ribbon ${selected === index ? 'selected' : ''}`} onClick={() => setSelected(index)} tabIndex={0} role="button" aria-label={`${unitName(flow.source_unit_id)} → ${unitName(flow.target_unit_id)}: ${flow.value} функций`} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelected(index) } }}><title>{unitName(flow.source_unit_id)} → {unitName(flow.target_unit_id)}: {flow.value} функций</title></path>)}
      {sources.map((node, index) => <g key={node.id}><rect x="248" y={node.y + shift(sources)} width="12" height={node.height} rx="3" fill={colors[index % colors.length]} /><text x="238" y={node.y + shift(sources) + node.height / 2 - 3} textAnchor="end" className="flow-node-name">{node.name}</text><text x="238" y={node.y + shift(sources) + node.height / 2 + 13} textAnchor="end" className="flow-node-count">{node.value} функций</text></g>)}
      {targets.map((node) => <g key={node.id}><rect x="700" y={node.y + shift(targets)} width="12" height={node.height} rx="3" fill={node.id === 'lost' ? '#c47769' : '#4c91be'} /><text x="724" y={node.y + shift(targets) + node.height / 2 - 3} className="flow-node-name">{node.name}</text><text x="724" y={node.y + shift(targets) + node.height / 2 + 13} className="flow-node-count">{node.value} функций</text></g>)}
    </svg></div>
    {selected !== null && flows[selected] && <FlowDetails flow={flows[selected]} result={result} onOpenSource={onOpenSource} />}
  </>
}
