> Especificación histórica. Las referencias numeradas al plan corresponden al [plan anterior archivado](../archive/PLAN_PROYECTO_2026-10-05_PREVIO.md); para alcance/estado y nuevas fases consulta el [plan vigente](../PLAN_PROYECTO.md). Este aviso no cambia sus criterios previamente aprobados.

# Especificación técnica — Fase 6

Estado: **Completada** (2026-10-04). Antigravity APROBADO en la tercera invocación tras dos respuestas incompletas/alcances de lectura denegados. Modelo `gemini-3.8-flash-high`, esfuerzo `high`; sin denegaciones en el intento aceptado.

## Objetivo

Conectar el workflow de repositorio `feature` con auditoría Antigravity, registro durable de hallazgos, triage estructurado, revisión con Codex y reauditoría. Un veredicto `BLOCKED`, una salida inválida o cambios de hash durante la auditoría nunca se consideran aprobados. El máximo son tres iteraciones; al llegar al límite, el Job queda en `WAITING_APPROVAL` con `approval_kind=iteration_limit`.

## Rutas afectadas

- `docs/specs/FASE_6.md`
- `config/schemas/audit.schema.json`, `config/schemas/triage.schema.json`
- `src/relayforge/adapters/base.py`, `src/relayforge/adapters/antigravity/{__init__.py,adapter.py,gate.py}`
- `src/relayforge/adapters/claude/orchestrator.py`
- `src/relayforge/core/{audit.py,jobs.py,scheduler.py,states.py,workflow.py}`
- `src/relayforge/db/{models.py,migrations/versions/0005_findings.py}`
- `src/relayforge/cli.py`, `src/relayforge/api/app.py`
- `web/src/{api.ts,pages/JobDetail.tsx}`
- `tests/{conftest.py,fakes/fake_codex.py,integration/test_audit_workflow.py,integration/test_db_migrations.py,unit/test_audit_adapter.py,unit/test_audit_gate.py,unit/test_jobs.py}`
- `docs/PLAN_PROYECTO.md`, `docs/ESTADO_TRABAJO.md`

## Contratos

- `AuditAdapter.audit(worktree, changed_paths, commands, iteration) -> AuditResult`; resultado validado contra `audit.schema.json`: veredicto `APPROVED | APPROVED_WITH_NOTES | REJECTED | BLOCKED`, hallazgos acotados con id, severidad, ruta, línea, título, evidencia y recomendación.
- La implementación calcula SHA-256 de cada ruta revisada antes y después. Rutas fuera del worktree, hashes diferentes, fallo del gate, timeout, salida ausente o JSON inválido producen `BLOCKED`.
- Las herramientas del auditor operan con allowlist exacta de lecturas, checks declarados y herramientas de control no mutables. `gate.py` falla cerrado ante llamada, ruta, comando o directorio no declarado. Los checks se ejecutan mediante el despachador de checks de RelayForge. El adaptador no importa desde `pocs/`.
- `OrchestratorAdapter.triage(ctx, findings, diff, test_results)` devuelve una decisión `accept | reject | defer` y motivo para cada id recibido. Requiere cobertura exacta de todos los hallazgos, sin ids extra ni motivos vacíos. Implementa ClaudeOrchestrator; pruebas y modo degradado usan dobles deterministas.
- Hallazgos se persisten por ejecución de auditoría e iteración. La decisión y motivo de triage se guardan en el mismo registro; GET de Job devuelve hallazgos ordenados.
- Solo decisiones `accept` entran al prompt de Codex resume. `reject` y `defer` no se corrigen. Un rechazo de hallazgo por triage no cambia un veredicto `BLOCKED`.
- `APPROVED` o `APPROVED_WITH_NOTES` sin hallazgos aceptados permiten cerrar la fase del Job como `COMPLETED`. Hallazgos aceptados mueven a `REVISING`; Codex reanuda el thread existente con los hallazgos aceptados explícitos, vuelve a ejecutar checks y reaudita. El máximo es 3.
- Al alcanzar el máximo con hallazgos aceptados, estado `WAITING_APPROVAL`, `approval_kind=iteration_limit`. `BLOCKED` termina en `FAILED` con código `audit_blocked`; no se permite continuar ni saltar auditoría.

## Criterios de aceptación

1. La suite valida schema de auditoría y triage; datos ausentes, adicionales o inválidos se rechazan.
2. El gate deniega herramientas desconocidas, comandos no declarados y rutas fuera de la allowlist. Un intento de escritura no cambia archivos; un cambio de hash da `BLOCKED`.
3. El runner vuelve a comprobar hashes aun si el auditor devuelve aprobación; todo veredicto y resumen quedan persistidos y aparecen en el detalle del Job.
4. El triage crea una fila por hallazgo con decisión y motivo; Codex resume solo recibe hallazgos `accept`.
5. La revisión vuelve a ejecutar checks y auditoría en orden, incrementa iteration y respeta el máximo de tres antes de pedir decisión humana.
6. Cualquier `BLOCKED`, timeout, salida inválida o fallo del gate nunca lleva a estado aprobado o `COMPLETED`.
7. Antigravity audita el diff y ejecuta los comandos declarados de esta fase. Ruff, formato, mypy, pytest, lint, typecheck, Vitest, build y `git diff --check` pasan.

## Verificación manual pendiente

La auditoría real del producto requiere Antigravity CLI autenticada, worktree Git con cambios y permisos de la CLI disponibles. No se afirmó su ejecución real desde las pruebas unitarias. La auditoría independiente del cambio sí se ejecutó y aprobó; run `0663c013e031449eb4ee5214f3ee3884`.
