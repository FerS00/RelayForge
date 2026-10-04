import { useCallback, useEffect, useState } from 'react'
import { HashRouter, Link, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type ConversationEvent } from './api'
import { ConversationList } from './components/ConversationList'
import { ChatView } from './components/ChatView'
import { useEventStream } from './lib/eventStream'
import styles from './styles.module.css'

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
    <div className={`${styles.sidebarWrap} ${mobileMenu ? styles.sidebarOpen : ''}`}><ConversationList conversations={conversations.data ?? []} activeId={id} onSelect={(conversationId) => navigate(`/c/${conversationId}`)} onCreate={() => create.mutate()} onClose={() => setMobileMenu(false)} /></div>
    {id ? <ChatView messages={[...combined, ...ephemeral]} active={active || Boolean(messages.data?.active_step)} onSend={(content) => send.mutate(content)} error={send.error?.message} onMenu={() => setMobileMenu(true)} /> : <main className={styles.welcome}><button className={styles.menuButton} onClick={() => setMobileMenu(true)} aria-label="Abrir conversaciones">☰</button><h1>RelayForge</h1><p>Inicia una conversación con Claude Code.</p><button className={styles.primary} onClick={() => create.mutate()}>Nueva conversación</button><Link className={styles.screenReader} to="/">Inicio</Link></main>}
  </div>
}

export function App() {
  return <HashRouter><Routes><Route path="/" element={<Workspace />} /><Route path="/c/:id" element={<Workspace />} /></Routes></HashRouter>
}
