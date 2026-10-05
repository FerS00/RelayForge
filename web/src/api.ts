export type Conversation = { id: string; title: string; created_at?: string; updated_at: string }
export type Message = {
  id: string
  step_id: string
  role: 'user' | 'orchestrator' | 'system'
  content: string
  status: 'complete' | 'error'
  ts: string
}
export type ConversationEvent = {
  conversation: string
  seq: number
  ts: string
  type: string
  actor: string
  step: string | null
  data: Record<string, unknown>
}
export type JobEvent = {
  job: string
  seq: number
  ts: string
  type: string
  actor: string
  step: string | null
  data: Record<string, unknown>
}
export type JobPlan = {
  objective: string
  summary: string
  steps: string[]
  risks: string[]
}
export type JobStep = {
  id: string
  kind: string
  agent: string
  status: string
  iteration: number
  attempt: number
  started_at: string | null
  finished_at: string | null
  summary: JobPlan | null
  error_code: string | null
  pid: number | null
  heartbeat_at: string | null
  resumable: boolean
  resume_token: string | null
}
export type Job = {
  id: string
  number: number
  display_id: string
  title: string
  request_text: string
  workflow: string
  planning_agent?: Agent
  planning_model?: string | null
  implementation_model?: string | null
  audit_model?: string | null
  paused_stage?: string | null
  approval_kind?: string | null
  require_plan_approval?: boolean
  worktree_path?: string | null
  status: string
  conversation_id: string
  repository_id: string | null
  base_sha: string | null
  branch: string | null
  codex_thread_id: string | null
  diff?: string | null
  diff_paths?: string[]
  created_at: string
  updated_at: string
  finished_at: string | null
  version: number
  error_code: string | null
  error_message: string | null
  retry_at: string | null
  retry_count: number
  plan: JobPlan | null
  steps?: JobStep[]
  events?: { seq: number; ts: string; type: string; actor: string; data: Record<string, unknown> }[]
  findings?: { id: string; audit_no: number; severity: string; file: string; line: number | null;
    title: string; evidence: string; recommendation: string; triage_decision: string | null;
    triage_reason: string | null; fixed_in_iteration: number | null }[]
}
export type Repository = {
  id: string
  name: string
  path: string
  default_branch: string
  created_at: string
  enabled: boolean
  dirty: boolean
  health?: string
  check_commands: CheckCommand[]
}
export type CheckCommand = { name: string; argv: string[]; timeout_seconds?: number }
export type Agent = 'claude' | 'codex' | 'antigravity'
export type AgentStatus = {
  agent: Agent; status: string; auth: string; version: string; models: string[]
  health: { status: string; detail: string | null; rate_limited_until: string | null } | null
  usage: { turns: number; steps: number; input_tokens: number | null; output_tokens: number | null;
    five_hour: { status: string; remaining: number | null }; weekly: { status: string; remaining: number | null } }
}
export type Approval = {
  id: string; job_id: string; operation: Record<string, unknown>; operation_hash: string
  diff_hash: string; status: string; decision: string | null; reason: string | null
  overlaps: { job_id: string; paths: string[] }[]
}
export type MetricsSummary = {
  from: string | null; to: string | null; total_jobs: number; jobs_by_status: Record<string, number>
  jobs_by_workflow: Record<string, number>; average_job_duration_seconds: number | null
  retry_count: number; step_count: number; failed_steps: number
  steps_by_agent: Record<string, { steps: number; failed: number; duration_seconds: number }>
  checks: { passed: number; failed: number; skipped: number }; findings_by_severity: Record<string, number>
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (init?.method && init.method !== 'GET' && init.method !== 'HEAD') {
    headers.set('X-CSRF-Token', await freshCsrfToken())
  }
  const response = await fetch(url, { ...init, headers, credentials: 'same-origin' })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: { message?: string } } | null
    throw new Error(body?.error?.message ?? 'No se pudo completar la solicitud.')
  }
  return response.json() as Promise<T>
}

let csrfRefresh: Promise<string> | undefined

function freshCsrfToken(): Promise<string> {
  if (!csrfRefresh) {
    csrfRefresh = fetch('/api/auth/csrf', { credentials: 'same-origin' })
      .then(async (response) => {
        if (!response.ok) throw new Error('No se pudo renovar el token CSRF.')
        const body = (await response.json()) as { csrf_token?: unknown }
        if (typeof body.csrf_token !== 'string' || !body.csrf_token) {
          throw new Error('La respuesta CSRF no contiene un token válido.')
        }
        return body.csrf_token
      })
      .finally(() => { csrfRefresh = undefined })
  }
  return csrfRefresh
}

export const api = {
  authStatus: () => request<{ authenticated: boolean }>('/api/auth/status'),
  csrf: () => request<{ csrf_token: string }>('/api/auth/csrf'),
  pair: (code: string, csrf: string) => request<{ authenticated: boolean }>('/api/auth/pair', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: JSON.stringify({ code }),
  }),
  doctor: () => request<Record<string, unknown>>('/api/doctor'),
  agents: () => request<{ agent: string; status: string; checked_at: string; detail: string | null; rate_limited_until: string | null }[]>('/api/agents'),
  agentStatus: () => request<AgentStatus[]>('/api/agents/status'),
  metrics: (from?: string, to?: string) => {
    const params = new URLSearchParams()
    if (from) params.set('from', from)
    if (to) params.set('to', to)
    return request<MetricsSummary>(`/api/metrics/summary${params.size ? `?${params}` : ''}`)
  },
  conversations: () => request<Conversation[]>('/api/conversations'),
  createConversation: () => request<Conversation>('/api/conversations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }),
  messages: (id: string) => request<{ messages: Message[]; active_step: { step_id: string } | null }>(`/api/conversations/${encodeURIComponent(id)}/messages`),
  send: (id: string, content: string) => request<{ message: Message }>(`/api/conversations/${encodeURIComponent(id)}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
    body: JSON.stringify({ content }),
  }),
  jobs: (repository_id?: string) => request<Job[]>(`/api/jobs${repository_id ? `?repository_id=${encodeURIComponent(repository_id)}` : ''}`),
  job: (id: string) => request<Job>(`/api/jobs/${encodeURIComponent(id)}`),
  createJob: (title: string, request_text: string, repository_id?: string, workflow = 'auto', selection?: { agent: Agent; model?: string; implementation_model?: string; audit_model?: string; require_plan_approval?: boolean }) => request<{ job: Job }>('/api/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
    body: JSON.stringify({ title: title || null, request_text, workflow, repository_id: repository_id || null, ...selection }),
  }),
  repositories: () => request<Repository[]>('/api/repos'),
  approvals: () => request<Approval[]>('/api/approvals?status=pending'),
  decideApproval: (id: string, decision: 'approve' | 'reject', scope: 'once' | 'job') => request<Approval>(`/api/approvals/${encodeURIComponent(id)}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
    body: JSON.stringify({ decision, scope }),
  }),
  addRepository: (body: { mode: 'register' | 'create'; name: string; path?: string; check_commands: CheckCommand[] }) => request<{ repository: Repository }>('/api/repos', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }),
  cancelJob: (id: string) => request<Job>(`/api/jobs/${encodeURIComponent(id)}/cancel`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  }),
  resumeJob: (id: string, mode: 'resume_session' | 'retry_step') => request<Job>(`/api/jobs/${encodeURIComponent(id)}/resume`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode }),
  }),
  dispatchStep: (id: string, agent: Agent, model: string | undefined, version: number) => request<Job>(`/api/jobs/${encodeURIComponent(id)}/step`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ agent, model: model || null, version }),
  }),
}
