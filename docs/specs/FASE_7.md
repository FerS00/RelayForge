> Especificación histórica. Las referencias numeradas al plan corresponden al [plan anterior archivado](../archive/PLAN_PROYECTO_2026-10-05_PREVIO.md); para alcance/estado y nuevas fases consulta el [plan vigente](../PLAN_PROYECTO.md). Este aviso no cambia sus criterios previamente aprobados.

# Especificación técnica — Fase 7

Estado: Completada (2026-10-04). Codex especificó/implementó sin Claude; Antigravity auditó en solo lectura.

## Objetivo

Añadir evaluación declarativa `allow | ask | deny`, solicitudes de aprobación idempotentes, grants limitados a un Job, revisión final y operación de entrega guardada por aprobación exacta. Ningún commit ni push ocurre si no coinciden Job, operación, mensaje, rama, destino remoto y hash aprobado del diff. Los destinos protegidos, merge y force push siempre se deniegan. El código permite entrega real tras decisión afirmativa desde la aplicación; las pruebas usan Git falso y no contactan remotos.

## Rutas afectadas

- `docs/specs/FASE_7.md`, `config/policies/default.yaml`
- `src/relayforge/adapters/base.py`, `src/relayforge/adapters/claude/orchestrator.py`
- `src/relayforge/core/{policy.py,approvals.py,delivery.py,jobs.py,scheduler.py,states.py}`
- `src/relayforge/db/{models.py,migrations/versions/0006_approvals.py}`
- `src/relayforge/git/delivery.py`
- `src/relayforge/api/{app.py,schemas.py,routes/approvals.py}`
- `web/src/{App.tsx,api.ts}`, `web/src/pages/Approvals.tsx`
- `tests/{integration/test_approvals.py,integration/test_db_migrations.py,unit/test_policy.py,unit/test_approval_service.py,unit/test_delivery.py,unit/test_states.py}`
- `docs/PLAN_PROYECTO.md`, `docs/ESTADO_TRABAJO.md`

## Contratos

- La política YAML valida `version`, `defaults`, perfiles, escalamiento por paths y overrides. Las capas se evalúan en este orden: defaults, perfil de repositorio, workflow y overrides que coinciden. `deny` de cualquier capa prevalece; entre decisiones restantes gana la capa más específica. Los targets `git.force_push`, `git.merge` y `git.push_protected_branch` son `deny` incondicional.
- `PolicyOperation` contiene `agent`, `role`, `repo`, `workflow`, `tool`, `operation`, `target` y `risk`. Targets y matchers se normalizan antes de comparar.
- `approvals` persiste operación/contexto exactos, riesgo, hash aprobado, estado, decisión, motivo e idempotency keys de solicitud/decisión. `approval_grants` persiste matcher y Job propietario. Grant solo eleva `ask` a `allow` si coincide el matcher en ese Job; nunca `deny`.
- La API lista pendientes y registra una sola decisión por aprobación. Repetir la misma `Idempotency-Key` devuelve el resultado previo; otra clave sobre una decisión ya tomada devuelve 409. La transición, decisión y grant se escriben en una transacción.
- `approve once` autoriza solo el digest y los campos exactos de una operación. `approve for job` crea matcher para el Job actual y debe seguir limitado al mismo `job_id`. Rechazar requiere razón opcional y pasa el Job a `FAILED`.
- La revisión final estructurada persiste `final-review.md`, estado del diff, riesgos y mensaje de commit propuesto. El workflow con entrega solicita aprobación y queda en `WAITING_APPROVAL(delivery)`; tras aprobar, el Core revalida diff/hash/rama/remoto y solo entonces ejecuta `git commit` y `git push origin HEAD:refs/heads/agent/job-N` sin force ni merge.
- Un cambio del worktree después de aprobar invalida la operación. El aviso de solapamiento compara paths de otros Jobs no terminales del mismo repositorio antes de presentar la decisión.
- Un repositorio sin remoto `origin` completa la revisión final sin pedir entrega; no se intenta commit ni push.
- El cliente Git se inyecta en pruebas. Las pruebas no llaman a un remoto ni hacen commit/push real.

## Criterios de aceptación

1. Matriz cubre precedencia, matches, deny gana, escalamiento a `security` y destinos protegidos.
2. Approve once, approve for job y reject persisten decisión; grants de un Job no autorizan otro; deny no se aprueba.
3. Clave idempotente repetida es estable; segunda decisión distinta responde 409.
4. Commit/push se rechaza sin aprobación exacta, con hash cambiado, rama protegida, force o merge; el push planeado usa la rama `agent/job-N` y SHA aprobados.
5. La lista muestra colisión de paths entre Jobs concurrentes y las decisiones aparecen en el detalle/timeline.
6. Migración upgrade/downgrade conserva datos previos; los tests usan dobles Git y no contactan remotos.
7. Antigravity revisa diff y ejecuta Ruff, formato, mypy, pytest, lint, typecheck, Vitest, build y `git diff --check`.

## Límites de ejecución de esta fase

No se enviará un push a un remoto ni se probará Git Credential Manager: D-11 requiere autorización explícita para el remoto de pruebas y el push. Los tests deben demostrar el argv planeado sin abrir conexión.

## Resultado de verificación

- Python: 91 passed, 1 skipped por `WinError 1314` al crear symlink; 1 aviso Starlette/httpx.
- Web: ESLint, TypeScript, 9 Vitest y build PASS. Ruff, formato, mypy y `git diff --check` PASS.
- Antigravity: APROBADO, 7/7 criterios, 10/10 comandos, cero acciones denegadas; `gemini-3.8-flash-medium`, esfuerzo `medium`, run `8f1d5056b88c4056bd2a82e93467c7bc`.
- No se probaron remotos reales ni Git Credential Manager. D-11 sigue pendiente de autorización explícita.
- Graphify incremental `--code-only`: 1200 nodos, 2629 aristas, 98 comunidades. No se reextrajeron semánticamente 22 documentos por falta de API key.
