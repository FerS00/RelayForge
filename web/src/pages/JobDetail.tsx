import { useCallback, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Agent, type Job } from '../api'
import { AgentSelection } from '../components/AgentSelection'
import { useJobEventStream } from '../lib/eventStream'
import styles from '../styles.module.css'

function activityLabel(event: NonNullable<Job['events']>[number]): string {
  if (event.type === 'job.state_changed') return `${String(event.data.from ?? 'Creado')} → ${String(event.data.to)}`
  if (event.type === 'checks.result') {
    const counts = event.data.counts as { passed?: number; failed?: number; skipped?: number } | null
    const summary = counts ? ` · ${counts.passed ?? 0} passed, ${counts.failed ?? 0} failed, ${counts.skipped ?? 0} skipped` : ''
    return `Check ${String(event.data.name)}: ${String(event.data.status)}${summary}`
  }
  if (event.type === 'audit.result') return `Audit ${String(event.data.verdict)} · ${String(event.data.findings)} findings`
  if (event.type === 'triage.decision') return `Triage ${String(event.data.finding_id)}: ${String(event.data.decision)}`
  if (event.type === 'final_review.created') return `Revisión final · ${String(event.data.diff_hash).slice(0, 12)}`
  if (event.type === 'approval.requested') return `Aprobación solicitada · ${String(event.data.id)}`
  if (event.type === 'approval.decided') return `Aprobación ${String(event.data.decision)} · ${String(event.data.scope)}`
  if (event.type === 'delivery.completed') return `Entrega completada · ${String(event.data.commit).slice(0, 12)}`
  return event.type
}

export function JobDetail() {
  const { id } = useParams()
  const queryClient = useQueryClient()
  const job = useQuery({ queryKey: ['job', id], queryFn: () => api.job(id!), enabled: Boolean(id), refetchInterval: (query) => ['COMPLETED', 'FAILED', 'CANCELLED'].includes(query.state.data?.status ?? '') ? false : 2000 })
  const receive = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['job', id] })
    void queryClient.invalidateQueries({ queryKey: ['jobs'] })
  }, [id, queryClient])
  useJobEventStream(id, receive, receive as () => void)
  const cancel = useMutation({
    mutationFn: () => api.cancelJob(id!),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['job', id] })
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
  const resume = useMutation({
    mutationFn: (mode: 'resume_session' | 'retry_step') => api.resumeJob(id!, mode),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['job', id] })
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
  if (job.isLoading) return <main className={styles.page}><p className={styles.muted}>Cargando Job…</p></main>
  if (job.isError || !job.data) return <main className={styles.page}><p role="alert">No se pudo cargar el Job.</p><Link to="/jobs">Volver a Jobs</Link></main>
  const value = job.data
  const terminal = ['COMPLETED', 'FAILED', 'CANCELLED'].includes(value.status)
  return <main className={styles.page}>
    <header className={styles.pageHeader}>
      <div><h1>{value.display_id} · {value.title}</h1><p>{value.status} · workflow {value.workflow} · versión {value.version}</p></div>
      <div className={styles.pageActions}>
        <Link className={styles.pageButton} to="/jobs">Jobs</Link>
        {!terminal && <button className={styles.pageButton} disabled={cancel.isPending} onClick={() => cancel.mutate()}>Cancelar</button>}
        {value.status === 'INTERRUPTED' && <button className={styles.pageButton} disabled={resume.isPending} onClick={() => resume.mutate('retry_step')}>Reintentar paso</button>}
        {value.status === 'INTERRUPTED' && value.steps?.some((step) => step.status === 'INTERRUPTED' && step.resume_token) &&
          <button className={styles.pageButton} disabled={resume.isPending} onClick={() => resume.mutate('resume_session')}>Reanudar sesión</button>}
      </div>
    </header>
    {cancel.isError && <p role="alert">No se pudo cancelar el Job: {cancel.error.message}</p>}
    {resume.isError && <p role="alert">No se pudo reanudar el Job: {resume.error.message}</p>}
    {value.status === 'WAITING_RETRY' && <p role="status">Reintento programado para {value.retry_at ?? 'una hora pendiente'}.</p>}
    {value.error_message && <p role="alert">{value.error_message}</p>}
    <section className={styles.planSection} aria-label="Fases del trabajo">
      <h2>Consola de trabajo</h2>
      <p>Planificación → Implementación → Tests/Lint → Auditoría → Aprobación/entrega</p>
      <p>Planificador: {value.planning_agent ?? 'claude'} · modelo {value.planning_model ?? 'predeterminado'}; implementación: Codex · {value.implementation_model ?? 'predeterminado'}; auditoría: Antigravity · {value.audit_model ?? 'predeterminado'}.</p>
      <ol>{value.steps?.map((step) => <li key={step.id}>{step.kind} · {step.agent} · {step.status} · intento {step.attempt}</li>)}</ol>
    </section>
    {['WAITING_AGENT', 'WAITING_RETRY', 'INTERRUPTED'].includes(value.status) || (value.status === 'WAITING_APPROVAL' && value.approval_kind === 'plan') ? <JobDispatchControls key={value.version} value={value} /> : null}
    {value.status === 'WAITING_APPROVAL' && <JobApprovalControls value={value} />}
    <section className={styles.planSection}>
      <h2>Solicitud</h2>
      <p className={styles.messageText}>{value.request_text}</p>
    </section>
    {value.plan && <section className={styles.planSection}>
      <h2>Plan</h2>
      <p><strong>{value.plan.objective}</strong></p>
      <p>{value.plan.summary}</p>
      <h3>Pasos</h3>
      <ol>{value.plan.steps.map((step, index) => <li key={`${index}-${step}`}>{step}</li>)}</ol>
      {value.plan.risks.length > 0 && <><h3>Riesgos</h3><ul>{value.plan.risks.map((risk, index) => <li key={`${index}-${risk}`}>{risk}</li>)}</ul></>}
    </section>}
    {value.repository_id && <section className={styles.planSection}>
      <h2>Changes</h2>
      <p>Rama <code>{value.branch ?? 'Preparando'}</code> · base <code>{value.base_sha ?? 'Preparando'}</code></p>
      {value.codex_thread_id && <p>Codex thread: <code>{value.codex_thread_id}</code></p>}
      {value.diff_paths?.length ? <ul>{value.diff_paths.map((path) => <li key={path}><code>{path}</code></li>)}</ul> : <p className={styles.muted}>Sin cambios capturados todavía.</p>}
      {value.diff && <pre className={styles.diffView}>{value.diff}</pre>}
    </section>}
    {value.findings && value.findings.length > 0 && <section className={styles.planSection}>
      <h2>Audit</h2>
      <ol>{value.findings.map((finding) => <li key={finding.id}>
        <p><strong>{finding.severity}: {finding.title}</strong> · {finding.file}{finding.line ? `:${finding.line}` : ''}</p>
        <p>{finding.evidence}</p><p>Recomendación: {finding.recommendation}</p>
        <p>Triages: {finding.triage_decision ?? 'pendiente'}{finding.triage_reason ? ` · ${finding.triage_reason}` : ''}</p>
      </li>)}</ol>
    </section>}
    <section className={styles.timelineSection}>
      <h2>Actividad</h2>
      <ol className={styles.eventList}>
        {value.events?.map((event) => <li key={event.seq}>
          <span>{activityLabel(event)}</span>
          <time dateTime={event.ts}>{event.ts}</time>
        </li>)}
      </ol>
      {!value.events?.length && <p className={styles.muted}>Esperando actividad…</p>}
    </section>
  </main>
}

function JobDispatchControls({ value }: { value: Job }) {
  const queryClient = useQueryClient()
  const configure = value.status === 'WAITING_APPROVAL'
  const stage = configure ? 'implement' : value.paused_stage ?? value.steps?.find((step) => step.status === 'INTERRUPTED')?.kind ?? 'plan'
  const allowed: Agent[] = configure ? ['codex', 'antigravity'] : stage === 'implement' ? ['codex'] : stage === 'audit' ? ['antigravity'] : ['claude', 'codex']
  const initialAgent: Agent = stage === 'implement' ? 'codex' : stage === 'audit' ? 'antigravity' : value.planning_agent ?? 'claude'
  const [agent, setAgent] = useState<Agent>(initialAgent)
  const [model, setModel] = useState(stage === 'implement' ? value.implementation_model ?? '' : stage === 'audit' ? value.audit_model ?? '' : value.planning_model ?? '')
  const dispatch = useMutation({
    mutationFn: ({ selected, selectedModel }: { selected: Agent; selectedModel: string }) => api.dispatchStep(value.id, selected, selectedModel || undefined, value.version),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['job', value.id] }); void queryClient.invalidateQueries({ queryKey: ['jobs'] }) },
  })
  return <section className={styles.planSection}>
    <h2>{configure ? 'Selección antes de aprobar el plan' : `Continuar etapa: ${stage}`}</h2>
    <form className={styles.jobForm} onSubmit={(event) => { event.preventDefault(); dispatch.mutate({ selected: agent, selectedModel: model }) }}>
      <AgentSelection agent={agent} model={model} label="siguiente turno" allowed={allowed} onAgent={setAgent} onModel={setModel} />
      <button className={styles.pageButton} disabled={dispatch.isPending}>{configure ? 'Guardar selección' : 'Continuar trabajo'}</button>
      {!configure && ['plan', 'triage'].includes(stage) && value.planning_agent !== 'codex' && <button type="button" className={styles.pageButton} disabled={dispatch.isPending} onClick={() => dispatch.mutate({ selected: 'codex', selectedModel: '' })}>Continuar con Codex</button>}
      {dispatch.isError && <p role="alert">{dispatch.error.message}</p>}
    </form>
  </section>
}

function JobApprovalControls({ value }: { value: Job }) {
  const queryClient = useQueryClient()
  const pending = useQuery({ queryKey: ['approvals'], queryFn: api.approvals, refetchInterval: 2000 })
  const decide = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: 'approve' | 'reject' }) => api.decideApproval(id, decision, 'once'),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['approvals'] }); void queryClient.invalidateQueries({ queryKey: ['job', value.id] }) },
  })
  return <section className={styles.planSection}>
    <h2>Aprobación humana</h2>
    {pending.data?.filter((approval) => approval.job_id === value.id).map((approval) => <div key={approval.id}>
      <p>Operación: {String(approval.operation.kind)} · estado {approval.status}</p>
      <button className={styles.pageButton} disabled={decide.isPending} onClick={() => decide.mutate({ id: approval.id, decision: 'approve' })}>{approval.operation.kind === 'plan' ? 'Aprobar plan' : `Autorizar ${String(approval.operation.kind)}`}</button>
      <button className={styles.pageButton} disabled={decide.isPending} onClick={() => decide.mutate({ id: approval.id, decision: 'reject' })}>Rechazar</button>
    </div>)}
    {(pending.isError || decide.isError) && <p role="alert">No se pudo consultar o registrar la aprobación.</p>}
    <Link to="/approvals">Revisar detalle y alcance de aprobaciones</Link>
  </section>
}
