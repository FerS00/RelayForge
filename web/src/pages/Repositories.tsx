import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import styles from '../styles.module.css'

export function Repositories() {
  const queryClient = useQueryClient()
  const repositories = useQuery({ queryKey: ['repos'], queryFn: api.repositories })
  const [mode, setMode] = useState<'register' | 'create'>('register')
  const [name, setName] = useState('')
  const [path, setPath] = useState('')
  const [checkCommands, setCheckCommands] = useState('[]')
  const add = useMutation({
    mutationFn: () => {
      const parsed: unknown = JSON.parse(checkCommands)
      if (!Array.isArray(parsed)) throw new Error('Los checks deben ser una lista JSON.')
      return api.addRepository({
        mode, name: name.trim(), check_commands: parsed,
        ...(mode === 'register' ? { path: path.trim() } : {}),
      })
    },
    onSuccess: () => {
      setName('')
      setPath('')
      setCheckCommands('[]')
      void queryClient.invalidateQueries({ queryKey: ['repos'] })
    },
  })
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    add.mutate()
  }
  return <main className={styles.page}>
    <header className={styles.pageHeader}>
      <div><h1>Repositories</h1><p>Repositorios locales que pueden recibir Jobs en worktrees aislados.</p></div>
      <div className={styles.pageActions}><Link className={styles.pageButton} to="/jobs">Jobs</Link></div>
    </header>
    <form className={styles.jobForm} onSubmit={submit}>
      <label>Acción
        <select value={mode} onChange={(event) => setMode(event.target.value as 'register' | 'create')}>
          <option value="register">Registrar repositorio Git existente</option>
          <option value="create">Crear repositorio bajo projects_root</option>
        </select>
      </label>
      <label>Nombre<input required minLength={1} maxLength={64} value={name} onChange={(event) => setName(event.target.value)} /></label>
      {mode === 'register' && <label>Ruta local<input required maxLength={4096} value={path} onChange={(event) => setPath(event.target.value)} /></label>}
      <label>Checks declarados (JSON argv)
        <textarea aria-describedby="check-help" value={checkCommands} onChange={(event) => setCheckCommands(event.target.value)} />
      </label>
      <p id="check-help" className={styles.muted}>Cada elemento usa name, argv y timeout_seconds opcional. No uses shell; por ejemplo: <code>{'[{"name":"pytest","argv":["uv","run","pytest","-q"]}]'}</code>.</p>
      {add.isError && <p role="alert">No se pudo guardar el repositorio: {add.error.message}</p>}
      <button className={`${styles.pageButton} ${styles.pageButtonPrimary}`} disabled={add.isPending || !name.trim()}>
        {add.isPending ? 'Guardando…' : mode === 'create' ? 'Crear repositorio' : 'Registrar repositorio'}
      </button>
    </form>
    {repositories.isError && <p role="alert">No se pudieron cargar los repositorios.</p>}
    <section className={styles.repositoryList} aria-label="Repositorios registrados">
      {(repositories.data ?? []).map((repository) => <article className={styles.repositoryCard} key={repository.id}>
        <h2>{repository.name}{repository.dirty ? ' · cambios sin commit' : ''}</h2>
        <p>{repository.path}</p>
        <p>Rama predeterminada: {repository.default_branch}</p>
        <p>Checks: {repository.check_commands.length}</p>
      </article>)}
    </section>
  </main>
}
