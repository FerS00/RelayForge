import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeSanitize from 'rehype-sanitize'
import { api, type ChatTurn, type Message } from '../api'
import styles from '../styles.module.css'

type Props = { messages: Message[]; active: boolean; onSend: (text: string, files: File[]) => Promise<void> | void; error?: string; onMenu: () => void; onDeliverables?: () => void; deliverablesEnabled?: boolean; conversationId?: string; agent?: string; model?: string; runtime?: string; options?: ReactNode; actions?: ReactNode; turns?: ChatTurn[] }

export function ChatView({ messages, active, onSend, error, onMenu, onDeliverables, deliverablesEnabled, conversationId, agent = 'Agente', model, runtime, options, actions, turns }: Props) {
  const efforts = new Map((turns ?? []).map((turn) => [turn.id, turn]))
  const [value, setValue] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [localError, setLocalError] = useState('')
  const [sending, setSending] = useState(false)
  const previous = useRef(conversationId)
  const bottom = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (previous.current !== undefined && previous.current !== conversationId) {
      setValue(''); setFiles([]); setLocalError('')
    }
    previous.current = conversationId
  }, [conversationId])
  useEffect(() => { bottom.current?.scrollIntoView?.({ block: 'end' }) }, [messages, active])
  const busy = sending
  const send = async (event?: FormEvent) => {
    event?.preventDefault()
    if ((!value.trim() && files.length === 0) || busy) return
    setSending(true); setLocalError('')
    try { await onSend(value, files); setValue(''); setFiles([]) }
    catch (failure) { setLocalError(failure instanceof Error ? failure.message : 'No se pudo enviar. Conservamos tu borrador.') }
    finally { setSending(false) }
  }
  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault(); void send()
    }
  }
  return <main className={styles.chat}>
    <header className={styles.chatHeader}><button className={styles.menuButton} onClick={onMenu} aria-label="Abrir conversaciones">☰</button><div className={styles.chatIdentity}><strong>{agent}</strong>{model && <small className={styles.modelName}>{model}</small>}</div>{deliverablesEnabled && <button className={styles.deliverablesHeaderButton} onClick={onDeliverables} aria-label="Abrir Entregables">Entregables</button>}<span className={styles.runtime}>{runtime === 'windows-container' ? 'Docker' : runtime === 'windows-native' ? 'Laptop Windows' : ''}</span></header>
    {options}
    <section className={styles.messages} aria-live="polite">
      {messages.length === 0 && <div className={styles.empty}><h1>¿En qué puedo ayudarte?</h1><p>Escribe tu solicitud o adjunta evidencia.</p></div>}
      {messages.filter(message => message.role !== 'system' || message.status === 'error').map((message) => <article key={message.id} className={`${styles.message} ${message.role === 'user' ? styles.userMessage : styles.agentMessage}`}>
        <div className={styles.messageRole}>{message.role === 'user' ? 'Tú' : message.role === 'system' ? 'Sistema' : agent}{message.role === 'orchestrator' && efforts.get(message.step_id)?.effort && <small className={styles.turnEffort}>{[efforts.get(message.step_id)?.model, `esfuerzo ${efforts.get(message.step_id)?.effort}`].filter(Boolean).join(' · ')}</small>}</div>
        <div className={styles.messageText}><ReactMarkdown rehypePlugins={[rehypeSanitize]} skipHtml>{message.content}</ReactMarkdown></div>
        {conversationId && message.attachments?.map((attachment) => <div className={styles.attachment} key={attachment.id}>
          {attachment.media_type.startsWith('image/') && <img className={styles.evidenceImage} src={api.attachmentUrl(conversationId, attachment.id)} alt={attachment.name} loading="lazy" />}
          <a href={api.attachmentUrl(conversationId, attachment.id)} download>{attachment.name}</a><small>{Math.ceil(attachment.size_bytes / 1024)} KB{attachment.state === 'no_text_extracted' ? ' · sin texto extraído; no OCR' : ''}</small>
        </div>)}
      </article>)}
      {actions}
      {active && <div className={styles.activity}>{agent} está respondiendo…</div>}
      {(localError || error) && <div role="alert" className={styles.error}>{localError || error}</div>}
      <div ref={bottom} />
    </section>
    <form className={styles.composer} onSubmit={(event) => { void send(event) }}>
      <textarea aria-label="Mensaje" placeholder="Escribe un mensaje…" value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={keyDown} rows={2} disabled={sending} />
      <button type="submit" disabled={busy || (!value.trim() && files.length === 0)}>Enviar</button>
      <label className={styles.attachButton}>Adjuntar<input aria-label="Adjuntar evidencia" type="file" multiple accept=".txt,.md,.log,.json,.csv,.png,.jpg,.jpeg,.webp,.pdf,.docx" disabled={busy} onChange={(event) => {
        const selected = [...files, ...Array.from(event.target.files ?? [])]
        event.target.value = ''
        if (selected.length > 8 || selected.some((file) => file.size > 8 * 1024 * 1024) || selected.reduce((sum, file) => sum + file.size, 0) > 32 * 1024 * 1024) { setLocalError('Máximo 8 adjuntos, 8 MB por archivo y 32 MB por mensaje.'); return }
        setFiles(selected); setLocalError('')
      }} /></label>
      <div className={styles.pendingFiles}>{files.map((file, index) => <div key={`${file.name}-${index}`}><span>{file.name}</span><button type="button" aria-label={`Quitar ${file.name}`} disabled={busy} onClick={() => setFiles(files.filter((_, at) => at !== index))}>×</button></div>)}</div>
      <span>Texto, imágenes, PDF y DOCX · 8 MB por archivo · Enter para enviar</span>
    </form>
  </main>
}
