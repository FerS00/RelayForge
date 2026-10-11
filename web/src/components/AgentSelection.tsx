import { useId } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type Agent } from '../api'

const names: Record<Agent, string> = { claude: 'Claude Code', codex: 'Codex CLI', antigravity: 'Antigravity (solo lectura)' }

export function AgentSelection({ agent, model, allowed, label, onAgent, onModel }: {
  agent: Agent; model: string; allowed: Agent[]; label: string
  onAgent: (agent: Agent) => void; onModel: (model: string) => void
}) {
  const id = useId()
  const status = useQuery({ queryKey: ['agent-status'], queryFn: api.agentStatus, staleTime: 30000 })
  const current = status.data?.find((item) => item.agent === agent)
  const models = [...new Set(current?.models ?? [])]
  const savedModelMissing = Boolean(model && !models.includes(model))
  return <fieldset>
    <legend>{label}</legend>
    <label>Agente de {label}
      <select value={agent} onChange={(event) => { onAgent(event.target.value as Agent); onModel('') }}>
        {allowed.map((item) => <option key={item} value={item}>{names[item]}</option>)}
      </select>
    </label>
    <label>Modelo de {label}
      <select id={id} value={model} onChange={(event) => onModel(event.target.value)}>
        <option value="">Predeterminado de la CLI</option>
        {savedModelMissing && <option value={model} disabled>{model} · guardado, fuera del catálogo</option>}
        {models.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
    </label>
    {status.isPending && <p role="status">Cargando modelos…</p>}
    {!status.isPending && !status.isError && models.length === 0 && <p role="status">Sin catálogo disponible; puedes usar el modelo predeterminado.</p>}
    <p>{current ? `CLI: ${current.status} · autenticación: ${current.auth}` : 'Disponibilidad sin comprobar.'}</p>
    {status.isError && <p role="status">No se pudo consultar la disponibilidad del agente.</p>}
  </fieldset>
}
