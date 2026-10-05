import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Approval } from '../api'
import styles from '../styles.module.css'

export function Approvals() {
  const queryClient = useQueryClient()
  const pending = useQuery({ queryKey: ['approvals'], queryFn: api.approvals })
  const decide = useMutation({
    mutationFn: ({ id, decision, scope }: { id: string; decision: 'approve' | 'reject'; scope: 'once' | 'job' }) => api.decideApproval(id, decision, scope),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['approvals'] }),
        queryClient.invalidateQueries({ queryKey: ['jobs'] }),
      ])
    },
  })
  return <main className={styles.page}>
    <header className={styles.pageHeader}><div><h1>Aprobaciones</h1><p>Revisa el diff y el destino antes de autorizar una entrega.</p></div><Link className={styles.pageButton} to="/jobs">Jobs</Link></header>
    {pending.isLoading && <p className={styles.muted}>Cargando aprobaciones…</p>}
    {pending.isError && <p role="alert">No se pudieron cargar las aprobaciones.</p>}
    {pending.data?.length === 0 && <p className={styles.muted}>No hay aprobaciones pendientes.</p>}
    {pending.data?.map((approval: Approval) => <section className={styles.planSection} key={approval.id}>
      <h2><Link to={`/jobs/${approval.job_id}`}>{approval.job_id}</Link> · entrega</h2>
      <p>Destino <code>{String(approval.operation.target)}</code></p>
      <p>Mensaje <code>{String(approval.operation.message)}</code></p>
      <p>Hash del diff <code>{approval.diff_hash}</code></p>
      <ul>{(approval.operation.paths as string[] | undefined)?.map((path) => <li key={path}><code>{path}</code></li>)}</ul>
      {approval.overlaps.length > 0 && <div role="alert"><strong>Rutas compartidas con otros Jobs activos</strong>{approval.overlaps.map((overlap) => <p key={overlap.job_id}>{overlap.job_id}: {overlap.paths.join(', ')}</p>)}</div>}
      <div className={styles.pageActions}>
        <button className={styles.pageButton} disabled={decide.isPending} onClick={() => decide.mutate({ id: approval.id, decision: 'approve', scope: 'once' })}>Approve once</button>
        <button className={styles.pageButton} disabled={decide.isPending} onClick={() => decide.mutate({ id: approval.id, decision: 'approve', scope: 'job' })}>Approve for job</button>
        <button className={styles.pageButton} disabled={decide.isPending} onClick={() => decide.mutate({ id: approval.id, decision: 'reject', scope: 'once' })}>Reject</button>
      </div>
    </section>)}
    {decide.isError && <p role="alert">No se pudo registrar la decisión: {decide.error.message}</p>}
  </main>
}
