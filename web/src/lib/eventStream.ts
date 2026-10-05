import { useEffect, useRef, useState } from 'react'
import type { ConversationEvent, JobEvent } from '../api'

export function useEventStream(conversationId: string | undefined, onEvent: (event: ConversationEvent) => void, onReconnect: () => void) {
  const latest = useRef(0)
  const [connection, setConnection] = useState<{ id: string; open: boolean } | null>(null)
  const onEventRef = useRef(onEvent)
  const onReconnectRef = useRef(onReconnect)
  onEventRef.current = onEvent
  onReconnectRef.current = onReconnect

  useEffect(() => {
    if (!conversationId) return
    setConnection(null)
    latest.current = 0
    let connected = false
    const stream = new EventSource(`/api/stream?conversation=${encodeURIComponent(conversationId)}`)
    stream.onopen = () => { connected = true; setConnection({ id: conversationId, open: true }) }
    stream.addEventListener('conversation.event', (message) => {
      const event = JSON.parse((message as MessageEvent<string>).data) as ConversationEvent
      if (event.seq <= latest.current) return
      latest.current = event.seq
      onEventRef.current(event)
    })
    stream.onerror = () => {
      if (connected) onReconnectRef.current()
    }
    return () => { stream.close(); setConnection(null) }
  }, [conversationId])
  return Boolean(conversationId && connection?.id === conversationId && connection.open)
}

export function useJobEventStream(jobId: string | undefined, onEvent: (event: JobEvent) => void, onReconnect: () => void) {
  const latest = useRef(0)
  const onEventRef = useRef(onEvent)
  const onReconnectRef = useRef(onReconnect)
  onEventRef.current = onEvent
  onReconnectRef.current = onReconnect

  useEffect(() => {
    if (!jobId) return
    latest.current = 0
    let connected = false
    const stream = new EventSource(`/api/jobs/${encodeURIComponent(jobId)}/events`)
    stream.onopen = () => { connected = true }
    stream.addEventListener('job.event', (message) => {
      const event = JSON.parse((message as MessageEvent<string>).data) as JobEvent
      if (event.seq <= latest.current) return
      latest.current = event.seq
      onEventRef.current(event)
    })
    stream.onerror = () => {
      if (connected) onReconnectRef.current()
    }
    return () => stream.close()
  }, [jobId])
}
