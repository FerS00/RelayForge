import { useCallback, useEffect, useRef, useState } from 'react'
import { HashRouter, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type ConversationEvent, type ChatDefaults } from './api'
import { ConversationList } from './components/ConversationList'
import { ConversationActions } from './components/ConversationActions'
import { ConversationSettings } from './components/ConversationSettings'
import { Deliverables } from './components/Deliverables'
import { ChatView } from './components/ChatView'
import { useEventStream } from './lib/eventStream'
import styles from './styles.module.css'
import { Dashboard } from './pages/Dashboard'
import { NewTask } from './pages/NewTask'
import { JobDetail } from './pages/JobDetail'
import { Repositories } from './pages/Repositories'
import { Pairing } from './pages/Pairing'
import { Agents } from './pages/Agents'
import { Approvals } from './pages/Approvals'
import { Metrics } from './pages/Metrics'
import { Projects } from './pages/Projects'

function SessionGate() {
  const auth = useQuery({ queryKey: ['auth'], queryFn: api.authStatus, retry: false })
  if (auth.isPending) return <main className={styles.welcome}>Comprobando sesión…</main>
  if (auth.isError || !auth.data?.authenticated) return <Pairing />
  return <Routes>
    <Route path="/" element={<Workspace />} />
    <Route path="/projects" element={<Projects />} />
    <Route path="/projects/:id" element={<Projects />} />
    <Route path="/chat" element={<Workspace />} />
    <Route path="/c/:id" element={<Workspace />} />
    <Route path="/jobs" element={<Dashboard />} />
    <Route path="/repos" element={<Repositories />} />
    <Route path="/jobs/new" element={<NewTask />} />
    <Route path="/jobs/:id" element={<JobDetail />} />
    <Route path="/agents" element={<Agents />} />
    <Route path="/approvals" element={<Approvals />} />
    <Route path="/metrics" element={<Metrics />} />
  </Routes>
}

function encodeFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error(`No se pudo leer ${file.name}.`))
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1])
    reader.readAsDataURL(file)
  })
}

function Workspace() {
  const { id } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [mobileMenu, setMobileMenu] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [deliverablesOpen, setDeliverablesOpen] = useState(false)
  const [selection, setSelection] = useState<{ agent?: 'claude' | 'codex'; model?: string }>({})
  const [streamMessages, setStreamMessages] = useState<Record<string, Record<string, string>>>({})
  const [activeId, setActiveId] = useState<string>()
  const pendingSend = useRef<{ fingerprint: string; key: string } | null>(null)
  const uploaded = useRef(new Map<File, { conversation: string; id: string }>())
  const conversations = useQuery({ queryKey: ['conversations'], queryFn: api.conversations })
  const defaults = useQuery({ queryKey: ['chat-defaults'], queryFn: api.chatDefaults, enabled: !id })
  const status = useQuery({ queryKey: ['agent-status'], queryFn: api.agentStatus, enabled: settingsOpen, staleTime: 30000 })
  const send = useMutation({ mutationFn: async ({ content, files }: { content: string; files: File[] }) => {
    let target = id
    if (!target) {
      const conversation = await api.createConversation(selection)
      target = conversation.id
      await queryClient.invalidateQueries({ queryKey: ['conversations'] })
      navigate(`/c/${target}`)
    }
    const attachments = []
    for (const file of files) {
      const existing = uploaded.current.get(file)
      if (existing?.conversation === target) { attachments.push(existing.id); continue }
      const attachment = await api.uploadAttachment(target, file.name, await encodeFile(file))
      uploaded.current.set(file, { conversation: target, id: attachment.id })
      attachments.push(attachment.id)
    }
    const fingerprint = JSON.stringify({ target, content, attachments })
    if (pendingSend.current?.fingerprint !== fingerprint) pendingSend.current = { fingerprint, key: crypto.randomUUID() }
    setActiveId(target)
    try { await api.send(target, content, attachments, pendingSend.current.key) }
    catch (error) { setActiveId(undefined); throw error }
    pendingSend.current = null
    uploaded.current.clear()
    await queryClient.invalidateQueries({ queryKey: ['messages', target] })
  } })
  const receive = useCallback((event: ConversationEvent) => {
    if (event.conversation !== id) return
    if (event.type === 'conversation.settings') { void queryClient.invalidateQueries({ queryKey: ['messages', id] }); void queryClient.invalidateQueries({ queryKey: ['conversations'] }) }
    if (event.type.startsWith('action.') || event.type.startsWith('job.') || event.type.startsWith('approval.') || event.type.startsWith('checks.') || event.type.startsWith('audit.')) void queryClient.invalidateQueries({ queryKey: ['messages', id] })
    if (event.type === 'step.started' || event.type === 'step.queued') setActiveId(id)
    if (event.type === 'step.finished') {
      setActiveId(undefined); setStreamMessages({})
      void queryClient.invalidateQueries({ queryKey: ['messages', id] })
      void queryClient.invalidateQueries({ queryKey: ['conversations'] })
    }
    if (event.type === 'agent.message.delta') {
      const messageId = String(event.data.message_id)
      setStreamMessages((previous) => ({ ...previous, [id!]: { ...previous[id!] ?? {}, [messageId]: (previous[id!]?.[messageId] ?? '') + String(event.data.text) } }))
    }
    if (event.type === 'agent.message') {
      const messageId = String(event.data.message_id)
      setStreamMessages((previous) => ({ ...previous, [id!]: { ...previous[id!] ?? {}, [messageId]: String(event.data.text) } }))
      void queryClient.invalidateQueries({ queryKey: ['messages', id] })
    }
  }, [id, queryClient])
  useEventStream(id, receive, () => { void queryClient.invalidateQueries({ queryKey: ['messages', id] }) })
  const messages = useQuery({ queryKey: ['messages', id], queryFn: () => api.messages(id!), enabled: Boolean(id), refetchInterval: (query) => query.state.data?.active_step || query.state.data?.jobs?.some(job => !['COMPLETED', 'FAILED', 'CANCELLED'].includes(job.status)) || query.state.data?.actions?.some(action => ['approved', 'running'].includes(action.status)) ? 1000 : false })
  const resetSend = send.reset
  useEffect(() => { setStreamMessages({}); setActiveId(undefined); setDeliverablesOpen(false); resetSend() }, [id, resetSend])
  useEffect(() => { if (messages.data && !messages.data.active_step && !send.isPending) setActiveId(undefined) }, [messages.data, send.isPending])
  const create = useMutation({ mutationFn: () => api.createConversation(selection), onSuccess: (conversation) => {
    setMobileMenu(false)
    void queryClient.invalidateQueries({ queryKey: ['conversations'] })
    navigate(`/c/${conversation.id}`)
  } })
  const liveMessages = streamMessages[id ?? ''] ?? {}
  const combined = (messages.data?.messages ?? []).map((message) => ({ ...message, content: liveMessages[message.id] ?? message.content }))
  const knownIds = new Set(combined.map((message) => message.id))
  const ephemeral = Object.entries(liveMessages).filter(([messageId]) => !knownIds.has(messageId)).map(([id, content]) => ({ id, step_id: '', role: 'orchestrator' as const, content, status: 'complete' as const, ts: '' }))
  const conversation = messages.data?.conversation ?? conversations.data?.find((item) => item.id === id)
  const effective = conversation ?? defaults.data
  const selectedAgent = selection.agent ?? defaults.data?.agent ?? 'codex'
  const models = status.data?.find((item) => item.agent === selectedAgent)?.models ?? []
  const options = !id ? <details className={styles.chatOptions} onToggle={(event) => setSettingsOpen(event.currentTarget.open)}><summary>Agente y modelo · opcional</summary>
    <label>Agente<select aria-label="Agente de conversación" value={selection.agent ?? ''} onChange={(event) => setSelection(event.target.value ? { agent: event.target.value as ChatDefaults['agent'], model: '' } : {})}><option value="">Predeterminado</option><option value="codex">Codex</option><option value="claude">Claude</option></select></label>
    <label>Modelo<select aria-label="Modelo de conversación" value={selection.model ?? ''} onChange={(event) => setSelection((current) => ({ ...current, model: event.target.value }))}><option value="">Predeterminado</option>{[...new Set(models)].map((model) => <option key={model} value={model}>{model}</option>)}</select></label>
  </details> : conversation?.settings_version !== undefined ? <ConversationSettings conversation={conversation} /> : undefined
  return <div className={styles.shell}>
    {mobileMenu && <button className={styles.backdrop} aria-label="Cerrar conversaciones" onClick={() => setMobileMenu(false)} />}
    <div className={`${styles.sidebarWrap} ${mobileMenu ? styles.sidebarOpen : ''}`}><ConversationList conversations={conversations.data ?? []} activeId={id} onSelect={(conversationId) => navigate(`/c/${conversationId}`)} onCreate={() => create.mutate()} onClose={() => setMobileMenu(false)} createError={create.error?.message} /></div>
    <ChatView actions={id ? <ConversationActions conversation={id} actions={messages.data?.actions ?? []} jobs={messages.data?.jobs ?? []} /> : undefined} messages={[...combined, ...ephemeral]} conversationId={id} agent={effective?.agent ?? 'Agente configurado'} model={effective?.model} runtime={effective?.runtime} options={options} active={Boolean(id && activeId === id) || Boolean(messages.data?.active_step) || send.isPending} onSend={(content, files) => send.mutateAsync({ content, files })} error={send.error?.message} onMenu={() => setMobileMenu(true)} turns={messages.data?.turns} deliverablesEnabled={Boolean(id && conversation?.capabilities?.includes('deliverables'))} onDeliverables={() => setDeliverablesOpen(true)} />
    {deliverablesOpen && id && <Deliverables conversationId={id} onClose={() => setDeliverablesOpen(false)} />}
  </div>
}

export function App() {
  return <HashRouter><SessionGate /></HashRouter>
}
