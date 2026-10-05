# Verificación y aceptación

Estado de los gates locales automatizados del candidato: **Aprobado con observaciones**. El producto sigue en **desarrollo temprano** y su aceptación operativa permanece pendiente.

Los [resultados originales](evidence/2026-10-05-console-checks.json) preservan el primer rechazo. La [auditoría correctiva](evidence/2026-10-05-console-correction.json) registra la revisión vigente sin logs completos ni credenciales.

## Evidencia actual — 2026-10-05

Auditoría correctiva `e07678935a1f49acb1d867add49bf39d`, Antigravity `gemini-3.8-flash-high`, esfuerzo high: **APROBADO**, 50/50 comandos, cero denegaciones, cero cambios del auditor y cero checks omitidos. El primer audit `56984be1120c4cbd8ff9aeca093c4cf2` fue rechazado; ambos hallazgos quedaron corregidos y la revisión nueva confirmó los gates locales. La ejecución intermedia `5457f9fa71fa4b86be582a29ec77c0a7` no cuenta como aprobación: su gate registró `manage_task` denegado.

| Comprobación | Resultado | Límite |
|---|---|---|
| `git diff --check` | Aprobado | Avisos LF/CRLF; no hay commit nuevo. |
| `uv run ruff check src tests` | Aprobado | El I001 de `tests/integration/test_doctor.py` fue corregido. |
| `uv run ruff format --check src tests` | Aprobado | 123 archivos. |
| `uv run mypy src` | Aprobado | 78 fuentes. |
| `uv run pytest -q` (41 archivos, ejecutados individualmente por el auditor) | Aprobado con observaciones | 139 passed/1 skipped por WinError 1314 de symlink; aviso deprecado Starlette/httpx. |
| `npm --prefix web run lint` | Aprobado | ESLint. |
| `npm --prefix web run typecheck` | Aprobado | TypeScript. |
| `npm --prefix web run test` | Aprobado | 12 archivos/18 pruebas Vitest. |
| `npm --prefix web run build` | Aprobado | Build Vite. |
| Navegador móvil emulado | Aprobado con observaciones | Backend aislado y fakes; no prueba móvil físico ni cuentas reales. |
| Docker build Windows | Aprobado con observaciones | Imagen nueva con tres CLIs construida; contenedor observado aún con imagen anterior. |
| CI GitHub para esta revisión | No ejecutado | La auditoría local no equivale a CI remota. |

En navegador se comprobó crear proyecto, seleccionar modelos, crear Job Claude, fallo simulado de cuota, relevo Codex, aprobación humana antes de implementar, archivo/diff sintéticos y resultado local. Historial persistió tras recarga y reinicio del servidor de prueba. Vistas revisadas en 360 px no mostraron desbordamiento; validación HTML de modelo acepta formato permitido y rechaza caracteres inválidos. Se corrigieron previamente el pattern HTML y un timeout de probe Windows que podía esperar pipes heredados.

## Hallazgos abiertos

| Severidad | Categoría | Evidencia/impacto | Cierre sugerido |
|---|---|---|---|
| Informativo | Cobertura Windows | Prueba de symlink omitida por WinError 1314 | Ejecutarla en un entorno con privilegio de symlink; no elevar silenciosamente. |
| Alto | Aceptación operativa | No hay Job completo validado con las tres CLIs del contenedor nuevo | Login en entorno real y tarea desechable desde teléfono; Fase 12. |
| Medio | Recuperación | Reinicio físico con Job activo/cancelación real siguen pendientes | Matriz de PID/creación, estados y eventos; Fase 14. |

## Ejecución automatizada y pruebas reales

La política de tests exige fakes o dry-run, sin cuentas/CLIs reales. Los probes de login/versiones del servicio se ejecutan por separado. El test de fingerprint usa un doble sintético para `_agent`; el login y la ejecución real de proveedores se validan por separado.

Pruebas reales pendientes: login Codex/Antigravity en el contenedor; supervivencia de credenciales tras recreate; tarea y SSE desde móvil; pipeline con checks/auditoría real; cancelación/reinicio; backup/restauración. CI remota todavía no se ha comprobado. Resultados históricos de pairing o de otros modos/checkouts no sustituyen esos criterios.

Las suites y comandos de [CONTRIBUTING](../CONTRIBUTING.md) son verificaciones obligatorias de cambios futuros. No presentar el veredicto textual de la CLI como aprobación si el gate registra denegaciones o faltan checks. Cada fase nueva tiene sus criterios en el [plan](PLAN_PROYECTO.md).
