import { mockClause, mockResult } from './mocks'
import { createLocalPreview } from './localPreview'
import type { AnalysisResult, AnalysisStatus, ClauseResponse } from './types'

const baseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000'
export const useMocks = import.meta.env.VITE_USE_MOCKS !== 'false'
const mockStarts = new Map<string, number>()
const mockResults = new Map<string, AnalysisResult>()

async function requestResponse(path: string, init?: RequestInit): Promise<Response> {
  let response: Response
  try {
    response = await fetch(`${baseUrl}${path}`, init)
  } catch {
    throw new Error('Не удалось связаться с сервером. Проверьте, что backend запущен.')
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const message = typeof body === 'object' && body !== null && 'error' in body && typeof body.error === 'string'
      ? body.error : `Ошибка сервера (${response.status})`
    throw new Error(message)
  }
  return response
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return (await requestResponse(path, init)).json() as Promise<T>
}

async function mockDelay(ms = 450) {
  await new Promise((resolve) => window.setTimeout(resolve, ms))
}

function startMock(result: AnalysisResult) {
  const id = `demo-${Date.now()}`
  mockStarts.set(id, Date.now())
  mockResults.set(id, result)
  return { id }
}

export const api = {
  async createAnalysis(before: File[], after: File[]): Promise<{ id: string }> {
    if (useMocks) {
      if (!before[0] || !after[0]) throw new Error('Добавьте документ «до» и документ «после».')
      return startMock(await createLocalPreview(before[0], after[0]))
    }
    const body = new FormData()
    before.forEach((file) => body.append('before', file))
    after.forEach((file) => body.append('after', file))
    return request('/api/analyses', { method: 'POST', body })
  },
  async createDemo(): Promise<{ id: string }> {
    if (useMocks) { await mockDelay(); return startMock(mockResult) }
    return request('/api/analyses/demo', { method: 'POST' })
  },
  async getStatus(id: string): Promise<AnalysisStatus> {
    if (useMocks) {
      await mockDelay(200)
      const elapsed = Date.now() - (mockStarts.get(id) ?? Date.now())
      const preview = mockResults.get(id)?.meta.model === 'local-preview'
      const progress = Math.min(1, elapsed / (preview ? 700 : 4500))
      return { id, status: progress === 1 ? 'done' : 'running', progress, step: preview ? 'alignment' : progress < .3 ? 'parsing' : progress < .7 ? 'units' : 'evidence' }
    }
    return request(`/api/analyses/${encodeURIComponent(id)}`)
  },
  async getResult(id: string): Promise<AnalysisResult> {
    if (useMocks) { await mockDelay(); return mockResults.get(id) ?? mockResult }
    return request(`/api/analyses/${encodeURIComponent(id)}/result`)
  },
  async getClause(id: string, docId: string, clauseId: string): Promise<ClauseResponse> {
    if (useMocks) { await mockDelay(300); return mockClause(mockResults.get(id) ?? mockResult, docId, clauseId) }
    return request(`/api/analyses/${encodeURIComponent(id)}/documents/${encodeURIComponent(docId)}/clauses/${encodeURIComponent(clauseId)}`)
  },
  async downloadReport(id: string): Promise<Blob> {
    return (await requestResponse(`/api/analyses/${encodeURIComponent(id)}/report.docx`)).blob()
  },
}
