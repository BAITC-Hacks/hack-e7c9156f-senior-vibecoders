export type Side = 'before' | 'after'

export interface AnalysisStatus {
  id: string
  created_at?: string
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
  id: string
  function: string
  category_id: string
  before_unit_id?: string
  after_unit_ids: string[]
  status: 'preserved' | 'moved' | 'modified' | 'lost'
  confidence: number
  evidence: Evidence[]
}

export interface CriticVerdict {
  verdict: 'upheld' | 'refuted' | 'uncertain'
  argument: string
  counter_evidence: Evidence[]
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
  rule_id?: string
  critic?: CriticVerdict
  review?: Review
}

export interface Review {
  status: 'accepted' | 'rejected'
  comment?: string
  reviewed_at: string
}

export type ReviewRequest = Pick<Review, 'status' | 'comment'>

export interface AnalysisSummary {
  id: string
  status: AnalysisStatus['status']
  created_at: string
  documents: { name: string; side: Side }[]
  counts?: { findings: number; rejected: number; high: number }
}

export interface Clause {
  clause_id: string
  section: string
  text: string
}

export type ClauseResponse = Pick<Clause, 'clause_id' | 'text'>

export interface DocumentText {
  doc_id: string
  name: string
  side: Side
  clauses: Clause[]
}

export interface ClauseAlignment {
  before_clause_id?: string
  after_clause_id?: string
  status: 'unchanged' | 'modified' | 'added' | 'removed' | 'moved'
  similarity: number
  diff?: { op: 'equal' | 'insert' | 'delete'; text: string }[]
}

export interface Flow {
  source_unit_id: string
  target_unit_id: string
  function_ids: string[]
  value: number
}

export interface AnalysisResult {
  units: Unit[]
  unit_changes: UnitChange[]
  function_mappings: FunctionMapping[]
  findings: Finding[]
  rejected_findings: Finding[]
  conclusion_md: string
  documents: DocumentText[]
  alignments: ClauseAlignment[]
  flows: Flow[]
  categories: { id: string; name: string }[]
  meta: {
    model: string
    provider: string
    duration_s: number
    documents: { doc_id: string; name: string; side: Side }[]
  }
}
