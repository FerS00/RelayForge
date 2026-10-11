import { useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type ChatAction, type Job } from '../api'
import styles from '../styles.module.css'

const labels: Record<string, string> = {list_directory: 'Listar carpeta', read_file: 'Leer archivo', write_file: 'Escribir archivo', native_task: 'Ejecutar tarea local', development_job: 'Desarrollar proyecto', start_preview: 'Iniciar preview', stop_preview: 'Detener preview', desktop_launch: 'Abrir aplicación', desktop_inspect: 'Inspeccionar ventana', desktop_invoke: 'Pulsar control', desktop_set_value: 'Escribir valor', desktop_type: 'Escribir texto', desktop_keys: 'Enviar teclas', desktop_menu: 'Usar menú', desktop_capture: 'Capturar ventana', desktop_close: 'Cerrar ventana', pending: 'Esperando decisión', approved: 'Aprobada', running: 'En curso', complete: 'Terminada', failed: 'Fallida', rejected: 'Rechazada', interrupted: 'Interrumpida', plan: 'Planificación', implement: 'Implementación', checks: 'Comprobaciones', audit: 'Auditoría', SUCCEEDED: 'Terminada', COMPLETED: 'Terminado', WAITING_APPROVAL: 'Esperando aprobación'}
const label = (value: string) => labels[value] ?? value

function ActionDetails({ action, conversation }: {action: ChatAction; conversation: string}) {
  return <div className={styles.actionDetails}>
    {typeof action.result?.attachment_id === 'string' && <a href={api.attachmentUrl(conversation, action.result.attachment_id)} target="_blank" rel="noreferrer"><img className={styles.evidenceImage} src={api.attachmentUrl(conversation, action.result.attachment_id)} alt="Captura de la ventana" loading="lazy" /></a>}
    {action.payload.path && <p>Recurso: <code>{action.payload.path}</code></p>}
    {action.payload.request && <p>{action.payload.request}</p>}
    {action.payload.content && <pre className={styles.diffView}>{action.payload.content}</pre>}
    {action.result?.error != null && <p role="alert">{String(action.result.error)}</p>}
    {action.result?.response != null && <p>{String(action.result.response)}</p>}
    {action.result?.text != null && <pre className={styles.diffView}>{String(action.result.text)}</pre>}
    {Array.isArray(action.result?.changed_paths) && <p>Archivos cambiados: {action.result.changed_paths.join(', ')}</p>}
  </div>
}

export function ConversationActions({ conversation, actions, jobs }: { conversation: string; actions: ChatAction[]; jobs: Job[] }) {
  const client = useQueryClient()
  const keys = useRef(new Map<string, string>())
  const key = (id: string, decision: string) => {
    const operation = `${id}:${decision}`
    if (!keys.current.has(operation)) keys.current.set(operation, crypto.randomUUID())
    return keys.current.get(operation)!
  }
  const refresh = () => { void client.invalidateQueries({ queryKey: ['messages', conversation] }); void client.invalidateQueries({ queryKey: ['approvals'] }) }
  const decision = useMutation({ mutationFn: ({ action, value }: { action: ChatAction; value: 'approve' | 'reject' }) => api.decideAction(conversation, action, value, key(action.id, value)), onSuccess: refresh })
  const pending = useQuery({ queryKey: ['approvals'], queryFn: api.approvals, enabled: jobs.length > 0, refetchInterval: jobs.some(job => job.status === 'WAITING_APPROVAL') ? 2000 : false })
  const approve = useMutation({ mutationFn: ({ id, value }: { id: string; value: 'approve' | 'reject' }) => api.decideApproval(id, value, 'once'), onSuccess: refresh })
  return <section aria-label="Acciones y trabajo de la conversación">
    {actions.map(action => <article key={action.id} className={styles.message}>
      <strong>{label(action.kind)}</strong> · {label(action.status)}
      {action.status === 'pending' ? <ActionDetails action={action} conversation={conversation} /> : <details open={typeof action.result?.attachment_id === 'string'}><summary>Ver operación y resultado</summary><ActionDetails action={action} conversation={conversation} /></details>}
      {action.status === 'pending' && <div><p>Esta decisión autoriza únicamente la operación mostrada y la versión actual del recurso.</p><button disabled={decision.isPending} onClick={() => decision.mutate({action, value: 'approve'})}>Aprobar acción</button><button disabled={decision.isPending} onClick={() => decision.mutate({action, value: 'reject'})}>Rechazar acción</button></div>}
      {action.status === 'interrupted' && <p>No se repite automáticamente; revisa el recurso y solicita una nueva acción.</p>}
    </article>)}
    {jobs.map(job => <article key={job.id} className={styles.message}>
      <strong>{job.title}</strong> · {label(job.status)}
      {job.plan && <div><h3>Plan</h3><p>{job.plan.summary}</p><ol>{job.plan.steps.map((step, index) => <li key={index}>{step}</li>)}</ol></div>}
      {job.steps?.map(step => <p key={step.id}>{label(step.kind)} · {step.agent} · {label(step.status)}</p>)}
      {job.error_message && <p role="alert">{job.error_message}</p>}
      {job.diff && <details><summary>Cambios</summary><pre className={styles.diffView}>{job.diff}</pre></details>}
      {job.events?.filter(event => ['checks.result', 'audit.result'].includes(event.type)).map(event => <p key={event.seq}>{event.type === 'checks.result' ? `Comprobación ${String(event.data.name)}: ${String(event.data.status)}` : `Auditoría ${String(event.data.verdict)}: ${String(event.data.summary ?? '')}`}</p>)}
      {job.findings?.map(finding => <p key={finding.id}>{finding.severity}: {finding.title} · {finding.recommendation}</p>)}
      {pending.data?.filter(approval => approval.job_id === job.id).map(approval => <div key={approval.id}><div className={styles.actionDetails}><p>Operación: {String(approval.operation.operation ?? approval.operation.kind ?? 'Plan')}</p>{approval.operation.target != null && <p>Destino: {String(approval.operation.target)}</p>}{approval.operation.message != null && <p>Mensaje: {String(approval.operation.message)}</p>}<details><summary>Detalle de la aprobación</summary><pre className={styles.diffView}>{JSON.stringify(approval.operation, null, 2)}</pre></details></div><button disabled={approve.isPending} onClick={() => approve.mutate({id: approval.id, value: 'approve'})}>{job.approval_kind === 'plan' ? 'Aprobar plan' : 'Aprobar operación'}</button><button disabled={approve.isPending} onClick={() => approve.mutate({id: approval.id, value: 'reject'})}>Rechazar</button></div>)}
    </article>)}
    {(decision.error || approve.error) && <p role="alert">{decision.error?.message ?? approve.error?.message}</p>}
  </section>
}
