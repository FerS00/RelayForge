export type ChatAction = { id: string; turn_id: string; kind: string; payload: Record<string, string>; operation_hash: string; status: string; version: number; result: Record<string, unknown> | null }
export type PreviewItem = { id: string; status: string; kind: 'static' | 'command'; root: string; path: string; port: number | null; error_code: string | null; created_at: string; log_tail: string[] }
export type PreviewList = { items: PreviewItem[]; available: boolean; error_code: string | null }
export type DeliverableRoot = { id: string; name: string }
export type DeliverableEntry = { name: string; directory: boolean; size_bytes: number; modified_at: string }
export type DeliverableListing = { root: string; path: string; entries: DeliverableEntry[]; truncated: boolean }
export type Attachment = { id: string; name: string; media_type: string; size_bytes: number; sha256: string; state: string; message_id?: string | null }
export type ChatDefaults = { agent: 'claude' | 'codex'; model: string; runtime: string }
export type ToolKey = 'write_files' | 'commands' | 'git_local' | 'preview' | 'desktop' | 'web_search' | 'remote_delivery'
export type Conversation = { id: string; title: string; created_at?: string; updated_at: string; agent?: string; model?: string; runtime?: string; capabilities?: string[]; effort?: string; effective_effort?: string; tools?: Record<ToolKey, boolean>; settings_version?: number; supported_efforts?: string[] }
export type ChatTurn = { id: string; status: string; version: number; agent?: string; model?: string; effort?: string }
export type Message = {
  id: string
  step_id: string
  role: 'user' | 'orchestrator' | 'system'
  content: string
  status: 'complete' | 'error'
  ts: string
  attachments?: Attachment[]
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
  review_only?: boolean
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
  efforts?: Record<string, string[]>; default_efforts?: string[]
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
  chatDefaults: () => request<ChatDefaults>('/api/conversations/defaults'),
  createConversation: (selection?: { agent?: 'claude' | 'codex'; model?: string }) => request<Conversation>('/api/conversations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(selection ?? {}) }),
  decideAction: (conversation: string, action: ChatAction, decision: 'approve' | 'reject', key: string) => request<ChatAction>(`/api/conversations/${encodeURIComponent(conversation)}/actions/${encodeURIComponent(action.id)}/decision`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify({ version: action.version, operation_hash: action.operation_hash, decision }) }),
  updateConversationSettings: (conversation: string, body: { effort?: string; tools?: Partial<Record<ToolKey, boolean>>; settings_version: number }) => request<Conversation>(`/api/conversations/${encodeURIComponent(conversation)}/settings`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  previews: (conversation: string) => request<PreviewList>(`/api/conversations/${encodeURIComponent(conversation)}/previews`),
  previewTicket: (id: string) => request<{ url: string; expires_in: number }>(`/api/previews/${encodeURIComponent(id)}/ticket`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }),
  stopPreview: (id: string) => request<{ id: string; status: string }>(`/api/previews/${encodeURIComponent(id)}/stop`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }),
  fileRoots: (conversation: string) => request<{ roots: DeliverableRoot[] }>(`/api/conversations/${encodeURIComponent(conversation)}/files/roots`),
  files: (conversation: string, root: string, path: string) => {
    const params = new URLSearchParams({ root, path })
    return request<DeliverableListing>(`/api/conversations/${encodeURIComponent(conversation)}/files?${params}`)
  },
  fileContentUrl: (conversation: string, root: string, path: string) => {
    const params = new URLSearchParams({ root, path })
    return `/api/conversations/${encodeURIComponent(conversation)}/files/content?${params}`
  },
  fileZipUrl: (conversation: string, root: string, path: string) => {
    const params = new URLSearchParams({ root, path })
    return `/api/conversations/${encodeURIComponent(conversation)}/files/zip?${params}`
  },
  messages: (id: string) => request<{ conversation?: Conversation; messages: Message[]; actions?: ChatAction[]; jobs?: Job[]; turns?: ChatTurn[]; active_step: { step_id: string } | null }>(`/api/conversations/${encodeURIComponent(id)}/messages`),
  send: (id: string, content: string, attachment_ids: string[] = [], key: string = crypto.randomUUID()) => request<{ message: Message }>(`/api/conversations/${encodeURIComponent(id)}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
    body: JSON.stringify({ content, attachment_ids }),
  }),
  uploadAttachment: (id: string, name: string, data_base64: string) => request<Attachment>(`/api/conversations/${encodeURIComponent(id)}/attachments`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, data_base64 }),
  }),
  attachmentUrl: (id: string, attachment: string) => `/api/conversations/${encodeURIComponent(id)}/attachments/${encodeURIComponent(attachment)}/content`,
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
