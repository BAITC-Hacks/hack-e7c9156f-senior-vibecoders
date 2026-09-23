export type Side = 'before' | 'after'

export interface AnalysisStatus {
  id: string
  status: 'queued' | 'running' | 'done' | 'failed'
  step?: string
  progress: number
  error?: string
}

export interface Evidence {
  doc_id: string
  doc_name: string
  side: Side
  clause_id: string
  quote: string
  verified: boolean
}

export interface Unit {
  id: string
  side: Side
  name: string
  abbr?: string
  parent?: string
  positions: string[]
  evidence: Evidence[]
}

export interface UnitChange {
  before_unit_ids: string[]
  after_unit_ids: string[]
  status: 'preserved' | 'renamed' | 'created' | 'abolished' | 'merged' | 'split' | 'transformed'
  rationale: string
  evidence: Evidence[]
}

export interface FunctionMapping {
  function: string
  before_unit_id?: string
  after_unit_ids: string[]
  status: 'preserved' | 'moved' | 'modified' | 'lost'
  confidence: number
  evidence: Evidence[]
}

export interface Finding {
  id: string
  type: 'function_loss' | 'duplication' | 'conflict_of_interest' | 'structure_change'
  severity: 'high' | 'medium' | 'low'
  title: string
  description: string
  recommendation?: string
  unit_ids: string[]
  evidence: Evidence[]
}

export interface AnalysisResult {
  units: Unit[]
  unit_changes: UnitChange[]
  function_mappings: FunctionMapping[]
  findings: Finding[]
  conclusion_md: string
  meta: {
    model: string
    provider: string
    duration_s: number
    documents: { doc_id: string; name: string; side: Side }[]
  }
}

export interface Clause {
  clause_id: string
  text: string
}
