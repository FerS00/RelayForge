import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type Conversation, type ToolKey } from '../api'
import styles from '../styles.module.css'

const tools: { key: ToolKey; label: string; description: string }[] = [
  { key: 'write_files', label: 'Escribir archivos', description: 'Crear o reemplazar archivos de texto con aprobación.' },
  { key: 'commands', label: 'Comandos locales', description: 'Tareas locales con Codex en el workspace.' },
  { key: 'git_local', label: 'Git local y desarrollo', description: 'Jobs con worktree, checks y auditoría.' },
  { key: 'preview', label: 'Preview', description: 'Iniciar y detener previews de entregables.' },
  { key: 'desktop', label: 'Escritorio (GUI)', description: 'Abrir y operar aplicaciones permitidas en la laptop.' },
  { key: 'web_search', label: 'Búsqueda web', description: 'Permite al agente buscar en Internet.' },
  { key: 'remote_delivery', label: 'Entrega remota', description: 'Commit/push solo con aprobación exacta de cada operación.' },
]
const errors: Record<string, string> = {
  effort_unsupported: 'Ese nivel de esfuerzo no lo admite el modelo actual.',
  settings_version_conflict: 'La configuración cambió en otra pestaña; se recargó la versión actual.',
  tool_dependency: 'La entrega remota requiere Git local activado.',
}

export function ConversationSettings({ conversation }: { conversation: Conversation }) {
  const client = useQueryClient()
  const [message, setMessage] = useState('')
  const update = useMutation({
    mutationFn: (change: { effort?: string; tools?: Partial<Record<ToolKey, boolean>> }) => api.updateConversationSettings(conversation.id, { ...change, settings_version: conversation.settings_version ?? 0 }),
    onSuccess: () => setMessage('Se aplica desde tu próximo mensaje.'),
    onError: (error) => setMessage(errors[error.message] ?? error.message),
    onSettled: () => { void client.invalidateQueries({ queryKey: ['messages', conversation.id] }); void client.invalidateQueries({ queryKey: ['conversations'] }) },
  })
  const supported = conversation.supported_efforts ?? []
  return <details className={styles.chatOptions}>
    <summary>Esfuerzo y herramientas · {conversation.effective_effort || 'predeterminado de la CLI'}</summary>
    {supported.length > 0 && <label>Esfuerzo<select aria-label="Esfuerzo de razonamiento" value={conversation.effort ?? ''} disabled={update.isPending} onChange={(event) => update.mutate({ effort: event.target.value })}>
      <option value="">Predeterminado ({conversation.effective_effort || 'CLI'})</option>
      {supported.map((level) => <option key={level} value={level}>{level}</option>)}
    </select></label>}
    <fieldset className={styles.toolToggles}><legend>Herramientas</legend>
      {tools.map((tool) => <label key={tool.key} title={tool.description}>
        <input type="checkbox" checked={Boolean(conversation.tools?.[tool.key])} disabled={update.isPending} onChange={(event) => update.mutate({ tools: { [tool.key]: event.target.checked } })} />
        <span>{tool.label}<small>{tool.description}</small></span>
      </label>)}
    </fieldset>
    <p className={styles.settingsNote}>Activar una herramienta no sustituye las aprobaciones exactas. Los cambios se aplican desde tu próximo mensaje.</p>
    {message && <p role={update.isError ? 'alert' : 'status'}>{message}</p>}
  </details>
}
