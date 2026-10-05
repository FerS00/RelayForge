> Especificación histórica. Las referencias numeradas al plan corresponden al [plan anterior archivado](../archive/PLAN_PROYECTO_2026-10-05_PREVIO.md); para alcance/estado y nuevas fases consulta el [plan vigente](../PLAN_PROYECTO.md). Este aviso no cambia sus criterios previamente aprobados.

# Especificación técnica — Fase 3

- Estado: **Completada** (2026-10-04). Antigravity: **APROBADO**; 10 criterios revisados y 10/10 comandos con código 0. Modelo/esfuerzo auditor: `gemini-3.8-flash-high` / `high`.
- Responsable de especificación e implementación: Codex.
- Auditor independiente: Antigravity en modo code, solo lectura.
- Base: `docs/PLAN_PROYECTO.md`, secciones 12, 21, 23 y Fase 3; POC-02 y POC-05 constan como PASS en `docs/POC_RESULTADOS.md`.

## Objetivo

Permitir registrar repositorios Git existentes, crear repositorios locales bajo `projects_root`, ejecutar la implementación planificada dentro de un worktree aislado con el adapter Codex y consultar el diff resultante desde la web. Los agentes de prueba serán dobles: las pruebas no lanzarán CLIs reales.

## Contratos y reglas

- `RepositoryService` valida el nombre, la ruta canónica, que el directorio exista y sea un repositorio Git, y obtiene HEAD, rama por defecto y cambios sin commit. El registro no ejecuta fetch ni altera el repositorio existente.
- `POST /api/repos` acepta `{mode:"register", name, path}` o `{mode:"create", name}`. Crear solo permite un nombre de un componente, dentro de `Settings.projects_root`; inicializa Git y hace un commit inicial vacío. Rechaza rutas fuera de esa raíz, colisiones y nombres inválidos.
- Se añade `repositories` por migración aditiva. Un Job refiere a un repositorio opcional; la configuración de Fase 2 sin repositorio sigue legible.
- `WorktreeManager` mantiene un lock por repositorio para add/remove/prune; cada Job recibe ruta fuera del repo principal, rama única `agent/job-N`, `base_sha` fijo y lock de Git. No modifica el checkout principal. Concurrencia máxima inicial: 2 Jobs activos por repositorio.
- El adapter Codex construye argumentos como lista (sin `shell=True`), usa `codex exec --json -C <worktree> -s workspace-write --output-schema <schema> -`, analiza JSONL tolerando eventos desconocidos, registra `thread_id`, y soporta `resume`. La ubicación del binario se resuelve por PATH o configuración. No captura ni devuelve secretos del entorno.
- El workflow conecta el plan existente con implementación, valida que haya diff y que todas las rutas cambiadas resuelvan dentro del worktree, y registra `file.changed`. El diff devuelto se deriva de `git diff <base_sha>`.
- La web ofrece listado y registro/creación de repositorios y una pestaña Changes en Job Detail; expone la advertencia de cambios sin commit que quedan fuera del Job.

## Rutas afectadas

- `src/relayforge/settings.py`
- `src/relayforge/cli.py`
- `src/relayforge/db/models.py`
- `src/relayforge/db/migrations/versions/0003_repositories.py`
- `src/relayforge/core/repositories.py`
- `src/relayforge/git/worktrees.py`
- `src/relayforge/core/workflow.py`
- `src/relayforge/git/__init__.py`
- `src/relayforge/git/operations.py`
- `src/relayforge/adapters/codex/__init__.py`
- `src/relayforge/adapters/codex/adapter.py`
- `src/relayforge/adapters/codex/parser.py`
- `src/relayforge/adapters/codex/schema.json`
- `src/relayforge/api/app.py`
- `src/relayforge/api/schemas.py`
- `src/relayforge/api/routes/repositories.py`
- `src/relayforge/api/routes/jobs.py`
- `src/relayforge/core/jobs.py`
- `src/relayforge/core/states.py`
- `src/relayforge/core/scheduler.py`
- `web/src/App.tsx`
- `web/src/api.ts`
- `web/src/pages/Repositories.tsx`
- `web/src/pages/Repositories.test.tsx`
- `web/src/pages/JobDetail.tsx`
- `web/src/pages/JobDetail.test.tsx`
- `web/src/pages/Dashboard.test.tsx`
- `web/src/pages/NewTask.test.tsx`
- `web/src/styles.module.css`
- `tests/fakes/fake_agent.py`
- `tests/fakes/fake_codex.py`
- `tests/conftest.py`
- `tests/unit/test_repositories.py`
- `tests/unit/test_codex_adapter.py`
- `tests/unit/test_worktrees.py`
- `tests/integration/test_repositories_api.py`
- `tests/integration/test_implementation_workflow.py`
- `tests/integration/test_db_migrations.py`
- `tests/unit/test_cli.py`
- `docs/specs/FASE_3.md`

## Criterios de aceptación

1. Se puede registrar un repositorio existente sin cambiar su HEAD ni su working tree; su dirty status queda visible.
2. Crear un repo requiere un nombre válido, queda bajo `projects_root`, contiene un commit inicial y rechaza traversal, colisión y escapes por symlink.
3. La migración preserva conversaciones y Jobs de Fase 2 y tiene downgrade que elimina solo las adiciones de Fase 3.
4. Dos Jobs del mismo repo reciben worktrees y ramas distintas; la operación concurrente de Git sobre el repo principal se serializa.
5. La base del worktree es el SHA fijado; la operación no incluye cambios sin commit del checkout principal.
6. Las pruebas confirman que rutas escritas fuera del worktree no son aceptadas como cambios del Job.
7. El fake Codex permite validar lanzamiento, JSONL, schema, `thread_id`, errores y resume sin ejecutar una CLI real.
8. El diff de API/UI coincide byte a byte con `git diff <base_sha>` y registra los archivos como eventos `file.changed`.
9. La web permite listar, registrar y crear repositorios y muestra los cambios sin commit que no se incluirán en el Job.
10. Ruff, mypy, pytest, lint, typecheck, Vitest, build y `git diff --check` pasan. Reportar comandos y resultados separados.

## Comprobaciones autorizadas para la auditoría

- `uv run ruff check`
- `uv run ruff format --check`
- `uv run mypy`
- `uv run pytest -q`
- `npm --prefix web run lint`
- `npm --prefix web run typecheck`
- `npm --prefix web run test`
- `npm --prefix web run build`
- `git diff --check`

No se ejecuta smoke contra Codex real en esta fase: el plan lo define como opt-in. No se hacen cambios fuera de las rutas listadas ni escrituras externas.

Evidencia local: Ruff y formato (67 archivos), mypy (47 fuentes), pytest (55 passed, una advertencia Starlette/httpx), lint, typecheck, Vitest (6 passed), build web y `git diff --check`: PASS. El runner registró una denegación de gate a una llamada auxiliar `manage_task status` durante la espera de pytest; no produjo acciones externas. `result.json` informa `denied_actions: []`, `changed_sources: []`, `missing_commands: []`; todos los comandos terminaron y el veredicto fue APROBADO.
