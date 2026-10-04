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

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: { message?: string } } | null
    throw new Error(body?.error?.message ?? 'No se pudo completar la solicitud.')
  }
  return response.json() as Promise<T>
}

export const api = {
  conversations: () => request<Conversation[]>('/api/conversations'),
  createConversation: () => request<Conversation>('/api/conversations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }),
  messages: (id: string) => request<{ messages: Message[]; active_step: { step_id: string } | null }>(`/api/conversations/${encodeURIComponent(id)}/messages`),
  send: (id: string, content: string) => request<{ message: Message }>(`/api/conversations/${encodeURIComponent(id)}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
    body: JSON.stringify({ content }),
  }),
}
