# Arquitectura actual

Referencia del checkout de desarrollo del 2026-10-05. Código existente no equivale a aceptación de todas las CLIs reales; el [plan](PLAN_PROYECTO.md) delimita lo pendiente.

| Módulo | Responsabilidad |
|---|---|
| `api/` | FastAPI, rutas, pairing/sesión y Host/Origin/CSRF/proxy confiable. |
| `core/jobs.py`, `states.py`, `scheduler.py` | Persistir/serializar Jobs; estados, dispatch versionado y etapas sin dos tareas activas por Job. |
| `core/workflow.py`, `checks.py`, `audit.py` | Worktree, implementación, checks, auditoría, triage y revisión. |
| `core/policy.py`, `approvals.py`, `delivery.py` | Política declarativa, decisiones/grants y entrega ligada a snapshot. |
| `adapters/claude/` | Planificación/consulta/triage, argv y normalización. |
| `adapters/codex/` | Implementación y planner read-only con sesiones/modelos por invocación. |
| `adapters/antigravity/` | CLI auditora, lecturas/checks enumerados y gate/hashes. |
| `process/`, `platform/` | Supervisión Windows, PID + creación y Job Objects. |
| `git/` | Repositorios, worktrees, diff y operaciones controladas. |
| `db/` | SQLAlchemy/SQLite, migraciones 0001–0008 y texto redactado. |
| `security/`, `doctor/` | Redacción/contención/escaneo y probes acotados. |
| `web/src/` | Proyectos, Jobs, modelos, aprobaciones, diagnóstico y métricas. |

## Dispatch y continuidad

`POST /api/jobs` recibe solicitud, repo/workflow, modelos/agent y Idempotency-Key. `POST /api/jobs/{id}/step` exige versión y permite seleccionar una etapa detenida o preparar la selección antes de aprobar. Plan/triage admite Claude/Codex; implementación Codex; auditoría Antigravity. Scheduler conserva la etapa al reanudar.

Planner Codex usa sesión nueva read-only y schema de plan/triage. Implementador usa workspace-write y thread propio. Flags de modelos son por invocación; no se muta un adaptador global.

Job persiste modelos y etapa pausada; eventos registran selección, inicio y uso reportado. `/api/agents/status` combina probes seguros, salud, catálogo configurado y consumo. No lee credenciales para fabricar cuotas; auth Antigravity puede ser UNKNOWN.

## Datos y comunicación

SQLite guarda repositorios, conversaciones, Jobs/pasos/eventos, hallazgos, triage, approvals/grants y salud. Migración 0008 añade selección/relevo sin eliminar Jobs existentes. Resultados se normalizan y redactan según el pipeline.

SSE sirve eventos/replay; las vistas Job también refrescan mediante queries. No todas las CLIs emiten tokens progresivos. El chat de consulta mantiene contrato separado de las tareas operativas.

## Runtime y límites

Nativo: listener loopback Windows. Docker: Server Core/Hyper-V, listener dentro de NAT y proxy confiable exacto. Compose no publica puertos; Windows portproxy escucha loopback y Serve reenvía allí. Volúmenes declarados: runtime, workspace, proyectos, perfil Claude/AGY y Codex. Persistir archivos no demuestra que un keyring/login sobreviva a recreación.

Worktree separa cambios Git, no permisos del OS. Checks/CLIs conservan permisos efectivos de su contexto. El gate auditor falla ante accesos denegados/checks omitidos; tampoco es sandbox completo del sistema operativo.
