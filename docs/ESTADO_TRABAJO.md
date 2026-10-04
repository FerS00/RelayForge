# Estado de trabajo

## Fase 1: chat local con Claude Code

Estado: **Completada (2026-10-03)**. Auditoría de Antigravity: APROBADO (criterios 1-13, 15 y 16; 8 comprobaciones en verde). Criterio 14 ejecutado por el coordinador: PASS (ver «Criterio 14»). Texto histórico abajo: El código cubre el alcance de `docs/specs/FASE_1.md`. La suite de Python y las tareas que requieren procesos de Vite quedaron bloqueadas por `EPERM`/`WinError 5` del sandbox; no se consideran aprobadas. La prueba manual del criterio 14 está pendiente.

Entorno registrado: Python 3.13.15, uv 0.12.3, Node.js 24.19.0, npm 11.17.0 y Vite 7.3.6. La [guía oficial de Vite 7](https://v7.vite.dev/guide/) requiere Node.js 20.19+ o 22.12+; Node.js 24.19.0 satisface ese requisito.

### Corrección 1

El coordinador ejecutó pytest fuera del sandbox y reportó 3 fallos y 9 errores. Se corrigió la inferencia de modelos de respuesta en los tres endpoints que devuelven uniones con respuestas HTTP; se cambió el lanzamiento `.cmd`/`.bat` a una cadena para `cmd.exe`, manteniendo lista de argumentos para ejecutables directos, y se rechazan metacaracteres antes de crear los archivos de salida. `claude_model` ahora acepta solo `^[A-Za-z0-9._:-]{1,100}$` o vacío. `kill` y `kill_all` toleran ejecuciones ya terminadas. Se añadieron pruebas unitarias para el lanzador `.cmd`, argumentos con metacaracteres, proceso terminado y modelo inválido.

Validación tras la corrección: `uv run ruff check` PASS; `uv run ruff format --check` PASS (42 archivos); `uv run mypy` PASS (32 archivos). Pytest no se repitió en esta corrección; los resultados fuera del sandbox de la ejecución anterior siguen pendientes de confirmar con el coordinador.

### Corrección 2

El coordinador reportó 2 fallos y una prueba inestable en pytest. `send_message` ahora usa una transacción que confirma antes de publicar `step.started`; las otras escrituras del servicio ya usan `sessionmaker.begin()` o `session.commit()` antes de publicar. El stream se suscribe sincrónicamente en el manejador antes de devolver las cabeceras. `kill` cierra el Job Object y espera la terminación del proceso y sus descendientes con un límite total de 5 segundos. El cierre de FastAPI ahora usa `lifespan`.

Se añadió la comprobación del primer evento y secuencia consecutiva a la integración de chat, y una integración SSE que envía el POST inmediatamente después de recibir las cabeceras y comprueba que llega `step.started`. Pytest no se ejecutó tras esta corrección; el coordinador debe repetirlo fuera del sandbox. Validación ejecutada: `uv run ruff check` PASS; `uv run ruff format --check` PASS (42 archivos); `uv run mypy` PASS (32 archivos).

### Dependencias

| Dependencia | Uso |
|---|---|
| FastAPI | API HTTP, validación de solicitudes y respuestas. |
| Uvicorn | Servidor ASGI local. |
| SQLAlchemy | Modelos y persistencia SQLite. |
| Alembic | Migraciones versionadas de la base. |
| pydantic-settings | Modelo validado de configuración. |
| PyYAML | Lectura de `config/settings.yaml`. |
| httpx | Cliente de integración para API y SSE. |
| psutil | Comprobación de procesos descendientes en pruebas. |
| pytest | Pruebas Python. |
| Ruff | Lint y formato Python. |
| mypy | Comprobación estática de tipos. |
| types-PyYAML | Tipos para PyYAML usados por mypy. |
| React / React DOM | Interfaz de conversación y renderizado web. |
| React Router DOM | Navegación por hash de conversaciones. |
| TanStack Query | Carga y actualización de datos HTTP. |
| Vite / plugin React | Desarrollo y build de la interfaz. |
| TypeScript | Tipado de la aplicación web. |
| ESLint y plugins | Lint de TypeScript, React y Hooks. |
| Vitest | Pruebas unitarias de la interfaz. |
| jsdom | DOM simulado para pruebas web. |
| Testing Library (React, jest-dom, user-event) | Pruebas de comportamiento de componentes. |
| @types/react / @types/react-dom | Tipos de React para TypeScript. |

### Validaciones ejecutadas

| Comando | Resultado observado |
|---|---|
| `uv lock` | Correcto; resolvió 38 paquetes. |
| `uv sync` | Correcto; instaló/sincronizó 38 paquetes. |
| `uv run ruff check` | Correcto: `All checks passed!`. |
| `uv run ruff format --check` | Correcto: 42 archivos ya formateados. |
| `uv run mypy` | Correcto: sin problemas en 32 archivos fuente. |
| `uv run pytest` | Falló durante setup de 15 pruebas; 6 pasaron. `tmp_path` y el caché de pytest recibieron `PermissionError: [WinError 5] Access is denied` antes de ejecutar esas pruebas. Reintentar con una ruta temporal dentro del workspace también fue denegado. |
| `npm --prefix web ci` | Falló con `npm error code EPERM`, `syscall spawn` en el paso de instalación de esbuild. |
| `npm_config_ignore_scripts=true npm --prefix web ci` | Correcto como instalación de diagnóstico (270 paquetes), pero no sustituye la instalación CI solicitada porque omite scripts de paquetes. |
| `npm --prefix web run lint` | Correcto. |
| `npm --prefix web run typecheck` | Correcto. |
| `npm --prefix web run test` | No ejecutó pruebas: `Error: spawn EPERM` al iniciar el servicio esbuild que carga `vite.config.ts`. |
| `npm --prefix web run build` | No ejecutó el build: `Error: spawn EPERM` al cargar la configuración mediante esbuild. |

`npm` necesitó una caché local temporal por denegación de acceso a la caché global. `uv` se ejecutó con `UV_NO_CACHE=1` porque la caché global no era accesible.

### Criterios de aceptación

| N.º | Estado | Evidencia y pendiente |
|---:|---|---|
| 1 | Parcial | La implementación y las fixtures están en las rutas permitidas; no hay imports desde `pocs/`. El estado inicial del árbol ya incluía cambios ajenos a esta fase en `docs/PLAN_PROYECTO.md`, `docs/POC_RESULTADOS.md`, `docs/specs/FASE_0C.md`, `pocs/README.md`, `pocs/poc10_autostart/probe.py`, `pocs/poc10_autostart/register-task.ps1`, `pocs/tests/test_dry_run.py`, `pocs/tests/test_probe_parse.py`, `pocs/tests/test_tailscale_app.py` y `docs/GUIA_LAPTOP_RESERVAS.md`; se conservaron sin cambios. Por ello `git status` no queda limitado a los archivos de la sección 5. |
| 2 | Parcial | Ruff, formato, mypy, lint y typecheck pasaron. Pytest, instalación `npm ci`, Vitest y build están bloqueados por el sandbox según los resultados anteriores. Las pruebas usan `tests/fakes/fake_agent.py`; no se ejecutaron CLIs reales. |
| 3 | Parcial | Las tres pruebas del parser pasaron con las fixtures; el resto de la validación Python afectada por setup no pudo ejecutarse. |
| 4 | Pendiente de ejecución | Hay una prueba de flujo SSE con servidor Uvicorn y agente falso; pytest no pudo preparar sus directorios temporales. |
| 5 | Parcial | El fake produce eventos de fragmentos y hay cobertura automatizada; no se ejecutó Vitest ni la comprobación manual con Claude real. |
| 6 | Parcial | El adaptador fija los argumentos de sesión, permisos y denegaciones; su prueba unitaria pasó. La continuidad contextual con Claude real es parte de la prueba manual pendiente. |
| 7 | Parcial | Hay persistencia/recarga de conversaciones implementada; pruebas de integración y recarga manual de navegador pendientes. |
| 8 | Parcial | La búsqueda estática no encontró renderizadores HTML inseguros y el parser descarta metadatos no textuales; las pruebas HTTP/SSE y la comprobación visual manual están pendientes. |
| 9 | Parcial | El bind está fijado a loopback y están implementadas las validaciones Host, Origin, tipo de contenido y CSP; las pruebas HTTP no se pudieron ejecutar por el bloqueo de setup. |
| 10 | Parcial | El supervisor implementa lectura incremental, límite de línea y Job Objects; las pruebas correspondientes no pudieron completar el setup de pytest. |
| 11 | Parcial | Están implementados los estados de error, concurrencia e idempotencia; las pruebas de integración no pudieron ejecutarse por el bloqueo de `tmp_path`. |
| 12 | Parcial | Migración SQLite/Alembic implementada; las pruebas de upgrade, downgrade y pragmas quedaron bloqueadas por setup. |
| 13 | Parcial | CLI, settings y archivos estáticos implementados; la prueba CLI pasó, pero los casos de arranque restantes y el flujo desde otro directorio no están verificados. |
| 14 | Pendiente manual | Debe ejecutarla el usuario o coordinador con Claude Code real y la interfaz. Registrar fecha, versión y resultados de los apartados (a)–(f), incluida la verificación de que no se crea ningún archivo ni se delega en otra CLI. POC-01b ya consta como PASS en la especificación, con Claude Code 2.1.283; no sustituye esta aceptación manual. |
| 15 | Parcial | Las fixtures se copiaron byte a byte y se comprobaron: `text_turn.ndjson` SHA-256 `033b34a84fa1accb93702770e6ddc2128dfb90963e400ec942baff9c9a244c09`; `resume_turn.ndjson` SHA-256 `b0e8a76adc4d614c32c06dd87106f00e9a18d712952181499201ec6a557f3efe`. Se verificaron rutas personales y listas de skills; no se hallaron. Los 68 archivos inspeccionados hasta este checkpoint no tenían BOM, CRLF ni rutas personales. `LICENSE` se contrastó con el texto oficial Apache-2.0. |
| 16 | Parcial | El listado de módulos y rutas inspeccionado no mostró módulos de fases posteriores; las verificaciones automatizadas globales no pudieron ejecutarse completamente. |

## Próximos pasos (historial de la Fase 1)

Los tres pasos anteriores quedaron resueltos: pytest y la web se ejecutaron fuera del sandbox (30/30 y todo en verde), el criterio 14 está registrado abajo y el commit de la Fase 1 incluye solo sus rutas más `.gitignore` y la documentación.

## Criterio 14 — prueba manual con Claude real (2026-10-03, Claude Code 2.1.283, coordinador)

Servidor `relayforge serve --port 8797` (8787 lo ocupa otra aplicación local), repositorio de pruebas como `workspace_dir`.

| Apartado | Resultado |
|---|---|
| (a) Fragmentos (criterio 5) | PASS sin herramientas: 5 actualizaciones en 2,4 s antes del mensaje completo; concatenación idéntica al mensaje. Limitación de la CLI confirmada: en turnos con herramientas, Claude emite los fragmentos de la respuesta final de golpe (archivo y pipe por igual), así que solo hay una actualización. No es un defecto de RelayForge. |
| (b) Contexto (criterio 6) | PASS: el segundo turno respondió `AMBAR-3`. |
| (c) Recarga (criterio 7) | PASS: API y URL `#/c/<id>` reconstruyen los 4 mensajes en orden. |
| (d) Sin razonamiento ni metadatos | PASS: API, SSE e interfaz solo muestran texto. |
| (e) Solo chat | PASS: no creó `rf-intento.txt`, no ejecutó `codex --version`; `git status --porcelain` igual antes y después. |
| (f) 390 px | PASS: una columna, menú plegado, campo de envío visible, sin desplazamiento horizontal. |

Otros: puerto ocupado → código 2 con mensaje; Ctrl+Break → código 0. `npm audit`: 0 vulnerabilidades en producción; 2 moderadas en dependencias de desarrollo (Vitest), pendientes de revisar.

## Relevo — continuar desde la laptop (2026-10-03)

**Decisión del usuario:** el desarrollo continúa en la laptop para no duplicar trabajo entre máquinas. La PC principal queda sin cambios pendientes tras el commit de la Fase 1.

### Estado verificado al cerrar en la PC principal

- Plan: `docs/PLAN_PROYECTO.md`. Fase 0 completada; **Fase 1 completada**; Fases 2-10 aprobadas en bloque (D-12), pendientes; Fase 11 pendiente de aprobación.
- Decisiones vigentes: D-12 (ejecución en bloque y reglas de parada), D-13 (varias tareas por repositorio, cada una en su worktree), D-14 (crear repositorios locales), D-15 (interfaz de agente de IA), D-16 (stream SSE por conversación, sin ajuste de host en la Fase 1, texto plano).
- Reservas abiertas: R-1 (push con Git Credential Manager desde una tarea programada), R-2 (horarios del arranque), R-4a (falsificación de cabeceras desde otro dispositivo). R-4b se cierra en la Fase 4. Guía: `docs/GUIA_LAPTOP_RESERVAS.md`; el repositorio de pruebas para R-1 es privado y su URL se dio en la conversación (no se publica aquí).

### Primeros pasos en la laptop

1. `git pull --ff-only` en `C:\Dev\RelayForge`.
2. Entorno: `uv sync`, `npm --prefix web ci`, `npm --prefix web run build` (Node.js 20.19+ o 22.12+; la PC usa 24.19.0).
3. Comprobación: `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`, `uv run pytest -q` (30 pruebas) y `npm --prefix web run lint`, `typecheck`, `test`.
4. Arranque de prueba: `RELAYFORGE_WORKSPACE_DIR=<repo de pruebas>` y `uv run relayforge serve` (puerto 8787 por defecto; usa `--port` si está ocupado).
5. Ejecutar `docs/GUIA_LAPTOP_RESERVAS.md` para cerrar R-1, R-2 y R-4a.
6. Siguiente fase: **Fase 2** (Jobs persistentes, máquina de estados y recuperación básica). Flujo: especificación de Claude en `docs/specs/FASE_2.md`, implementación de Codex, auditoría de Antigravity, verificación fuera del sandbox y cierre en el plan.

### Lecciones operativas (aplican a todas las fases)

- El sandbox de Codex bloquea los temporales de pytest y los procesos de Vite: el coordinador ejecuta pytest y la web fuera del sandbox y devuelve la salida exacta.
- El runner de Antigravity rechaza archivos cuyo nombre empieza por `.env` (incluido `.env.example`): se revisan aparte.
- Modelo por defecto de Antigravity: `gemini-3.8-flash-medium` con `--effort medium`.
- Los fragmentos de Claude solo llegan de forma progresiva en turnos sin herramientas; con herramientas, la CLI emite la respuesta final de golpe.
- En la PC principal el puerto 8787 lo ocupa otra aplicación local (Docker); en la laptop no está verificado.
- Dependencias de desarrollo web: `npm audit` informa 2 vulnerabilidades moderadas en Vitest (solo pruebas locales); revisar en la Fase 10.
