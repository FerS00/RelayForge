import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api, type Agent } from '../api'
import { AgentSelection } from '../components/AgentSelection'
import styles from '../styles.module.css'

export function NewTask() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [title, setTitle] = useState('')
  const [request, setRequest] = useState('')
  const [repositoryId, setRepositoryId] = useState(params.get('repository_id') ?? '')
  const [agent, setAgent] = useState<Agent>('claude')
  const [model, setModel] = useState('')
  const [implementationModel, setImplementationModel] = useState('')
  const [auditModel, setAuditModel] = useState('')
  const [workflow, setWorkflow] = useState(params.has('repository_id') ? 'feature' : 'auto')
  const repositories = useQuery({ queryKey: ['repos'], queryFn: api.repositories })
  const create = useMutation({
    mutationFn: () => api.createJob(title.trim(), request.trim(), repositoryId || undefined, workflow,
      { agent, model: model || undefined, implementation_model: implementationModel || undefined, audit_model: auditModel || undefined, require_plan_approval: Boolean(repositoryId) }),
    onSuccess: ({ job }) => navigate(`/jobs/${job.id}`),
  })
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    create.mutate()
  }
  return <main className={styles.page}>
    <header className={styles.pageHeader}>
      <div><h1>Nueva tarea</h1><p>Plan → aprobación → implementación Codex → checks → auditoría → entrega aprobada.</p></div>
      <Link className={styles.pageButton} to="/jobs">Volver a Jobs</Link>
    </header>
    <form className={styles.jobForm} onSubmit={submit}>
      <label>Título (opcional)
        <input maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} />
      </label>
      <label>Solicitud
        <textarea required minLength={1} maxLength={100000} value={request} onChange={(event) => setRequest(event.target.value)} />
      </label>
      <label>Repositorio
        <select value={repositoryId} onChange={(event) => { setRepositoryId(event.target.value); setWorkflow(event.target.value ? 'feature' : 'auto') }}>
          <option value="">Solo generar un plan</option>
          {(repositories.data ?? []).filter((repository) => repository.enabled).map((repository) =>
            <option key={repository.id} value={repository.id}>{repository.name}{repository.dirty ? ' · cambios locales fuera del Job' : ''}</option>)}
        </select>
      </label>
      {repositoryId && <label>Workflow
        <select value={workflow} onChange={(event) => setWorkflow(event.target.value)}>
          <option value="auto">Auto (según el plan)</option>
          <option value="trivial">Trivial</option>
          <option value="feature">Feature</option>
          <option value="security">Security</option>
        </select>
      </label>}
      <AgentSelection agent={agent} model={model} label="planificación" allowed={['claude', 'codex']} onAgent={setAgent} onModel={setModel} />
      {repositoryId && <>
        <AgentSelection agent="codex" model={implementationModel} label="implementación" allowed={['codex']} onAgent={() => undefined} onModel={setImplementationModel} />
        <AgentSelection agent="antigravity" model={auditModel} label="auditoría" allowed={['antigravity']} onAgent={() => undefined} onModel={setAuditModel} />
        <p>El plan necesita aprobación antes de implementar. Antigravity audita sin editar archivos.</p>
      </>}
      {create.isError && <p role="alert">{create.error.message}</p>}
      <button className={`${styles.pageButton} ${styles.pageButtonPrimary}`} disabled={create.isPending || !request.trim()}>
        {create.isPending ? 'Creando…' : repositoryId ? 'Planificar tarea' : 'Crear Job de planificación'}
      </button>
    </form>
  </main>
}
