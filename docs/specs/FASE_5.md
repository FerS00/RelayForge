> Especificación histórica. Las referencias numeradas al plan corresponden al [plan anterior archivado](../archive/PLAN_PROYECTO_2026-10-05_PREVIO.md); para alcance/estado y nuevas fases consulta el [plan vigente](../PLAN_PROYECTO.md). Este aviso no cambia sus criterios previamente aprobados.

# Fase 5 — Checks declarados

Estado: **Completada** (2026-10-04). Antigravity APROBADO: 7 criterios, 10/10 checks; modelo `gemini-3.8-flash-low`, esfuerzo `low`. Python 75 passed, web 8/8, Ruff, formato, mypy, ESLint, TypeScript, build y diff-check PASS. El test de timeout confirmó que no queda ningún PID hijo.

## ESPECIFICACIÓN TÉCNICA (PARA CODEX)

### Objetivo

Ejecutar después de la implementación únicamente los checks declarados por el repositorio, con `argv`, entorno filtrado, timeout y terminación del árbol mediante Job Object. Persistir y emitir un resumen `checks.result` visible en la actividad del Job.

### Rutas afectadas

- `config/schemas/check-command.schema.json`: contrato de comando.
- `src/relayforge/adapters/checks/{__init__.py,adapter.py}`: validación, armado de `LaunchPlan`, entorno permitido y resumen JUnit/pytest.
- `src/relayforge/core/checks.py`, `src/relayforge/core/scheduler.py`, `src/relayforge/core/jobs.py`: ciclo TESTING y persistencia de pasos/resultados.
- `src/relayforge/core/repositories.py`, `src/relayforge/api/schemas.py`, `src/relayforge/api/routes/repositories.py`: guardar declaraciones en el campo existente `check_commands_json`.
- `web/src/api.ts`, `web/src/pages/Repositories.tsx`, `web/src/pages/JobDetail.tsx`, `web/src/styles.module.css`: configurar argv y mostrar resultado.
- `tests/fakes/fake_check.py`, `tests/unit/test_checks_adapter.py`, `tests/integration/test_checks_workflow.py`, `tests/integration/test_repositories_api.py`, `tests/integration/test_implementation_workflow.py`, `web/src/pages/Repositories.test.tsx`, `web/src/pages/JobDetail.test.tsx`.
- Este documento, `docs/PLAN_PROYECTO.md` y `docs/ESTADO_TRABAJO.md`.

### Contratos y reglas

1. Cada check contiene `name` (1–80 caracteres), `argv` (1–64 argumentos, sin NUL, hasta 4096 caracteres total) y `timeout_seconds` (1–3600; default 600). El esquema rechaza strings de shell, argv vacíos y ejecutables de shell (`cmd`, PowerShell, `sh`, `bash`, `wscript`, `cscript`). No se añade `shell=True`.
2. El cwd es la raíz del worktree creado por RelayForge; no se acepta un cwd desde la API. El comando se lanza con `Supervisor` y el Job Object existente.
3. El entorno del proceso solo copia `PATH`, `PATHEXT`, `SYSTEMROOT`, `WINDIR`, `TEMP`, `TMP` y `COMSPEC` cuando existen. No se heredan variables de agente, Git, nube, proxy ni perfil. Los checks no instalan dependencias automáticamente.
4. El proceso se sondea hasta terminar. Al exceder timeout se termina el Job Object y se registra estado `timeout`; cualquier descendiente debe quedar terminado. Se limita la lectura de salida y no se copia la salida completa a eventos.
5. Si existe XML JUnit declarado como argumento de salida convencional (`--junitxml=<ruta>` o `--junit-xml=<ruta>`), se parsean contadores solo si la ruta relativa resuelta queda bajo el worktree. Para pytest se parsea el resumen final. XML inválido/ausente no inventa conteos.
6. `checks.result` persiste nombre, estado, exit code, duración, conteos conocidos y timeout; no incluye stdout/stderr sin filtrar. El Job conserva cada ejecución como `JobStep(kind="checks")` y serializa el resumen en su timeline.
7. Los repositorios sin comandos declarados omiten TESTING. Los repositorios con checks mueven `IMPLEMENTING → TESTING`; fallo, timeout o código distinto de cero emite resultado y termina el Job como `FAILED`. No se reintenta.
8. Un comando se configura mediante una lista JSON de objetos; la UI guarda esta lista junto al repositorio. No se aceptan scripts de shell ni comandos enviados desde el Job.

### Criterios de aceptación

1. Solo se ejecuta el argv almacenado para el repositorio y bajo el worktree.
2. Una variable sintética `ANTHROPIC_API_KEY`/`CODEX_HOME` del host no aparece en `LaunchPlan.env`; las variables permitidas se preservan.
3. Un check exitoso emite y persiste `checks.result` con código y conteos conocidos; la UI muestra el resultado.
4. Un check fallido y uno vencido terminan en `FAILED` con estado explícito y sin reintento.
5. El timeout termina el árbol del proceso y no deja procesos hijos.
6. JUnit válido produce contadores; XML inválido o fuera del worktree queda sin conteos y no se lee.
7. Ruff, formato, mypy, pytest, lint, typecheck, Vitest, build y `git diff --check` pasan; Antigravity audita la fase y ejecuta los checks exactos.

### Exclusiones

No se prueban CLIs reales de agente, no se instalan dependencias, no se ejecutan suites de repositorios reales, no se ejecutan herramientas de shell, y no se suben artefactos ni datos a servicios externos. La configuración por repositorio sigue siendo explícita.
