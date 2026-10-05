import { useCallback, useEffect, useState } from 'react'
import { HashRouter, Link, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type ConversationEvent } from './api'
import { ConversationList } from './components/ConversationList'
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
    <Route path="/" element={<Projects />} />
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

function Workspace() {
  const { id } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [mobileMenu, setMobileMenu] = useState(false)
  const [streamMessages, setStreamMessages] = useState<Record<string, string>>({})
  const [active, setActive] = useState(false)
  const conversations = useQuery({ queryKey: ['conversations'], queryFn: api.conversations })
  const send = useMutation({ mutationFn: (content: string) => api.send(id!, content), onSuccess: () => queryClient.invalidateQueries({ queryKey: ['messages', id] }) })
  const receive = useCallback((event: ConversationEvent) => {
    if (event.type === 'step.started') setActive(true)
    if (event.type === 'step.finished') {
      setActive(false)
      setStreamMessages({})
      void queryClient.invalidateQueries({ queryKey: ['messages', id] })
      void queryClient.invalidateQueries({ queryKey: ['conversations'] })
    }
    if (event.type === 'agent.message.delta') {
      const messageId = String(event.data.message_id)
      setStreamMessages((previous) => ({ ...previous, [messageId]: (previous[messageId] ?? '') + String(event.data.text) }))
    }
    if (event.type === 'agent.message') {
      const messageId = String(event.data.message_id)
      setStreamMessages((previous) => ({ ...previous, [messageId]: String(event.data.text) }))
      void queryClient.invalidateQueries({ queryKey: ['messages', id] })
    }
  }, [id, queryClient])
  const streamReady = useEventStream(id, receive, () => { void queryClient.invalidateQueries({ queryKey: ['messages', id] }) })
  const messages = useQuery({ queryKey: ['messages', id], queryFn: () => api.messages(id!), enabled: Boolean(id) && streamReady })
  useEffect(() => {
    if (messages.data?.active_step) setActive(true)
  }, [messages.data?.active_step])
  const create = useMutation({ mutationFn: api.createConversation, onSuccess: (conversation) => {
    void queryClient.invalidateQueries({ queryKey: ['conversations'] })
    navigate(`/c/${conversation.id}`)
  } })
  const combined = (messages.data?.messages ?? []).map((message) => ({ ...message, content: streamMessages[message.id] ?? message.content }))
  const knownIds = new Set(combined.map((message) => message.id))
  const ephemeral = Object.entries(streamMessages).filter(([messageId]) => !knownIds.has(messageId)).map(([id, content]) => ({ id, step_id: '', role: 'orchestrator' as const, content, status: 'complete' as const, ts: '' }))
  return <div className={styles.shell}>
    {mobileMenu && <button className={styles.backdrop} aria-label="Cerrar conversaciones" onClick={() => setMobileMenu(false)} />}
    <div className={`${styles.sidebarWrap} ${mobileMenu ? styles.sidebarOpen : ''}`}><ConversationList conversations={conversations.data ?? []} activeId={id} onSelect={(conversationId) => navigate(`/c/${conversationId}`)} onCreate={() => create.mutate()} onClose={() => setMobileMenu(false)} createError={id ? create.error?.message : undefined} /></div>
    {id ? <ChatView messages={[...combined, ...ephemeral]} active={active || Boolean(messages.data?.active_step)} onSend={(content) => send.mutate(content)} error={send.error?.message} onMenu={() => setMobileMenu(true)} /> : <main className={styles.welcome}><button className={styles.menuButton} onClick={() => setMobileMenu(true)} aria-label="Abrir conversaciones">☰</button><h1>RelayForge</h1><p>Inicia una conversación con Claude Code.</p><button className={styles.primary} onClick={() => create.mutate()}>Nueva conversación</button>{create.error && <p role="alert" className={styles.error}>{create.error.message}</p>}<Link className={styles.screenReader} to="/">Inicio</Link></main>}
  </div>
}

export function App() {
  return <HashRouter><SessionGate /></HashRouter>
}
