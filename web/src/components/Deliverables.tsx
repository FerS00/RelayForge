import { useCallback, useEffect, useState } from 'react'
import { api, type DeliverableRoot, type PreviewItem, type PreviewList } from '../api'
import styles from '../styles.module.css'

const statusLabels: Record<string, string> = {
  starting: 'Iniciando',
  running: 'En ejecución',
  stopped: 'Detenido',
  failed: 'Fallido',
  interrupted: 'Interrumpido',
}

function joinPath(parent: string, child: string) {
  return parent ? `${parent}/${child}` : child
}

export function Deliverables({ conversationId, onClose }: { conversationId: string; onClose: () => void }) {
  const [previewList, setPreviewList] = useState<PreviewList>({ items: [], available: false, error_code: null })
  const [rootOptions, setRootOptions] = useState<DeliverableRoot[]>([])
  const [root, setRoot] = useState('workspace')
  const [path, setPath] = useState('')
  const [listing, setListing] = useState<{ name: string; directory: boolean; size_bytes: number; modified_at: string }[]>([])
  const [truncated, setTruncated] = useState(false)
  const [inlinePreview, setInlinePreview] = useState<{ id: string; url: string } | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  const refreshPreviews = useCallback(async () => {
    try {
      setPreviewList(await api.previews(conversationId))
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'No se pudieron cargar los previews.')
    }
  }, [conversationId])

  useEffect(() => {
    let live = true
    void Promise.all([api.fileRoots(conversationId), api.previews(conversationId)])
      .then(([rootResponse, previews]) => {
        if (!live) return
        setRootOptions(rootResponse.roots)
        setRoot((current) => rootResponse.roots.some((item) => item.id === current) ? current : rootResponse.roots[0]?.id ?? 'workspace')
        setPreviewList(previews)
      })
      .catch((failure: unknown) => {
        if (live) setError(failure instanceof Error ? failure.message : 'No se pudieron cargar los entregables.')
      })
    return () => { live = false }
  }, [conversationId])

  useEffect(() => {
    let live = true
    void api.files(conversationId, root, path)
      .then((result) => {
        if (!live) return
        setListing(result.entries)
        setTruncated(result.truncated)
      })
      .catch((failure: unknown) => {
        if (live) {
          setListing([])
          setError(failure instanceof Error ? failure.message : 'No se pudo explorar esta carpeta.')
        }
      })
    return () => { live = false }
  }, [conversationId, root, path])

  useEffect(() => {
    const timer = window.setInterval(() => { void refreshPreviews() }, 2000)
    return () => window.clearInterval(timer)
  }, [refreshPreviews])

  const openPreview = async (preview: PreviewItem) => {
    const popup = window.open('about:blank', '_blank')
    if (popup) popup.opener = null
    setBusy(preview.id)
    setError('')
    try {
      const ticket = await api.previewTicket(preview.id)
      if (popup) popup.location.replace(ticket.url)
      else window.location.assign(ticket.url)
    } catch (failure) {
      popup?.close()
      setError(failure instanceof Error ? failure.message : 'No se pudo abrir el preview.')
    } finally {
      setBusy('')
    }
  }

  const showInline = async (preview: PreviewItem) => {
    setBusy(preview.id)
    setError('')
    try {
      const ticket = await api.previewTicket(preview.id)
      setInlinePreview({ id: preview.id, url: ticket.url })
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'No se pudo abrir el preview.')
    } finally {
      setBusy('')
    }
  }

  const stopPreview = async (preview: PreviewItem) => {
    setBusy(preview.id)
    setError('')
    try {
      await api.stopPreview(preview.id)
      setInlinePreview((current) => current?.id === preview.id ? null : current)
      await refreshPreviews()
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'No se pudo detener el preview.')
    } finally {
      setBusy('')
    }
  }

  const rootName = rootOptions.find((item) => item.id === root)?.name ?? root
  const crumbs = path ? path.split('/') : []
  const selectedRoot = rootOptions.find((item) => item.id === root)
  const canZip = Boolean(selectedRoot)

  return <div className={styles.deliverablesOverlay}>
    <section className={styles.deliverablesPanel} role="dialog" aria-modal="true" aria-label="Entregables">
      <header className={styles.deliverablesHeader}>
        <div><h2>Entregables</h2><p>Previews y archivos de esta conversación</p></div>
        <button type="button" className={styles.pageButton} onClick={onClose} aria-label="Cerrar Entregables">Cerrar</button>
      </header>
      <div className={styles.deliverablesBody}>
        <section className={styles.deliverablesSection} aria-label="Previews">
          <h3>Previews</h3>
          {!previewList.available && <p className={styles.muted}>{previewList.error_code ?? 'preview_gateway_unavailable'}</p>}
          {previewList.items.length === 0 && <p className={styles.muted}>Todavía no hay previews.</p>}
          {previewList.items.map((preview) => <article className={styles.previewCard} key={preview.id}>
            <div className={styles.previewHeading}>
              <strong>{preview.kind === 'static' ? 'Web estática' : 'Servidor local'}</strong>
              <span>{statusLabels[preview.status] ?? preview.status}</span>
            </div>
            <p>{preview.root}{preview.path ? ` · ${preview.path}` : ''}</p>
            {preview.error_code && <p role="alert">{preview.error_code}</p>}
            {preview.log_tail.length > 0 && <details><summary>Salida reciente</summary><pre className={styles.previewLog}>{preview.log_tail.join('\n')}</pre></details>}
            <div className={styles.previewActions}>
              <button type="button" disabled={preview.status !== 'running' || busy !== ''} onClick={() => { void openPreview(preview) }}>Abrir</button>
              <button type="button" disabled={preview.status !== 'running' || busy !== ''} onClick={() => { void showInline(preview) }}>Ver aquí</button>
              <button type="button" disabled={!['running', 'starting'].includes(preview.status) || busy !== ''} onClick={() => { void stopPreview(preview) }}>Detener</button>
            </div>
            {inlinePreview?.id === preview.id && <iframe className={styles.previewFrame} src={inlinePreview.url} title="Preview de la conversación" sandbox="allow-scripts allow-forms allow-same-origin allow-popups" />}
          </article>)}
        </section>
        <section className={styles.deliverablesSection} aria-label="Explorador de archivos">
          <div className={styles.deliverablesToolbar}>
            <h3>Archivos</h3>
            <label>Raíz<select aria-label="Raíz de archivos" value={root} onChange={(event) => { setRoot(event.target.value); setPath('') }}>
              {rootOptions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select></label>
          </div>
          <nav className={styles.deliverablesCrumbs} aria-label="Ruta actual">
            <button type="button" onClick={() => setPath('')}>{rootName}</button>
            {crumbs.map((crumb, index) => <span key={index}><span aria-hidden="true">/</span><button type="button" onClick={() => setPath(crumbs.slice(0, index + 1).join('/'))}>{crumb}</button></span>)}
          </nav>
          {canZip && <a className={styles.pageButton} href={api.fileZipUrl(conversationId, root, path)} download>Descargar ZIP</a>}
          {truncated && <p className={styles.muted}>Se muestran las primeras 2000 entradas.</p>}
          <div className={styles.deliverablesList}>
            {listing.map((entry) => <div className={styles.deliverableEntry} key={entry.name}>
              {entry.directory
                ? <button type="button" onClick={() => setPath(joinPath(path, entry.name))}>Carpeta: {entry.name}</button>
                : <a href={api.fileContentUrl(conversationId, root, joinPath(path, entry.name))} download>Archivo: {entry.name}</a>}
              {!entry.directory && <small>{entry.size_bytes.toLocaleString()} bytes</small>}
            </div>)}
            {listing.length === 0 && <p className={styles.muted}>{rootOptions.length ? 'Esta carpeta está vacía.' : 'No hay raíces disponibles.'}</p>}
          </div>
        </section>
      </div>
      {error && <p className={styles.deliverablesError} role="alert">{error}</p>}
    </section>
  </div>
}
